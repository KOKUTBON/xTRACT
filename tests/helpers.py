from __future__ import annotations

import io
import json
import logging
import sys
import tempfile
from pathlib import Path
from wsgiref.util import setup_testing_defaults

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from xtract.config import PlatformConfig
from xtract.core import Platform

logging.disable(logging.CRITICAL)

SCHEMA_FILES = sorted((ROOT / "src" / "xtract" / "contracts" / "schemas").glob("*.schema.json"))
_SCHEMAS = {path.name: json.loads(path.read_text("utf-8")) for path in SCHEMA_FILES}
REGISTRY = Registry().with_resources(
    (schema["$id"], Resource.from_contents(schema)) for schema in _SCHEMAS.values()
)

LETTER = """ACME Services Ltd
From: Jane Doe
To: City Records Office
Date: 12/03/2026
Our reference: AB-2026/0042
Subject: Request for archive copies

Dear Sir or Madam,
please send the requested copies.
Kind regards
"""

INVOICE = """INVOICE
Supplier: Example Supplier One
Invoice number: INV-2026-0017
Invoice date: 3 March 2026
VAT number: IT00000000000
Subtotal 1.000,00
Total amount: 1.220,00 €
"""

INCOMPLETE_PERMIT = """Building permit request
Applicant: Example Applicant One
Case number:
Request date: 31/13/2026
"""


def schema_errors(schema_name: str, payload) -> list[str]:
    validator = Draft202012Validator(_SCHEMAS[schema_name], registry=REGISTRY)
    return [f"{list(e.absolute_path)}: {e.message}" for e in validator.iter_errors(payload)]


def make_platform(test_case, config: dict | None = None, **overrides) -> Platform:
    tmp = tempfile.TemporaryDirectory()
    test_case.addCleanup(tmp.cleanup)
    cfg = PlatformConfig(data_dir=Path(tmp.name), worker_enabled=False)
    for key, value in (config or {}).items():
        setattr(cfg, key, value)
    return Platform(cfg, sleep=lambda _seconds: None, **overrides)


def ingest_text(
    platform: Platform, text: str, filename: str = "doc.txt", family: str = "auto"
) -> str:
    doc, _ = platform.intake.ingest_document(
        institution_id="default",
        office_id="general",
        document_family=family,
        filename=filename,
        content=text.encode("utf-8"),
        mime_type="text/plain",
    )
    platform.process_pending()
    return doc["document_id"]


def call(app, method: str, path: str, body=None, headers: dict | None = None):
    """Invoke the WSGI app and return (status_code, headers, parsed_body)."""
    environ: dict = {}
    setup_testing_defaults(environ)
    path, _, query = path.partition("?")
    raw = b"" if body is None else json.dumps(body).encode("utf-8")
    environ.update(
        {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "CONTENT_LENGTH": str(len(raw)),
            "CONTENT_TYPE": "application/json",
            "wsgi.input": io.BytesIO(raw),
        }
    )
    for name, value in (headers or {}).items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(response_headers)

    data = b"".join(app(environ, start_response))
    content_type = captured["headers"].get("Content-Type", "")
    parsed = json.loads(data) if content_type.startswith("application/json") and data else data
    return captured["status"], captured["headers"], parsed
