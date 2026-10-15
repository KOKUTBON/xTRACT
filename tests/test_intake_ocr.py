import io
import unittest

from helpers import LETTER, make_platform, schema_errors

from xtract.intake.service import IntakeError, guess_mime_type, sanitize_filename
from xtract.ocr.engines import OcrEngine, OcrResult, TesseractOcrEngine
from xtract.ocr.engines.base import line_blocks


class FakeEngine(OcrEngine):
    media_types = ("text/plain", "image/*")

    def __init__(self, name, confidence, available=True, crash=False):
        self.name = name
        self.confidence = confidence
        self.available = available
        self.crash = crash

    def availability(self):
        return (self.available, "available" if self.available else "not installed")

    def process(self, file_bytes, filename, mime_type, preprocess_steps=None):
        if self.crash:
            raise RuntimeError("engine crashed")
        text = f"text from {self.name}"
        return OcrResult(
            self.name,
            text,
            [{"page_number": 1, "text_blocks": line_blocks(text, self.confidence)}],
            self.confidence,
        )


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.platform = make_platform(self)

    def ingest(self, content: bytes, filename="a.txt", mime=None):
        return self.platform.intake.ingest_document(
            "inst", "office", "auto", filename, content, mime
        )

    def test_sanitizes_filenames(self):
        self.assertEqual(sanitize_filename("../../etc/pass wd?.txt"), "pass wd_.txt")
        self.assertEqual(sanitize_filename("C:\\scans\\page.png"), "page.png")
        self.assertEqual(sanitize_filename("..."), "document")

    def test_sniffs_media_types(self):
        self.assertEqual(guess_mime_type("x.bin", b"%PDF-1.7 ..."), "application/pdf")
        self.assertEqual(guess_mime_type("x.bin", b"\x89PNG\r\n\x1a\nxxxx"), "image/png")
        self.assertEqual(guess_mime_type("notes", b"plain words"), "text/plain")

    def test_registers_document_and_queues_ocr(self):
        doc, job = self.ingest(LETTER.encode())
        self.assertEqual(doc["current_workflow_stage"], "acquired")
        self.assertEqual(job.job_type, "ocr.process_document")
        self.assertEqual(len(doc["metadata_json"]["sha256"]), 64)
        events = self.platform.db.get_audit_events(doc["document_id"])
        self.assertEqual(events[0]["event_type"], "document.acquired")

    def test_rejects_invalid_uploads(self):
        cases = [
            (b"", "a.txt", None, "EMPTY_PAYLOAD"),
            (b"PK\x03\x04", "a.zip", "application/zip", "UNSUPPORTED_MEDIA_TYPE"),
            (b"not a pdf", "a.pdf", "application/pdf", "MEDIA_TYPE_MISMATCH"),
        ]
        for content, name, mime, code in cases:
            with self.subTest(code=code), self.assertRaises(IntakeError) as ctx:
                self.ingest(content, name, mime)
            self.assertEqual(ctx.exception.code, code)
        self.platform.intake.config.max_file_size_bytes = 3
        with self.assertRaises(IntakeError) as ctx:
            self.ingest(b"too long")
        self.assertEqual(ctx.exception.code, "PAYLOAD_TOO_LARGE")

    def test_rejects_duplicates_per_institution(self):
        first, _ = self.ingest(b"same content")
        with self.assertRaises(IntakeError) as ctx:
            self.ingest(b"same content")
        self.assertEqual(ctx.exception.code, "DUPLICATE_DOCUMENT")
        self.assertEqual(ctx.exception.details["document_id"], first["document_id"])
        other, _ = self.platform.intake.ingest_document(
            "other", "o", "auto", "a.txt", b"same content"
        )
        self.assertNotEqual(other["document_id"], first["document_id"])


