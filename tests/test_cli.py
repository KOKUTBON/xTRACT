from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from helpers import INVOICE, LETTER

from xtract.cli import main


class CliRunTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.invoice_path = Path(self.temp_dir.name) / "invoice.txt"
        self.invoice_path.write_text(INVOICE, encoding="utf-8")
        self.letter_path = Path(self.temp_dir.name) / "letter.txt"
        self.letter_path.write_text(LETTER, encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_json_format_single_file(self):
        output_file = Path(self.temp_dir.name) / "out.json"
        ret = main(["run", str(self.invoice_path), "--format", "json", "-o", str(output_file)])
        self.assertEqual(ret, 0)
        self.assertTrue(output_file.is_file())

        data = json.loads(output_file.read_text(encoding="utf-8"))
        self.assertEqual(data["document_family"], "invoice")
        self.assertIn("fields", data)
        self.assertEqual(data["fields"].get("invoice_number"), "INV-2026-0017")
        self.assertEqual(data["fields"].get("total_amount"), "1220.00")

    def test_run_csv_format_tabular_flattening(self):
        output_file = Path(self.temp_dir.name) / "out.csv"
        ret = main(["run", str(self.invoice_path), "--format", "csv", "-o", str(output_file)])
        self.assertEqual(ret, 0)
        self.assertTrue(output_file.is_file())

        content = output_file.read_text(encoding="utf-8")
        reader = list(csv.DictReader(io.StringIO(content)))
        self.assertEqual(len(reader), 1)
        row = reader[0]

        # Base columns
        self.assertEqual(row["source_filename"], "invoice.txt")
        self.assertEqual(row["document_family"], "invoice")

        # Flattened field columns
        self.assertEqual(row["invoice_number"], "INV-2026-0017")
        self.assertEqual(row["invoice_date"], "2026-03-03")
        self.assertEqual(row["supplier_name"], "Example Supplier One")
        self.assertEqual(row["vat_number"], "IT00000000000")
        self.assertEqual(row["total_amount"], "1220.00")

    def test_run_csv_format_multiple_documents(self):
        output_file = Path(self.temp_dir.name) / "out_multi.csv"
        ret = main(
            [
                "run",
                str(self.invoice_path),
                str(self.letter_path),
                "--format",
                "csv",
                "-o",
                str(output_file),
            ]
        )
        self.assertEqual(ret, 0)
        self.assertTrue(output_file.is_file())

        content = output_file.read_text(encoding="utf-8")
        reader = list(csv.DictReader(io.StringIO(content)))
        self.assertEqual(len(reader), 2)

        filenames = [r["source_filename"] for r in reader]
        self.assertIn("invoice.txt", filenames)
        self.assertIn("letter.txt", filenames)

    def test_run_missing_file_returns_error(self):
        missing_path = Path(self.temp_dir.name) / "nonexistent.txt"
        ret = main(["run", str(missing_path)])
        self.assertEqual(ret, 1)


if __name__ == "__main__":
    unittest.main()
