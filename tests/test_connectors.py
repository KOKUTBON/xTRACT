from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import unittest
import urllib.error
import xml.etree.ElementTree as ET

from helpers import schema_errors

from xtract.integration.connector import (
    CONNECTOR_REGISTRY,
    AgidProtocolloConnector,
    PeppolRegistryConnector,
    ProtocolConnector,
    WebhookProtocolConnector,
    generate_agid_segnatura_xml,
    generate_peppol_ubl_xml,
    register_connector_type,
)
from xtract.integration.dispatcher import ProtocolDispatcher


class FakeHttpResponse:
    def __init__(self, body: dict | str | bytes | None = None, status: int = 200) -> None:
        self.status = status
        if isinstance(body, (dict, list)):
            self._body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            self._body = body.encode("utf-8")
        elif isinstance(body, bytes):
            self._body = body
        else:
            self._body = b"{}"

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def make_mock_opener(body=None, status=200, error=None):
    seen = {}

    def opener(request, timeout=15.0):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["data"] = request.data
        seen["method"] = request.get_method()
        if error:
            raise error
        return FakeHttpResponse(body=body, status=status)

    return opener, seen


class AgidConnectorTests(unittest.TestCase):
    def setUp(self):
        self.command = {
            "schema_version": "1.0.0",
            "command_id": "cmd-agid-001",
            "command_type": "protocol.register",
            "document_id": "doc-00000000-0000-0000-0000-000000000001",
            "idempotency_key": "idem-agid-001",
            "caller": {
                "user_id": "operator_it",
                "institution_id": "c_roma",
                "office_id": "affari_generali",
            },
            "payload": {
                "source_filename": "istanza_permesso.pdf",
                "checksum_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "document_type_name": "Permesso di Costruire",
                "metadata": [
                    {"field_code": "oggetto", "value": "Richiesta permesso di costruire via Roma"},
                    {"field_code": "richiedente", "value": "Mario Rossi"},
                    {"field_code": "mittente", "value": "Mario Rossi"},
                ],
            },
            "audit_context": {
                "correlation_id": "corr-agid-001",
            },
        }
        self.connector_config = {
            "connector_id": "agid_hub",
            "system_name": "agid-protocollo",
            "description": "AgID Interoperability Hub",
            "channel_type": "agid_protocollo",
            "auth_profile": "none",
            "status": "active",
            "reference_prefix": "PROT",
            "agid_administration_code": "c_roma",
            "agid_aoo_code": "AOO_01",
            "ownership": {
                "source_system_of_record": "xtract",
                "target_system_of_record": "agid-protocollo",
                "synchronization_owner": "integration-hub",
            },
            "authoritative_reference_types": ["registration_number"],
            "supported_commands": ["protocol.register"],
        }

    def test_generate_agid_segnatura_xml(self):
        xml_str = generate_agid_segnatura_xml(
            self.command, self.connector_config, "PROT-2026-0000123", "2026-03-15"
        )
        self.assertIn("<?xml", xml_str)
        root = ET.fromstring(xml_str)
        self.assertIn("Segnatura", root.tag)

        # Check Intestazione
        ns = {"ns": "http://www.agid.gov.it/protocollo/segnatura.v1"}
        ident = root.find(".//ns:Identificatore", ns)
        self.assertIsNotNone(ident)
        self.assertEqual(ident.find("ns:CodiceAmministrazione", ns).text, "c_roma")
        self.assertEqual(ident.find("ns:CodiceAOO", ns).text, "AOO_01")
        self.assertEqual(ident.find("ns:NumeroRegistrazione", ns).text, "PROT-2026-0000123")
        self.assertEqual(ident.find("ns:DataRegistrazione", ns).text, "2026-03-15")

        # Check Mittente & Oggetto
        self.assertEqual(root.find(".//ns:Mittente", ns).text, "Mario Rossi")
        self.assertEqual(
            root.find(".//ns:Oggetto", ns).text, "Richiesta permesso di costruire via Roma"
        )

        # Check Documento & Checksum
        doc = root.find(".//ns:Documento", ns)
        self.assertEqual(doc.get("id"), "doc-00000000-0000-0000-0000-000000000001")
        self.assertEqual(doc.find("ns:Nome", ns).text, "istanza_permesso.pdf")
        self.assertEqual(
            doc.find("ns:Impronta", ns).text,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )

    def test_agid_local_sovereign_dispatch(self):
        connector = AgidProtocolloConnector()
        res = connector.dispatch(self.command, self.connector_config, attempt_number=1)
        self.assertEqual(res["mode"], "success")
        self.assertIsNone(res["http_status"])
        self.assertIsNone(res["error_code"])
        resp_payload = res["response"]
        self.assertEqual(
            schema_errors("protocol-registration-response.v1.schema.json", resp_payload), []
        )
        remote = resp_payload["remote_reference"]
        self.assertTrue(remote["reference_id"].startswith("PROT-"))
        self.assertIn("urn:agid:protocollo:c_roma:", remote["uri"])
        self.assertIn("raw_payload", resp_payload)
        self.assertIn("Segnatura", resp_payload["raw_payload"])

    def test_agid_remote_http_dispatch(self):
        cfg = {
            **self.connector_config,
            "base_url": "https://protocollo.pa.gov.it",
            "endpoint_path": "/api/v1/registra",
        }
        opener, seen = make_mock_opener(
            body={"reference_id": "PROT-REMOTE-999", "uri": "https://protocollo.pa.gov.it/ref/999"}
        )
        connector = AgidProtocolloConnector(opener=opener)
        res = connector.dispatch(self.command, cfg, attempt_number=1)
        self.assertEqual(res["mode"], "success")
        self.assertEqual(res["http_status"], 200)
        self.assertEqual(res["response"]["remote_reference"]["reference_id"], "PROT-REMOTE-999")
        self.assertEqual(seen["url"], "https://protocollo.pa.gov.it/api/v1/registra")
        self.assertEqual(seen["headers"]["X-agid-amministrazione"], "c_roma")
        self.assertEqual(seen["headers"]["X-agid-aoo"], "AOO_01")
        self.assertIn(b"Segnatura", seen["data"])

    def test_agid_http_errors(self):
        cfg = {**self.connector_config, "base_url": "https://protocollo.pa.gov.it"}
        error_503 = urllib.error.HTTPError("u", 503, "Unavailable", {}, io.BytesIO(b""))
        opener, _ = make_mock_opener(error=error_503)
        res = AgidProtocolloConnector(opener=opener).dispatch(self.command, cfg, 1)
        self.assertEqual(res["mode"], "retryable_failure")
        self.assertEqual(res["http_status"], 503)


