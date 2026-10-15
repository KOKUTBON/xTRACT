from __future__ import annotations

import abc
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ProtocolConnector(abc.ABC):
    """Delivers protocol registration commands to a target system."""

    @abc.abstractmethod
    def dispatch(self, command: dict, connector: dict, attempt_number: int) -> dict:
        """Deliver a command.

        Returns a dictionary with:
        - mode: "success" | "retryable_failure" | "permanent_failure"
        - http_status: int | None
        - error_code: str | None
        - response: protocol-registration-response payload on success, else None
        """
        raise NotImplementedError


def build_response(command: dict, connector: dict, reference_id: str, uri: str) -> dict:
    return {
        "schema_version": "1.0.0",
        "command_id": command["command_id"],
        "connector_id": connector["connector_id"],
        "document_id": command["document_id"],
        "delivery_status": "synchronized",
        "remote_reference": {
            "reference_type": command["payload"].get("requested_reference_type", "protocol_id"),
            "reference_id": reference_id,
            "status": "synchronized",
            "uri": uri,
            "synchronized_at": now_utc(),
        },
        "error_code": None,
        "audit_correlation_id": command["audit_context"]["correlation_id"],
    }


class LocalRegistryConnector(ProtocolConnector):
    """Built-in registry that assigns sequential reference numbers per year.

    It gives every validated document an authoritative registration number without
    requiring an external protocol system.
    """

    def __init__(self, database=None) -> None:
        self.db = database

    def dispatch(self, command: dict, connector: dict, attempt_number: int) -> dict:
        prefix = connector.get("reference_prefix", "REG")
        year = datetime.now(timezone.utc).year
        institution = command["caller"]["institution_id"]
        if self.db is not None:
            sequence = self.db.next_sequence_value(
                f"{connector['connector_id']}:{institution}:{year}"
            )
        else:
            sequence = attempt_number
        reference_id = f"{prefix}-{year}-{sequence:06d}"
        uri = f"urn:xtract:{connector['connector_id']}:{reference_id}"
        return {
            "mode": "success",
            "http_status": None,
            "error_code": None,
            "response": build_response(command, connector, reference_id, uri),
        }


