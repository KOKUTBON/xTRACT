"""Exercise institution isolation through the public API using a shared database."""

import csv
import io
import json
import unittest

from helpers import INCOMPLETE_PERMIT, INVOICE, call, make_platform

from xtract.api.app import create_app


class InstitutionIsolationTests(unittest.TestCase):
    def setUp(self):
        self.platform = make_platform(
            self, config={"api_token": "bootstrap-key", "jwt_secret": "test-signing-key"}
        )
        self.app = create_app(self.platform)
        self.documents = {}
        for institution in ("institution-a", "institution-b"):
            doc, _ = self.platform.intake.ingest_document(
                institution_id=institution,
                office_id="records",
                document_family="auto",
                filename=f"{institution}.txt",
                content=INCOMPLETE_PERMIT.encode(),
                mime_type="text/plain",
            )
            self.documents[institution] = doc["document_id"]
        doc, _ = self.platform.intake.ingest_document(
            institution_id="institution-b",
            office_id="finance",
            document_family="auto",
            filename="private-invoice-b.txt",
            content=INVOICE.encode(),
            mime_type="text/plain",
        )
        self.invoice_b = doc["document_id"]
        self.platform.process_pending()
        self.exceptions = {
            institution: self.platform.db.record_exception(
                document, "operator_review_required", "medium"
            )
            for institution, document in self.documents.items()
        }
        self.auth = self.headers("institution-a", "admin")

    def headers(self, institution, role="operator"):
        token = self.platform.auth.create_token(
            "test-user", roles=[role], institution_id=institution, office_id="records"
        )
        return {"Authorization": f"Bearer {token}"}

    def test_foreign_document_reads_and_writes_are_hidden_without_side_effects(self):
        foreign = self.documents["institution-b"]
        before = self.platform.projections.get_document_workspace(foreign)
        routes = [
            ("GET", "", None),
            ("HEAD", "", None),
            ("GET", "/source", None),
            ("HEAD", "/source", None),
            ("GET", "/ocr", None),
            ("GET", "/export?include_text=true", None),
            ("POST", "/assistant", {"prompt": "Summarize"}),
            ("PUT", "/fields/case_number", {"value": "ATTACK"}),
            ("POST", "/fields/case_number/confirm", {}),
            ("POST", "/review/complete", {}),
            ("POST", "/review/reopen", {}),
            ("POST", "/discard", {"reason": "ATTACK"}),
            ("POST", "/reprocess", {"scope": "ocr"}),
            ("POST", "/integration/retry", {}),
        ]
        for method, suffix, body in routes:
            with self.subTest(method=method, suffix=suffix):
                status, _, _ = call(
                    self.app, method, f"/api/v1/documents/{foreign}{suffix}", body, self.auth
                )
                self.assertEqual(status, 404)
        self.assertEqual(self.platform.projections.get_document_workspace(foreign), before)
        status, _, _ = call(
            self.app,
            "POST",
            f"/api/v1/exceptions/{self.exceptions['institution-b']['exception_id']}/resolve",
            {},
            self.auth,
        )
        self.assertEqual(status, 404)
        self.assertEqual(
            self.platform.db.get_exception(self.exceptions["institution-b"]["exception_id"])[
                "exception_status"
            ],
            "open",
        )

    def test_institution_lists_counts_and_export_formats_are_scoped(self):
        own = self.documents["institution-a"]
        status, _, search = call(self.app, "GET", "/api/v1/documents", headers=self.auth)
        self.assertEqual(status, 200)
        self.assertEqual([hit["document_id"] for hit in search["hits"]], [own])
        for path in ("/api/v1/review-queue", "/api/v1/exceptions"):
            status, _, result = call(self.app, "GET", path, headers=self.auth)
            self.assertEqual(status, 200)
            self.assertTrue(result["items"])
            self.assertEqual(
                {item["institution_id"] for item in result["items"]}, {"institution-a"}
            )
        status, _, stats = call(self.app, "GET", "/api/v1/stats", headers=self.auth)
        self.assertEqual(status, 200)
        self.assertEqual(stats["documents_total"], 1)
        self.assertEqual(
            stats["open_exceptions"],
            len(self.platform.db.get_exceptions(status="open", institution_id="institution-a")),
        )
        self.assertEqual(
            stats["jobs_by_status"], self.platform.queue.count_by_status("institution-a")
        )
        status, _, records = call(
            self.app, "GET", "/api/v1/export/documents.json?stage=all", headers=self.auth
        )
        self.assertEqual(status, 200)
        self.assertEqual([r["source_document_id"] for r in records], [own])
        _, _, lines = call(
            self.app,
            "GET",
            "/api/v1/export/documents.jsonl?stage=all&include_text=true",
            headers=self.auth,
        )
        self.assertEqual(
            [json.loads(line)["document"]["source_document_id"] for line in lines.splitlines()],
            [own],
        )
        _, _, output = call(
            self.app, "GET", "/api/v1/export/fields.csv?stage=all", headers=self.auth
        )
        rows = list(csv.DictReader(io.StringIO(output.decode("utf-8"))))
        self.assertTrue(rows)
        self.assertEqual({row["document_id"] for row in rows}, {own})
        _, _, validated = call(self.app, "GET", "/api/v1/export/documents.json", headers=self.auth)
        self.assertEqual(validated, [])  # B's registered invoice must not leak.

    def test_explicit_foreign_filters_and_uploads_are_rejected(self):
        for path in (
            "documents",
            "review-queue",
            "exceptions",
            "stats",
            "export/documents.json",
            "export/documents.jsonl",
            "export/fields.csv",
        ):
            with self.subTest(path=path):
                status, _, _ = call(
                    self.app,
                    "GET",
                    f"/api/v1/{path}?institution_id=institution-b",
                    headers=self.auth,
                )
                self.assertEqual(status, 403)
        status, _, _ = call(
            self.app,
            "POST",
            "/api/v1/documents",
            {"institution_id": "institution-b", "filename": "attack.txt", "text_content": "ATTACK"},
            self.auth,
        )
        self.assertEqual(status, 403)
        self.assertEqual(len(self.platform.db.query_documents()), 3)

    def test_upload_defaults_config_and_same_institution_actions(self):
        _, _, config = call(self.app, "GET", "/api/v1/config", headers=self.auth)
        self.assertEqual(
            config["defaults"], {"institution_id": "institution-a", "office_id": "records"}
        )
        status, _, uploaded = call(
            self.app,
            "POST",
            "/api/v1/documents",
            {"filename": "own.txt", "text_content": "Own institution upload"},
            self.auth,
        )
        self.assertEqual(status, 201)
        self.assertEqual(
            self.platform.db.get_document(uploaded["document_id"])["institution_id"],
            "institution-a",
        )
        own = self.documents["institution-a"]
        for suffix in ("", "/source", "/ocr", "/export"):
            self.assertEqual(
                call(self.app, "GET", f"/api/v1/documents/{own}{suffix}", headers=self.auth)[0], 200
            )
        self.assertEqual(
            call(
                self.app,
                "PUT",
                f"/api/v1/documents/{own}/fields/case_number",
                {"value": "BP-2026-123"},
                self.auth,
            )[0],
            200,
        )
        self.assertEqual(
            call(
                self.app,
                "POST",
                f"/api/v1/exceptions/{self.exceptions['institution-a']['exception_id']}/resolve",
                {},
                self.auth,
            )[0],
            200,
        )

    def test_institution_admin_cannot_mint_foreign_tokens(self):
        status, _, _ = call(
            self.app,
            "POST",
            "/api/v1/auth/token",
            {"institution_id": "institution-b", "roles": ["admin"]},
            self.auth,
        )
        self.assertEqual(status, 403)
        status, _, result = call(
            self.app, "POST", "/api/v1/auth/token", {"roles": ["operator"]}, self.auth
        )
        self.assertEqual(status, 200)
        _, _, me = call(
            self.app,
            "GET",
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {result['access_token']}"},
        )
        self.assertEqual(me["institution_id"], "institution-a")
        # Only possession of the deployment bootstrap credential provisions other institutions.
        status, _, _ = call(
            self.app,
            "POST",
            "/api/v1/auth/token",
            {"api_token": "bootstrap-key", "institution_id": "institution-b"},
        )
        self.assertEqual(status, 200)

    def test_foreign_related_exception_cannot_be_attached_to_own_reprocessing(self):
        own = self.documents["institution-a"]
        before = self.platform.projections.get_document_workspace(own)
        status, _, _ = call(
            self.app,
            "POST",
            f"/api/v1/documents/{own}/reprocess",
            {
                "scope": "ocr",
                "related_exception_id": self.exceptions["institution-b"]["exception_id"],
            },
            self.auth,
        )
        self.assertEqual(status, 404)
        self.assertEqual(self.platform.projections.get_document_workspace(own), before)

    def test_proxy_identity_and_shared_token_do_not_bypass_document_scope(self):
        self.platform.config.trust_forwarded_headers = True
        foreign = self.documents["institution-b"]
        for headers in (
            {
                "X-Forwarded-User": "proxy-admin",
                "X-Forwarded-Roles": "admin",
                "X-Forwarded-Institution": "institution-a",
            },
            {"Authorization": "Bearer bootstrap-key"},
            self.headers("institution-a", "viewer"),
        ):
            with self.subTest(headers=headers):
                self.assertEqual(
                    call(self.app, "GET", f"/api/v1/documents/{foreign}", headers=headers)[0], 404
                )