class PeppolConnectorTests(unittest.TestCase):
    def setUp(self):
        self.command = {
            "schema_version": "1.0.0",
            "command_id": "cmd-peppol-001",
            "command_type": "protocol.register",
            "document_id": "doc-00000000-0000-0000-0000-000000000002",
            "idempotency_key": "idem-peppol-001",
            "caller": {
                "user_id": "procurement_agent",
                "institution_id": "eu-agency",
                "office_id": "finance",
            },
            "payload": {
                "source_filename": "invoice_1024.pdf",
                "document_type_name": "Commercial Invoice",
                "metadata": [
                    {"field_code": "invoice_number", "value": "INV-2026-1024"},
                    {"field_code": "invoice_date", "value": "2026-03-20"},
                    {"field_code": "supplier_name", "value": "Acme Europe B.V."},
                    {"field_code": "supplier_vat", "value": "NL123456789B01"},
                    {"field_code": "customer_name", "value": "European Digital Agency"},
                    {"field_code": "total_amount", "value": "12500.50"},
                    {"field_code": "currency", "value": "EUR"},
                ],
            },
            "audit_context": {
                "correlation_id": "corr-peppol-001",
            },
        }
        self.connector_config = {
            "connector_id": "peppol_ap",
            "system_name": "peppol-access-point",
            "description": "Peppol BIS Billing 3.0 Hub",
            "channel_type": "peppol_registry",
            "auth_profile": "none",
            "status": "active",
            "reference_prefix": "PEPPOL",
            "peppol_endpoint_id": "9915:NL123456789B01",
            "ownership": {
                "source_system_of_record": "xtract",
                "target_system_of_record": "peppol-access-point",
                "synchronization_owner": "integration-hub",
            },
            "authoritative_reference_types": ["registration_number"],
            "supported_commands": ["protocol.register"],
        }

    def test_generate_peppol_ubl_xml(self):
        xml_str = generate_peppol_ubl_xml(
            self.command, self.connector_config, "INV-2026-1024", "2026-03-20"
        )
        self.assertIn("<?xml", xml_str)
        root = ET.fromstring(xml_str)
        self.assertIn("Invoice", root.tag)

        cbc = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
        cac = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"

        customization_id = root.find(f"{{{cbc}}}CustomizationID")
        self.assertIsNotNone(customization_id)
        self.assertIn("poacc:billing:3.0", customization_id.text)

        invoice_id = root.find(f"{{{cbc}}}ID")
        self.assertEqual(invoice_id.text, "INV-2026-1024")

        # Supplier & Customer
        supplier_elem = root.find(f".//{{{cac}}}AccountingSupplierParty")
        self.assertIsNotNone(supplier_elem)
        supplier_name = supplier_elem.find(f".//{{{cbc}}}RegistrationName")
        self.assertEqual(supplier_name.text, "Acme Europe B.V.")

        # Total amount
        total_elem = root.find(f".//{{{cac}}}LegalMonetaryTotal/{{{cbc}}}PayableAmount")
        self.assertEqual(total_elem.text, "12500.50")
        self.assertEqual(total_elem.get("currencyID"), "EUR")

    def test_peppol_local_dispatch(self):
        connector = PeppolRegistryConnector()
        res = connector.dispatch(self.command, self.connector_config, attempt_number=1)
        self.assertEqual(res["mode"], "success")
        resp = res["response"]
        self.assertEqual(schema_errors("protocol-registration-response.v1.schema.json", resp), [])
        remote = resp["remote_reference"]
        self.assertEqual(remote["reference_id"], "PEPPOL-INV-2026-1024")
        self.assertIn("urn:peppol:invoice:", remote["uri"])
        self.assertIn("raw_payload", resp)
        self.assertIn("CustomizationID", resp["raw_payload"])

    def test_peppol_remote_http_dispatch(self):
        cfg = {
            **self.connector_config,
            "base_url": "https://peppol.accesspoint.eu",
            "endpoint_path": "/api/v2/as4/send",
        }
        opener, seen = make_mock_opener(
            body={"reference_id": "AP-UUID-1234", "uri": "https://peppol.accesspoint.eu/doc/1234"}
        )
        connector = PeppolRegistryConnector(opener=opener)
        res = connector.dispatch(self.command, cfg, attempt_number=1)
        self.assertEqual(res["mode"], "success")
        self.assertEqual(seen["url"], "https://peppol.accesspoint.eu/api/v2/as4/send")
        self.assertEqual(seen["headers"]["X-peppol-sender"], "9915:NL123456789B01")
        self.assertIn(b"Invoice", seen["data"])