class HttpProtocolConnector(ProtocolConnector):
    """Posts commands as JSON to an external protocol registry over HTTP(S).

    The remote endpoint must answer with a JSON body containing either a
    ``remote_reference`` object or a ``reference_id`` (and optional ``uri``).
    """

    def __init__(self, timeout_seconds: float = 15.0, opener=None) -> None:
        self.timeout_seconds = timeout_seconds
        self.opener = opener or urllib.request.urlopen

    def dispatch(self, command: dict, connector: dict, attempt_number: int) -> dict:
        base_url = (connector.get("base_url") or "").rstrip("/")
        if not base_url:
            return {
                "mode": "permanent_failure",
                "http_status": None,
                "error_code": "connector_not_configured",
                "response": None,
            }
        url = base_url + connector.get("endpoint_path", "/protocol-registrations")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Idempotency-Key": command["idempotency_key"],
        }
        if connector.get("auth_profile") == "bearer_token":
            token = os.environ.get(connector.get("auth_token_env", ""), "")
            if not token:
                return {
                    "mode": "permanent_failure",
                    "http_status": None,
                    "error_code": "missing_credentials",
                    "response": None,
                }
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(
            url, data=json.dumps(command).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as http_response:
                status = http_response.status
                body = json.loads(http_response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            retryable = exc.code in RETRYABLE_HTTP_STATUSES
            return {
                "mode": "retryable_failure" if retryable else "permanent_failure",
                "http_status": exc.code,
                "error_code": str(exc.code),
                "response": None,
            }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {
                "mode": "retryable_failure",
                "http_status": None,
                "error_code": "timeout" if isinstance(exc, TimeoutError) else "unreachable",
                "response": None,
            }
        except ValueError:
            return {
                "mode": "permanent_failure",
                "http_status": None,
                "error_code": "invalid_response",
                "response": None,
            }

        remote = body.get("remote_reference") or {}
        reference_id = remote.get("reference_id") or body.get("reference_id")
        if not reference_id:
            return {
                "mode": "permanent_failure",
                "http_status": status,
                "error_code": "missing_reference",
                "response": None,
            }
        uri = remote.get("uri") or body.get("uri") or f"{base_url}/{reference_id}"
        return {
            "mode": "success",
            "http_status": status,
            "error_code": None,
            "response": build_response(command, connector, str(reference_id), uri),
        }


def _extract_field_value(command: dict, *field_codes: str) -> str | None:
    """Extract a value from command metadata fields by field code aliases."""
    for item in command.get("payload", {}).get("metadata", []):
        if item.get("field_code") in field_codes and item.get("value") is not None:
            return str(item["value"])
    return None


def generate_agid_segnatura_xml(
    command: dict, connector: dict, reference_id: str, date_str: str
) -> str:
    """Generate official AgID Segnatura.xml according to Italian PA interoperability rules."""
    admin_code = connector.get("agid_administration_code") or command["caller"]["institution_id"]
    aoo_code = connector.get("agid_aoo_code") or command["caller"]["office_id"]
    doc_id = command["document_id"]
    payload = command.get("payload", {})
    filename = payload.get("source_filename") or "document"
    checksum = payload.get("checksum_sha256") or "0" * 64

    subject = (
        _extract_field_value(command, "subject", "oggetto", "title")
        or payload.get("document_type_name")
        or "Protocollo Informatico"
    )
    sender = (
        _extract_field_value(
            command, "sender", "mittente", "applicant", "supplier_name", "supplier"
        )
        or "Mittente Non Specificato"
    )
    recipient = (
        _extract_field_value(command, "recipient", "destinatario", "customer_name", "customer")
        or admin_code
    )

    root = ET.Element("Segnatura", xmlns="http://www.agid.gov.it/protocollo/segnatura.v1")
    intestazione = ET.SubElement(root, "Intestazione")

    identificatore = ET.SubElement(intestazione, "Identificatore")
    ET.SubElement(identificatore, "CodiceAmministrazione").text = admin_code
    ET.SubElement(identificatore, "CodiceAOO").text = aoo_code
    ET.SubElement(identificatore, "NumeroRegistrazione").text = reference_id
    ET.SubElement(identificatore, "DataRegistrazione").text = date_str

    origine = ET.SubElement(intestazione, "Origine")
    ET.SubElement(origine, "Mittente").text = sender

    destinazione = ET.SubElement(intestazione, "Destinazione")
    ET.SubElement(destinazione, "Destinatario").text = recipient

    ET.SubElement(intestazione, "Oggetto").text = subject

    descrizione = ET.SubElement(root, "Descrizione")
    doc_elem = ET.SubElement(descrizione, "Documento", id=doc_id)
    ET.SubElement(doc_elem, "Nome").text = filename
    impronta = ET.SubElement(doc_elem, "Impronta", algoritmo="SHA-256")
    impronta.text = checksum

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


class AgidProtocolloConnector(ProtocolConnector):
    """Italian Public Administration Protocollo Informatico connector (AgID).

    Generates official XML Segnatura envelopes compliant with DPCM 3 Dicembre 2013
    and AgID interoperability guidelines.
    """

    def __init__(self, database=None, timeout_seconds: float = 15.0, opener=None) -> None:
        self.db = database
        self.timeout_seconds = timeout_seconds
        self.opener = opener or urllib.request.urlopen

    def dispatch(self, command: dict, connector: dict, attempt_number: int) -> dict:
        prefix = connector.get("reference_prefix", "AGID")
        year = datetime.now(timezone.utc).year
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        institution = command["caller"]["institution_id"]

        if self.db is not None:
            sequence = self.db.next_sequence_value(
                f"{connector['connector_id']}:{institution}:{year}"
            )
        else:
            sequence = attempt_number
        reference_id = f"{prefix}-{year}-{sequence:07d}"

        segnatura_xml = generate_agid_segnatura_xml(command, connector, reference_id, date_str)

        base_url = (connector.get("base_url") or "").rstrip("/")
        if not base_url:
            # Sovereign local AgID registration mode
            uri = f"urn:agid:protocollo:{institution}:{reference_id}"
            resp = build_response(command, connector, reference_id, uri)
            resp["raw_payload"] = segnatura_xml
            return {
                "mode": "success",
                "http_status": None,
                "error_code": None,
                "response": resp,
            }

        # Remote AgID interoperability gateway delivery
        url = base_url + connector.get("endpoint_path", "/agid/protocollo")
        headers = {
            "Content-Type": "application/xml; charset=utf-8",
            "Accept": "application/json, application/xml",
            "Idempotency-Key": command["idempotency_key"],
            "X-AgID-Amministrazione": connector.get("agid_administration_code") or institution,
            "X-AgID-AOO": connector.get("agid_aoo_code") or command["caller"]["office_id"],
        }
        if connector.get("auth_profile") == "bearer_token":
            token = os.environ.get(connector.get("auth_token_env", ""), "")
            if not token:
                return {
                    "mode": "permanent_failure",
                    "http_status": None,
                    "error_code": "missing_credentials",
                    "response": None,
                }
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(
            url, data=segnatura_xml.encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as http_response:
                status = http_response.status
                raw = http_response.read().decode("utf-8") or "{}"
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = {"reference_id": reference_id}
        except urllib.error.HTTPError as exc:
            retryable = exc.code in RETRYABLE_HTTP_STATUSES
            return {
                "mode": "retryable_failure" if retryable else "permanent_failure",
                "http_status": exc.code,
                "error_code": str(exc.code),
                "response": None,
            }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {
                "mode": "retryable_failure",
                "http_status": None,
                "error_code": "timeout" if isinstance(exc, TimeoutError) else "unreachable",
                "response": None,
            }

        remote = body.get("remote_reference") or {}
        remote_ref_id = remote.get("reference_id") or body.get("reference_id") or reference_id
        uri = (
            remote.get("uri")
            or body.get("uri")
            or f"urn:agid:protocollo:{institution}:{remote_ref_id}"
        )
        resp = build_response(command, connector, str(remote_ref_id), uri)
        resp["raw_payload"] = segnatura_xml
        return {
            "mode": "success",
            "http_status": status,
            "error_code": None,
            "response": resp,
        }


def generate_peppol_ubl_xml(
    command: dict, connector: dict, invoice_id: str, issue_date: str
) -> str:
    """Generate standard European UBL 2.1 / Peppol BIS Billing 3.0 invoice XML."""
    currency = _extract_field_value(command, "currency", "valuta") or "EUR"
    total_amount = (
        _extract_field_value(command, "total_amount", "importo_totale", "total", "amount") or "0.00"
    )
    supplier_name = (
        _extract_field_value(command, "supplier_name", "fornitore", "supplier")
        or command["caller"]["institution_id"]
    )
    supplier_vat = (
        _extract_field_value(command, "vat_number", "partita_iva", "supplier_vat")
        or "IT00000000000"
    )
    customer_name = (
        _extract_field_value(command, "customer_name", "cliente", "customer")
        or "Pubblica Amministrazione"
    )

    root = ET.Element(
        "Invoice",
        xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
        attrib={
            "xmlns:cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
            "xmlns:cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
        },
    )
    ET.SubElement(
        root,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}CustomizationID",
    ).text = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
    ET.SubElement(
        root, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ProfileID"
    ).text = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
    ET.SubElement(
        root, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID"
    ).text = invoice_id
    ET.SubElement(
        root, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}IssueDate"
    ).text = issue_date
    ET.SubElement(
        root,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}DocumentCurrencyCode",
    ).text = currency

    # Supplier
    supp_party = ET.SubElement(
        root,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}AccountingSupplierParty",
    )
    party = ET.SubElement(
        supp_party,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}Party",
    )
    legal_ent = ET.SubElement(
        party,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}PartyLegalEntity",
    )
    ET.SubElement(
        legal_ent,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}RegistrationName",
    ).text = supplier_name
    ET.SubElement(
        legal_ent, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}CompanyID"
    ).text = supplier_vat

    # Customer
    cust_party = ET.SubElement(
        root,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}AccountingCustomerParty",
    )
    c_party = ET.SubElement(
        cust_party,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}Party",
    )
    c_legal_ent = ET.SubElement(
        c_party,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}PartyLegalEntity",
    )
    ET.SubElement(
        c_legal_ent,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}RegistrationName",
    ).text = customer_name

    # Monetary Total
    monetary = ET.SubElement(
        root,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}LegalMonetaryTotal",
    )
    ET.SubElement(
        monetary,
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}PayableAmount",
        currencyID=currency,
    ).text = total_amount

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


