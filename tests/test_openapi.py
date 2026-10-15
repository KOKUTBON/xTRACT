"""Tests validating that docs/openapi.yaml accurately matches xTRACT API endpoints."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class OpenApiSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec_path = ROOT / "docs" / "openapi.yaml"
        cls.assertTrue(cls.spec_path.is_file(), f"Missing spec: {cls.spec_path}")
        cls.content = cls.spec_path.read_text(encoding="utf-8")

    def test_spec_metadata(self):
        self.assertRegex(self.content, r"^openapi:\s*3\.1\.0", "OpenAPI version must be 3.1.0")
        self.assertIn("title: xTRACT Document Processing API", self.content)
        self.assertRegex(self.content, r"version:\s*0\.1\.0")

    def test_security_hardening_in_spec(self):
        # Must require BearerAuth and reject query param access_token
        self.assertIn("BearerAuth:", self.content)
        self.assertIn("scheme: bearer", self.content)
        # No query string token parameter anywhere in the specification
        self.assertNotIn("name: access_token", self.content)

    def test_all_api_endpoints_documented(self):
        expected_paths = [
            "/api/v1/health",
            "/api/v1/branding",
            "/api/v1/packs",
            "/api/v1/auth/config",
            "/api/v1/auth/me",
            "/api/v1/auth/token",
            "/api/v1/config",
            "/api/v1/stats",
            "/api/v1/connectors",
            "/api/v1/documents",
            "/api/v1/documents/{document_id}",
            "/api/v1/documents/{document_id}/source",
            "/api/v1/documents/{document_id}/ocr",
            "/api/v1/documents/{document_id}/export",
            "/api/v1/documents/{document_id}/fields/{field_code}",
            "/api/v1/documents/{document_id}/fields/{field_code}/confirm",
            "/api/v1/documents/{document_id}/review/complete",
            "/api/v1/documents/{document_id}/review/reopen",
            "/api/v1/documents/{document_id}/discard",
            "/api/v1/documents/{document_id}/reprocess",
            "/api/v1/documents/{document_id}/integration/retry",
            "/api/v1/documents/{document_id}/assistant",
            "/api/v1/review-queue",
            "/api/v1/exceptions",
            "/api/v1/exceptions/{exception_id}/resolve",
            "/api/v1/export/documents.jsonl",
            "/api/v1/export/documents.json",
            "/api/v1/export/fields.csv",
        ]
        # Find all path entries at two spaces indentation under paths:
        found_paths = set(re.findall(r"^  (/api/v1/[^\s:]+):", self.content, re.MULTILINE))
        for path in expected_paths:
            self.assertIn(path, found_paths, f"Path {path} missing in docs/openapi.yaml")


if __name__ == "__main__":
    unittest.main()