class WebhookConnectorTests(unittest.TestCase):
    def setUp(self):
        self.command = {
            "schema_version": "1.0.0",
            "command_id": "cmd-webhook-001",
            "command_type": "protocol.register",
            "document_id": "doc-00000000-0000-0000-0000-000000000003",
            "idempotency_key": "idem-wh-001",
            "caller": {
                "user_id": "system_worker",
                "institution_id": "org_global",
                "office_id": "it",
            },
            "payload": {
                "status": "ready",
            },
            "audit_context": {
                "correlation_id": "corr-wh-001",
            },
        }
        self.connector_config = {
            "connector_id": "wh_connector",
            "system_name": "webhook-dispatcher",
            "description": "Universal HMAC signed webhook",
            "channel_type": "webhook",
            "auth_profile": "hmac_signature",
            "status": "active",
            "base_url": "https://consumer.example.org",
            "endpoint_path": "/webhooks/events",
            "webhook_secret_env": "TEST_WEBHOOK_SECRET",
            "ownership": {
                "source_system_of_record": "xtract",
                "target_system_of_record": "consumer",
                "synchronization_owner": "integration-hub",
            },
            "authoritative_reference_types": ["registration_number"],
            "supported_commands": ["protocol.register"],
        }
        os.environ["TEST_WEBHOOK_SECRET"] = "super-secret-hmac-key"

    def tearDown(self):
        os.environ.pop("TEST_WEBHOOK_SECRET", None)

    def test_webhook_hmac_signing(self):
        opener, seen = make_mock_opener(body={"reference_id": "WH-ACK-100"})
        connector = WebhookProtocolConnector(opener=opener)
        res = connector.dispatch(self.command, self.connector_config, attempt_number=1)
        self.assertEqual(res["mode"], "success")
        self.assertEqual(seen["url"], "https://consumer.example.org/webhooks/events")

        # Verify HMAC signature
        signature_header = seen["headers"].get("X-signature-sha256")
        self.assertIsNotNone(signature_header)
        self.assertTrue(signature_header.startswith("sha256="))
        expected_sig = (
            "sha256=" + hmac.new(b"super-secret-hmac-key", seen["data"], hashlib.sha256).hexdigest()
        )
        self.assertEqual(signature_header, expected_sig)
        self.assertEqual(seen["headers"].get("X-event-type"), "protocol.register")
        self.assertEqual(
            seen["headers"].get("X-document-id"), "doc-00000000-0000-0000-0000-000000000003"
        )


