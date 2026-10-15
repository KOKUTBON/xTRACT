import base64
import io
import json
import unittest
import urllib.error

from helpers import INCOMPLETE_PERMIT, INVOICE, call, make_platform, schema_errors

from xtract.api.app import create_app
from xtract.integration.connector import HttpProtocolConnector


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.platform = make_platform(self)
        self.app = create_app(self.platform)

    def upload(self, text, filename="doc.txt", **extra):
        return call(
            self.app,
            "POST",
            "/api/v1/documents",
            {"filename": filename, "text_content": text, **extra},
            {"X-Operator-Id": "Test Operator"},
        )

    def test_health_config_and_stats(self):
        status, _, body = call(self.app, "GET", "/api/v1/health")
        self.assertEqual((status, body["status"]), (200, "healthy"))
        status, _, branding = call(self.app, "GET", "/api/v1/branding")
        self.assertEqual(status, 200)
        self.assertEqual(schema_errors("institution-profile.v1.schema.json", branding), [])
        self.assertEqual(branding["institution_id"], "default")
        status, _, packs = call(self.app, "GET", "/api/v1/packs")
        self.assertEqual(status, 200)
        pack_ids = [p["pack_id"] for p in packs["packs"]]
        self.assertIn("general", pack_ids)
        self.assertIn("it-pa", pack_ids)
        self.assertEqual(packs["active_pack"], "general")
        status, _, config = call(self.app, "GET", "/api/v1/config")
        self.assertEqual(status, 200)
        self.assertIn("invoice", [f["family_code"] for f in config["document_families"]])
        self.assertEqual(config["institution"]["institution_id"], "default")
        self.assertEqual(config["config_pack"], "general")
        self.assertEqual(call(self.app, "GET", "/api/v1/stats")[2]["documents_total"], 0)
        status, _, conn_resp = call(self.app, "GET", "/api/v1/connectors")
        self.assertEqual(status, 200)
        conn_ids = [c["connector_id"] for c in conn_resp["connectors"]]
        self.assertIn("local_registry", conn_ids)
        self.assertIn("peppol_hub", conn_ids)
        self.assertIn("webhook_notifier", conn_ids)

    def test_upload_process_review_and_export(self):
        status, headers, created = self.upload(INCOMPLETE_PERMIT, "permit.txt")
        self.assertEqual(status, 201)
        document_id = created["document_id"]
        self.assertEqual(headers["Location"], f"/api/v1/documents/{document_id}")
        self.platform.process_pending()

        status, _, workspace = call(self.app, "GET", f"/api/v1/documents/{document_id}")
        self.assertEqual(status, 200)
        self.assertEqual(schema_errors("document-workspace.v1.schema.json", workspace), [])
        self.assertIn("complete_review", workspace["permitted_actions"])

        status, _, error = call(
            self.app,
            "PUT",
            f"/api/v1/documents/{document_id}/fields/request_date",
            {"value": "someday"},
        )
        self.assertEqual((status, error["error"]), (422, "VALIDATION_FAILED"))
        status, _, workspace = call(
            self.app,
            "PUT",
            f"/api/v1/documents/{document_id}/fields/request_date",
            {"value": "someday", "force": True},
        )
        self.assertEqual(status, 200)
        call(
            self.app,
            "PUT",
            f"/api/v1/documents/{document_id}/fields/case_number",
            {"value": "BP-1"},
        )
        call(
            self.app,
            "PUT",
            f"/api/v1/documents/{document_id}/fields/request_date",
            {"value": "2026-01-02"},
        )
        status, _, workspace = call(
            self.app, "POST", f"/api/v1/documents/{document_id}/review/complete", {}
        )
        self.assertEqual((status, workspace["workflow_state"]["stage"]), (200, "validated"))
        self.platform.process_pending()

        status, _, record = call(self.app, "GET", f"/api/v1/documents/{document_id}/export")
        self.assertEqual(status, 200)
        self.assertEqual(
            schema_errors("validated-document-export.v1.schema.json", record["document"]), []
        )
        corrected = {p["field_code"]: p["corrected"] for p in record["field_provenance"]}
        self.assertTrue(corrected["case_number"])

        status, headers, body = call(self.app, "GET", "/api/v1/export/fields.csv")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn(b"BP-1", body)
        status, _, body = call(self.app, "GET", "/api/v1/export/documents.jsonl?stage=all")
        self.assertEqual(len(body.decode().strip().splitlines()), 1)

        events = self.platform.db.get_audit_events(document_id)
        self.assertEqual(events[0]["actor_id"], "Test Operator")

    def test_upload_errors_map_to_http_statuses(self):
        self.assertEqual(self.upload("same")[0], 201)
        self.assertEqual(self.upload("same")[0], 409)
        status, _, body = call(
            self.app,
            "POST",
            "/api/v1/documents",
            {
                "filename": "x.zip",
                "content_base64": base64.b64encode(b"PK\x03\x04").decode(),
                "mime_type": "application/zip",
            },
        )
        self.assertEqual((status, body["error"]), (415, "UNSUPPORTED_MEDIA_TYPE"))
        self.assertEqual(call(self.app, "POST", "/api/v1/documents", {"filename": "x"})[0], 400)
        self.assertEqual(
            call(self.app, "POST", "/api/v1/documents", {"content_base64": "***"})[0], 400
        )

    def test_malformed_request_types_are_rejected_without_writes(self):
        for data in (
            {"content_base64": ["bad"]},
            {"text_content": "hello", "mime_type": {}},
            {"text_content": "hello", "document_family": "unknown"},
            {"text_content": "hello", "force": "false"},
        ):
            with self.subTest(data=data):
                self.assertEqual(call(self.app, "POST", "/api/v1/documents", data)[0], 422)
        self.assertEqual(self.platform.projections.get_stats()["documents_total"], 0)

    def test_negative_content_length_is_rejected_without_reading(self):
        from unittest.mock import Mock

        from xtract.api.app import HttpError, Request

        stream = Mock()
        request = Request({"CONTENT_LENGTH": "-1", "wsgi.input": stream}, 100)
        with self.assertRaises(HttpError) as raised:
            request.json()
        self.assertEqual(raised.exception.status, 400)
        stream.read.assert_not_called()

    def test_unicode_filename_is_safe_in_http_headers(self):
        _, _, created = self.upload("unicode upload", "文書.txt")
        status, headers, _ = call(
            self.app, "GET", f"/api/v1/documents/{created['document_id']}/source"
        )
        self.assertEqual(status, 200)
        self.assertIn("filename*=UTF-8''", headers["Content-Disposition"])
        headers["Content-Disposition"].encode("latin-1")

    def test_unreviewed_export_does_not_claim_validation(self):
        _, _, created = self.upload(INCOMPLETE_PERMIT)
        self.platform.process_pending()
        record = self.platform.exporter.document_export(created["document_id"])
        self.assertEqual(record["export_stage"], "draft")
        self.assertFalse(record["document_type"]["is_final"])
        self.assertEqual(schema_errors("validated-document-export.v1.schema.json", record), [])

    def test_processing_document_cannot_be_discarded(self):
        _, _, created = self.upload("queued document")
        document_id = created["document_id"]
        status, _, body = call(
            self.app, "POST", f"/api/v1/documents/{document_id}/discard", {"reason": "remove"}
        )
        self.assertEqual((status, body["error"]), (409, "BUSY"))
        _, _, workspace = call(self.app, "GET", f"/api/v1/documents/{document_id}")
        self.assertNotIn("discard_document", workspace["permitted_actions"])
        self.platform.process_pending()
        self.assertEqual(
            call(
                self.app, "POST", f"/api/v1/documents/{document_id}/discard", {"reason": "remove"}
            )[0],
            200,
        )

    def test_routing_errors(self):
        self.assertEqual(call(self.app, "GET", "/api/v1/nope")[0], 404)
        self.assertEqual(call(self.app, "DELETE", "/api/v1/documents")[0], 405)
        missing = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(call(self.app, "GET", f"/api/v1/documents/{missing}")[0], 404)
        self.assertEqual(
            call(self.app, "POST", f"/api/v1/documents/{missing}/discard", {"reason": "x"})[0], 404
        )

    def test_review_queue_exceptions_assistant_and_reprocess(self):
        _, _, created = self.upload(INCOMPLETE_PERMIT)
        document_id = created["document_id"]
        self.platform.process_pending()
        _, _, queue = call(self.app, "GET", "/api/v1/review-queue")
        self.assertEqual(queue["items"][0]["document_id"], document_id)
        self.assertEqual(call(self.app, "GET", "/api/v1/exceptions?status=bogus")[0], 422)

        status, _, card = call(
            self.app,
            "POST",
            f"/api/v1/documents/{document_id}/assistant",
            {"prompt": "Why does this need attention?"},
        )
        self.assertEqual((status, card["response_mode"]), (200, "answer"))

        status, _, request = call(
            self.app, "POST", f"/api/v1/documents/{document_id}/reprocess", {"scope": "ocr"}
        )
        self.assertEqual((status, request["status"]), (202, "accepted"))
        self.assertEqual(
            call(
                self.app,
                "POST",
                f"/api/v1/documents/{document_id}/reprocess",
                {"scope": "extraction"},
            )[0],
            409,
        )  # still processing
        self.platform.process_pending()
        self.assertEqual(
            call(
                self.app,
                "POST",
                f"/api/v1/documents/{document_id}/reprocess",
                {"scope": "everything"},
            )[0],
            422,
        )

    def test_source_download_and_static_portal(self):
        _, _, created = self.upload(INVOICE, "invoice.txt")
        status, headers, body = call(
            self.app, "GET", f"/api/v1/documents/{created['document_id']}/source"
        )
        self.assertEqual((status, headers["Content-Type"]), (200, "text/plain"))
        self.assertIn(b"Example Supplier", body)
        self.assertIn("sandbox", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(headers["Cache-Control"], "no-store")

        status, headers, body = call(self.app, "GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"xTRACT", body)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(call(self.app, "GET", "/app.js")[0], 200)
        self.assertEqual(call(self.app, "GET", "/modules/i18n.js")[0], 200)
        self.assertEqual(call(self.app, "GET", "/branding/logo-mark.svg")[0], 200)
        self.assertEqual(call(self.app, "GET", "/../../pyproject.toml")[0], 404)
        self.assertEqual(call(self.app, "GET", "/README.md")[0], 404)

    def test_api_token_protects_api_but_not_health(self):
        platform = make_platform(self, config={"api_token": "s3cret"})
        app = create_app(platform)
        self.assertEqual(call(app, "GET", "/api/v1/health")[0], 200)
        self.assertEqual(call(app, "GET", "/api/v1/branding")[0], 200)
        self.assertEqual(call(app, "GET", "/api/v1/stats")[0], 401)
        self.assertEqual(
            call(app, "GET", "/api/v1/stats", headers={"Authorization": "Bearer nope"})[0], 401
        )
        self.assertEqual(
            call(app, "GET", "/api/v1/stats", headers={"Authorization": "Bearer s3cret"})[0], 200
        )
        # Credentials in query parameters are strictly rejected for security
        self.assertEqual(call(app, "GET", "/api/v1/stats?access_token=s3cret")[0], 401)
        self.assertEqual(call(app, "GET", "/")[0], 200)

    def test_auth_discovery_and_profile_endpoints(self):
        status, _, auth_cfg = call(self.app, "GET", "/api/v1/auth/config")
        self.assertEqual(status, 200)
        self.assertIn("admin", auth_cfg["available_roles"])
        self.assertIn("viewer", auth_cfg["available_roles"])
        self.assertIn("field:edit", auth_cfg["available_permissions"])

        status, _, me = call(self.app, "GET", "/api/v1/auth/me")
        self.assertEqual(status, 200)
        self.assertEqual(me["user_id"], "operator")
        self.assertIn("admin", me["roles"])

    def test_auth_token_issuance_and_rbac_enforcement(self):
        self.platform = make_platform(self, config={"api_token": "bootstrap-secret"})
        self.app = create_app(self.platform)
        admin_auth = {"Authorization": "Bearer bootstrap-secret"}
        # 1. Issue viewer token
        status, _, token_res = call(
            self.app,
            "POST",
            "/api/v1/auth/token",
            {"user_id": "auditor1", "display_name": "Audit Officer", "roles": ["viewer"]},
            headers=admin_auth,
        )
        self.assertEqual(status, 200)
        viewer_token = token_res["access_token"]
        viewer_auth = {"Authorization": f"Bearer {viewer_token}"}

        # 2. Issue operator token
        _, _, op_res = call(
            self.app,
            "POST",
            "/api/v1/auth/token",
            {"user_id": "operator1", "display_name": "Front Desk Operator", "roles": ["operator"]},
            headers=admin_auth,
        )
        op_auth = {"Authorization": f"Bearer {op_res['access_token']}"}

        # 3. Issue supervisor token
        _, _, sup_res = call(
            self.app,
            "POST",
            "/api/v1/auth/token",
            {"user_id": "supervisor1", "display_name": "Office Lead", "roles": ["supervisor"]},
            headers=admin_auth,
        )
        sup_auth = {"Authorization": f"Bearer {sup_res['access_token']}"}

        # Check me endpoint as viewer
        status, _, me_viewer = call(self.app, "GET", "/api/v1/auth/me", headers=viewer_auth)
        self.assertEqual(status, 200)
        self.assertEqual(me_viewer["user_id"], "auditor1")
        self.assertEqual(me_viewer["roles"], ["viewer"])

        # Viewer cannot upload document (requires field:edit)
        status, _, err = call(
            self.app,
            "POST",
            "/api/v1/documents",
            {"filename": "test.txt", "text_content": "sample content"},
            headers=viewer_auth,
        )
        self.assertEqual(status, 403)
        self.assertEqual(err["error"], "FORBIDDEN")

        # Operator can upload document
        status, _, created = call(
            self.app,
            "POST",
            "/api/v1/documents",
            {"filename": "test.txt", "text_content": INCOMPLETE_PERMIT},
            headers=op_auth,
        )
        self.assertEqual(status, 201)
        doc_id = created["document_id"]
        self.platform.process_pending()

        # Viewer can read workspace
        status, _, ws = call(self.app, "GET", f"/api/v1/documents/{doc_id}", headers=viewer_auth)
        self.assertEqual(status, 200)

        # Viewer cannot edit field
        status, _, _ = call(
            self.app,
            "PUT",
            f"/api/v1/documents/{doc_id}/fields/case_number",
            {"value": "BP-2026-99"},
            headers=viewer_auth,
        )
        self.assertEqual(status, 403)

        # Operator can edit field
        status, _, _ = call(
            self.app,
            "PUT",
            f"/api/v1/documents/{doc_id}/fields/case_number",
            {"value": "BP-2026-99"},
            headers=op_auth,
        )
        self.assertEqual(status, 200)

        # Operator cannot discard document (requires supervisor or admin)
        status, _, _ = call(
            self.app,
            "POST",
            f"/api/v1/documents/{doc_id}/discard",
            {"reason": "Not needed"},
            headers=op_auth,
        )
        self.assertEqual(status, 403)

        # Supervisor can discard document
        status, _, _ = call(
            self.app,
            "POST",
            f"/api/v1/documents/{doc_id}/discard",
            {"reason": "Approved discard"},
            headers=sup_auth,
        )
        self.assertEqual(status, 200)

    def test_jwt_mode_blocks_anonymous_access_and_token_issuance(self):
        platform = make_platform(
            self, config={"api_token": "", "auth_mode": "jwt", "jwt_secret": "jwt-test-key"}
        )
        app = create_app(platform)
        self.assertEqual(call(app, "GET", "/api/v1/auth/me")[0], 401)
        self.assertEqual(call(app, "GET", "/api/v1/documents")[0], 401)
        self.assertEqual(call(app, "POST", "/api/v1/auth/token", {"roles": ["admin"]})[0], 401)
        self.assertEqual(call(app, "GET", "/api/v1/auth/config")[2]["auth_required"], True)
        for role in ("viewer", "operator", "supervisor"):
            with self.subTest(role=role):
                token = platform.auth.create_token("user", roles=[role])
                self.assertEqual(
                    call(
                        app,
                        "POST",
                        "/api/v1/auth/token",
                        {"roles": ["admin"]},
                        {"Authorization": f"Bearer {token}"},
                    )[0],
                    403,
                )
        admin = platform.auth.create_token("admin", roles=["admin"])
        headers = {"Authorization": f"Bearer {admin}"}
        status, _, result = call(
            app, "POST", "/api/v1/auth/token", {"user_id": "viewer", "roles": ["viewer"]}, headers
        )
        self.assertEqual(status, 200)
        status, _, me = call(
            app,
            "GET",
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {result['access_token']}"},
        )
        self.assertEqual((status, me["roles"]), (200, ["viewer"]))
        self.assertTrue(call(app, "GET", "/api/v1/config", headers=headers)[2]["auth_required"])

    def test_token_issuance_requires_verified_admin_even_in_development(self):
        self.assertEqual(call(self.app, "POST", "/api/v1/auth/token", {"roles": ["admin"]})[0], 401)
        self.assertEqual(
            call(
                self.app,
                "POST",
                "/api/v1/auth/token",
                {"roles": ["admin"]},
                {"Authorization": "Bearer arbitrary"},
            )[0],
            401,
        )

    def test_shared_token_bootstraps_token_issuance(self):
        app = create_app(make_platform(self, config={"api_token": "bootstrap-secret"}))
        self.assertEqual(call(app, "POST", "/api/v1/auth/token", {"api_token": "wrong"})[0], 401)
        status, _, result = call(
            app,
            "POST",
            "/api/v1/auth/token",
            {"api_token": "bootstrap-secret", "roles": ["operator"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            call(
                app,
                "GET",
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {result['access_token']}"},
            )[2]["roles"],
            ["operator"],
        )

    def test_token_issuance_rejects_invalid_roles_and_lifetimes(self):
        app = create_app(make_platform(self, config={"api_token": "bootstrap-secret"}))
        headers = {"Authorization": "Bearer bootstrap-secret"}
        for payload in (
            {"roles": "admin"},
            {"roles": []},
            {"roles": [42]},
            {"roles": ["unknown"]},
            {"expires_in": 0},
            {"expires_in": -1},
            {"expires_in": 86401},
            {"expires_in": True},
            {"expires_in": "3600"},
            {"expires_in": None},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(call(app, "POST", "/api/v1/auth/token", payload, headers)[0], 422)

    def test_header_mode_requires_identity_and_signing_key_for_issuance(self):
        app = create_app(
            make_platform(self, config={"api_token": "", "jwt_secret": "", "auth_mode": "header"})
        )
        self.assertEqual(call(app, "GET", "/api/v1/auth/me")[0], 401)
        self.assertEqual(
            call(app, "GET", "/api/v1/auth/me", headers={"X-Forwarded-User": "   "})[0], 401
        )
        self.assertEqual(
            call(
                app,
                "POST",
                "/api/v1/auth/token",
                {},
                {"X-Forwarded-User": "admin", "X-Forwarded-Roles": "admin"},
            )[0],
            503,
        )

    def test_reverse_proxy_header_federation_in_api(self):
        platform = make_platform(
            self, config={"api_token": "s3cret", "trust_forwarded_headers": True}
        )
        app = create_app(platform)
        headers = {
            "X-Forwarded-User": "federated-mario",
            "X-Forwarded-Roles": "supervisor",
            "X-Forwarded-Institution": "prefettura-rm",
        }
        status, _, me = call(app, "GET", "/api/v1/auth/me", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(me["user_id"], "federated-mario")
        self.assertEqual(me["roles"], ["supervisor"])
        self.assertEqual(me["institution_id"], "prefettura-rm")
        self.assertEqual(me["auth_method"], "header")

    def test_custom_institution_branding_overrides(self):
        import os

        old_env = os.environ.copy()
        try:
            os.environ["XTRACT_INSTITUTION_NAME"] = "Politecnico di Milano"
            os.environ["XTRACT_APP_TITLE"] = "PoliMi Intake Portal"
            os.environ["XTRACT_BRAND_ACCENT_COLOR"] = "#003b71"
            platform = make_platform(self)
            app = create_app(platform)
            status, _, branding = call(app, "GET", "/api/v1/branding")
            self.assertEqual(status, 200)
            self.assertEqual(branding["institution_name"], "Politecnico di Milano")
            self.assertEqual(branding["app_title"], "PoliMi Intake Portal")
            self.assertEqual(branding["accent_color"], "#003b71")
        finally:
            os.environ.clear()
            os.environ.update(old_env)


class HttpConnectorTests(unittest.TestCase):
    command = {
        "command_id": "11111111-1111-1111-1111-111111111111",
        "document_id": "22222222-2222-2222-2222-222222222222",
        "idempotency_key": "k",
        "caller": {"institution_id": "i"},
        "audit_context": {"correlation_id": "33333333-3333-3333-3333-333333333333"},
        "payload": {"requested_reference_type": "protocol_id"},
    }
    connector = {
        "connector_id": "remote",
        "base_url": "https://registry.example.org/api",
        "auth_profile": "none",
    }

    def opener_returning(self, status=200, body=None, error=None):
        seen = {}

        class FakeResponse:
            def __init__(self):
                self.status = status

            def read(self):
                return json.dumps(body or {}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = dict(request.header_items())
            if error:
                raise error
            return FakeResponse()

        return opener, seen

    def test_success_maps_reference(self):
        opener, seen = self.opener_returning(body={"reference_id": "P-9", "uri": "https://r/P-9"})
        result = HttpProtocolConnector(opener=opener).dispatch(self.command, self.connector, 1)
        self.assertEqual(result["mode"], "success")
        self.assertEqual(result["response"]["remote_reference"]["reference_id"], "P-9")
        self.assertEqual(seen["url"], "https://registry.example.org/api/protocol-registrations")
        self.assertEqual(
            schema_errors("protocol-registration-response.v1.schema.json", result["response"]), []
        )

    def test_errors_are_classified(self):
        for code, mode in [(503, "retryable_failure"), (400, "permanent_failure")]:
            error = urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))
            opener, _ = self.opener_returning(error=error)
            self.assertEqual(
                HttpProtocolConnector(opener=opener).dispatch(self.command, self.connector, 1)[
                    "mode"
                ],
                mode,
            )
        opener, _ = self.opener_returning(error=urllib.error.URLError("down"))
        self.assertEqual(
            HttpProtocolConnector(opener=opener).dispatch(self.command, self.connector, 1)["mode"],
            "retryable_failure",
        )
        opener, _ = self.opener_returning(body={})
        self.assertEqual(
            HttpProtocolConnector(opener=opener).dispatch(self.command, self.connector, 1)[
                "error_code"
            ],
            "missing_reference",
        )

    def test_bearer_token_is_required_when_configured(self):
        connector = {
            **self.connector,
            "auth_profile": "bearer_token",
            "auth_token_env": "XTRACT_TEST_TOKEN_UNSET",
        }
        opener, _ = self.opener_returning()
        result = HttpProtocolConnector(opener=opener).dispatch(self.command, connector, 1)
        self.assertEqual(result["error_code"], "missing_credentials")


if __name__ == "__main__":
    unittest.main()