class OcrTests(unittest.TestCase):
    def run_with(self, engines, policy_route=None):
        platform = make_platform(self, ocr_engines=engines)
        if policy_route:
            platform.ocr.policy = {**platform.ocr.policy, "default_route": policy_route}
        doc, _ = platform.intake.ingest_document("i", "o", "auto", "a.txt", b"hello", "text/plain")
        platform.process_pending()
        return platform, platform.db.get_document(doc["document_id"])

    def test_plain_text_engine_output_matches_schema(self):
        platform, doc = self.run_with(None)
        self.assertEqual(doc["metadata_json"]["ocr_selected_engine"], "text")
        key = f"{doc['institution_id']}/{doc['document_id']}/normalized_output.json"
        import json

        output = json.loads(platform.storage.get_object("ocr-artifacts", key))
        self.assertEqual(schema_errors("ocr-normalized-output.v1.schema.json", output), [])

    def test_falls_back_to_best_engine_and_skips_unavailable_ones(self):
        route = {
            "preprocess_profile_id": "standard",
            "preferred_engines": ["missing", "low", "better"],
            "min_confidence": 0.95,
            "min_text_accuracy": 0.9,
        }
        platform, doc = self.run_with(
            {
                "missing": FakeEngine("missing", 1.0, available=False),
                "low": FakeEngine("low", 0.5),
                "better": FakeEngine("better", 0.7),
            },
            route,
        )
        self.assertEqual(doc["metadata_json"]["ocr_selected_engine"], "better")
        self.assertEqual(
            platform.db.get_document_text(doc["document_id"])["full_text"], "text from better"
        )

    def test_all_engines_failing_marks_document_failed(self):
        route = {
            "preprocess_profile_id": "standard",
            "preferred_engines": ["broken"],
            "min_confidence": 0.5,
            "min_text_accuracy": 0.9,
        }
        platform, doc = self.run_with({"broken": FakeEngine("broken", 1.0, crash=True)}, route)
        self.assertEqual(doc["current_workflow_stage"], "failed")
        codes = [e["exception_code"] for e in platform.db.get_exceptions(doc["document_id"])]
        self.assertEqual(codes, ["ocr_engine_failure"])

    @unittest.skipUnless(TesseractOcrEngine().availability()[0], "Tesseract is not installed")
    def test_tesseract_reads_a_rendered_image(self):
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (900, 200), "white")
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 40)
        except OSError:
            font = ImageFont.load_default(size=40)
        ImageDraw.Draw(image).text((20, 60), "Invoice number: INV-42", fill="black", font=font)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        result = TesseractOcrEngine().process(
            buffer.getvalue(), "scan.png", "image/png", ["grayscale"]
        )
        self.assertIn("INV-42", result.full_text)
        self.assertGreater(result.average_confidence, 0.5)


class PdfCompletenessTests(unittest.TestCase):
    def test_mixed_pdf_text_layer_does_not_hide_scanned_pages(self):
        from unittest.mock import MagicMock, patch

        from xtract.ocr.engines.pdf_text_engine import PdfTextLayerEngine

        pdf = MagicMock()
        pdf.__len__.return_value = 2
        pages = []
        for text in ("Embedded text " * 40, ""):
            page = MagicMock()
            page.get_height.return_value = 800
            page.get_textpage.return_value.count_rects.return_value = 0
            page.get_textpage.return_value.get_text_range.return_value = text
            pages.append(page)
        pdf.__getitem__.side_effect = pages
        with patch("xtract.ocr.engines.pdf_text_engine._load_pdfium") as loader:
            loader.return_value.PdfDocument.return_value = pdf
            result = PdfTextLayerEngine().process(b"pdf", "mixed.pdf", "application/pdf")
        self.assertEqual(result.average_confidence, 0)
        pdf.close.assert_called_once()

    def test_scanned_pdf_page_limit_fails_instead_of_truncating(self):
        import sys
        from unittest.mock import MagicMock, patch

        from xtract.ocr.engines.tesseract_engine import TesseractOcrEngine

        pdf = MagicMock()
        pdf.__len__.return_value = 51
        module = MagicMock()
        module.PdfDocument.return_value = pdf
        with patch.dict(sys.modules, {"pypdfium2": module}):
            with self.assertRaisesRegex(ValueError, "split it"):
                list(TesseractOcrEngine()._images(b"pdf", "application/pdf", None))
        pdf.__getitem__.assert_not_called()
        pdf.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