class DispatcherCatalogTests(unittest.TestCase):
    def test_available_connectors(self):
        catalog = {
            "schema_version": "1.0.0",
            "connectors": [
                {
                    "connector_id": "local_registry",
                    "system_name": "xtract-registry",
                    "description": "Local Sovereign Registry",
                    "channel_type": "local_registry",
                    "status": "active",
                    "supported_commands": ["protocol.register"],
                    "reference_prefix": "REG",
                    "ownership": {"a": "b"},
                },
                {
                    "connector_id": "peppol_hub",
                    "system_name": "peppol-access-point",
                    "description": "Peppol BIS Billing 3.0",
                    "channel_type": "peppol_registry",
                    "status": "active",
                    "supported_commands": ["protocol.register"],
                    "reference_prefix": "PEPPOL",
                    "ownership": {"c": "d"},
                },
            ],
        }
        policy = {"schema_version": "1.0.0", "routes": []}
        dispatcher = ProtocolDispatcher(catalog, policy)
        conns = dispatcher.available_connectors()
        self.assertEqual(len(conns), 2)
        self.assertEqual(conns[0]["connector_id"], "local_registry")
        self.assertEqual(conns[1]["connector_id"], "peppol_hub")
        self.assertEqual(conns[1]["channel_type"], "peppol_registry")

    def test_custom_connector_registration(self):
        class CustomConnector(ProtocolConnector):
            def dispatch(self, command: dict, connector: dict, attempt_number: int) -> dict:
                return {"mode": "success", "http_status": 200, "error_code": None, "response": {}}

        register_connector_type("custom_type", CustomConnector)
        self.assertIn("custom_type", CONNECTOR_REGISTRY)
        self.assertEqual(CONNECTOR_REGISTRY["custom_type"], CustomConnector)


if __name__ == "__main__":
    unittest.main()