class PeppolRegistryConnector(ProtocolConnector):
    """Pan-European Public Procurement On-Line (Peppol) BIS Billing 3.0 connector.

    Transforms commercial invoices into standard EN 16931 / UBL 2.1 XML invoices
    for dispatch to Peppol Access Points.
    """

    def __init__(self, database=None, timeout_seconds: float = 15.0, opener=None) -> None:
        self.db = database
        self.timeout_seconds = timeout_seconds
        self.opener = opener or urllib.request.urlopen

    def dispatch(self, command: dict, connector: dict, attempt_number: int) -> dict:
        invoice_id = (
            _extract_field_value(command, "invoice_number", "numero_fattura", "number")
            or f"INV-{command['document_id'][:8]}"
        )
        issue_date = _extract_field_value(
            command, "invoice_date", "data_fattura", "date"
        ) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prefix = connector.get("reference_prefix", "PEPPOL")
        endpoint_id = connector.get("peppol_endpoint_id") or "0201:default"

        ubl_xml = generate_peppol_ubl_xml(command, connector, invoice_id, issue_date)

        base_url = (connector.get("base_url") or "").rstrip("/")
        if not base_url:
            # Sovereign local Peppol registration mode
            reference_id = f"{prefix}-{invoice_id}"
            uri = f"urn:peppol:invoice:{endpoint_id}:{reference_id}"
            resp = build_response(command, connector, reference_id, uri)
            resp["raw_payload"] = ubl_xml
            return {
                "mode": "success",
                "http_status": None,
                "error_code": None,
                "response": resp,
            }

        # Remote Peppol Access Point delivery
        url = base_url + connector.get("endpoint_path", "/peppol/outbox")
        headers = {
            "Content-Type": "application/xml; charset=utf-8",
            "Accept": "application/json, application/xml",
            "Idempotency-Key": command["idempotency_key"],
            "X-Peppol-Sender": endpoint_id,
        }
        if connector.get("auth_profile") == "bearer_token":
            token = os.environ.get(connector.get("auth_token_env", ""), "")
            if not token:
                return {
                    "mode": "permanent_failure",
                    "http_status": None,
                    "error_code": "missing_credentials",
                    "response": None,
                }
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(
            url, data=ubl_xml.encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as http_response:
                status = http_response.status
                raw = http_response.read().decode("utf-8") or "{}"
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = {"reference_id": f"{prefix}-{invoice_id}"}
        except urllib.error.HTTPError as exc:
            retryable = exc.code in RETRYABLE_HTTP_STATUSES
            return {
                "mode": "retryable_failure" if retryable else "permanent_failure",
                "http_status": exc.code,
                "error_code": str(exc.code),
                "response": None,
            }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {
                "mode": "retryable_failure",
                "http_status": None,
                "error_code": "timeout" if isinstance(exc, TimeoutError) else "unreachable",
                "response": None,
            }

        remote = body.get("remote_reference") or {}
        remote_ref_id = (
            remote.get("reference_id") or body.get("reference_id") or f"{prefix}-{invoice_id}"
        )
        uri = (
            remote.get("uri")
            or body.get("uri")
            or f"urn:peppol:invoice:{endpoint_id}:{remote_ref_id}"
        )
        resp = build_response(command, connector, str(remote_ref_id), uri)
        resp["raw_payload"] = ubl_xml
        return {
            "mode": "success",
            "http_status": status,
            "error_code": None,
            "response": resp,
        }


class WebhookProtocolConnector(ProtocolConnector):
    """Dispatches webhook notifications with HMAC-SHA256 signature verification."""

    def __init__(self, timeout_seconds: float = 15.0, opener=None) -> None:
        self.timeout_seconds = timeout_seconds
        self.opener = opener or urllib.request.urlopen

    def dispatch(self, command: dict, connector: dict, attempt_number: int) -> dict:
        base_url = (connector.get("base_url") or "").rstrip("/")
        if not base_url:
            return {
                "mode": "permanent_failure",
                "http_status": None,
                "error_code": "connector_not_configured",
                "response": None,
            }
        url = base_url + connector.get("endpoint_path", "")
        raw_body = json.dumps(command, sort_keys=True).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Event-Type": command.get("command_type", "protocol.register"),
            "X-Document-Id": command["document_id"],
            "Idempotency-Key": command["idempotency_key"],
        }
        secret_env = connector.get("webhook_secret_env", "")
        secret = os.environ.get(secret_env, "") if secret_env else ""
        if secret:
            sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            headers["X-Signature-SHA256"] = f"sha256={sig}"

        request = urllib.request.Request(url, data=raw_body, headers=headers, method="POST")
        try:
            with self.opener(request, timeout=self.timeout_seconds) as http_response:
                status = http_response.status
                body = json.loads(http_response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            retryable = exc.code in RETRYABLE_HTTP_STATUSES
            return {
                "mode": "retryable_failure" if retryable else "permanent_failure",
                "http_status": exc.code,
                "error_code": str(exc.code),
                "response": None,
            }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {
                "mode": "retryable_failure",
                "http_status": None,
                "error_code": "timeout" if isinstance(exc, TimeoutError) else "unreachable",
                "response": None,
            }
        except ValueError:
            return {
                "mode": "permanent_failure",
                "http_status": None,
                "error_code": "invalid_response",
                "response": None,
            }

        ref_id = (
            body.get("reference_id")
            or body.get("remote_reference", {}).get("reference_id")
            or f"WH-{command['command_id'][:8]}"
        )
        uri = (
            body.get("uri")
            or body.get("remote_reference", {}).get("uri")
            or f"urn:webhook:{connector['connector_id']}:{ref_id}"
        )
        return {
            "mode": "success",
            "http_status": status,
            "error_code": None,
            "response": build_response(command, connector, str(ref_id), uri),
        }


CONNECTOR_REGISTRY: dict[str, type[ProtocolConnector]] = {
    "local_registry": LocalRegistryConnector,
    "http_api": HttpProtocolConnector,
    "internal_api": HttpProtocolConnector,
    "agid_protocollo": AgidProtocolloConnector,
    "peppol_registry": PeppolRegistryConnector,
    "webhook": WebhookProtocolConnector,
}


def register_connector_type(channel_type: str, connector_cls: type[ProtocolConnector]) -> None:
    """Register a custom protocol connector class for a channel type."""
    CONNECTOR_REGISTRY[channel_type] = connector_cls
