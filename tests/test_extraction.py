import unittest

from helpers import INCOMPLETE_PERMIT, INVOICE, LETTER, make_platform

from xtract.extraction.normalizers import (
    apply_normalization,
    normalize_alphanumeric,
    normalize_fiscal_code,
    normalize_iban,
    normalize_vat_number,
    parse_date,
    parse_decimal,
    text_lines,
)


def ocr_output(text: str) -> dict:
    blocks = [
        {
            "block_id": f"block_{i}",
            "text": line,
            "confidence": 1.0,
            "bounding_box": {"left": 0, "top": i * 16, "width": 100, "height": 16},
        }
        for i, line in enumerate(text.splitlines())
        if line.strip()
    ]
    return {"full_text": text, "pages": [{"page_number": 1, "text_blocks": blocks}]}


class NormalizationTests(unittest.TestCase):
    def test_dates(self):
        cases = {
            "2026-03-12": "2026-03-12",
            "12/03/2026": "2026-03-12",
            "12.03.26": "2026-03-12",
            "3 March 2026": "2026-03-03",
            "March 3, 2026": "2026-03-03",
            "5 giugno 2026": "2026-06-05",
            "12 marzo 2026": "2026-03-12",
            "in data 15/09/2026": "2026-09-15",
            "12. März 2026": "2026-03-12",
            "1er mars 2026": "2026-03-01",
            "12 de octubre de 2026": "2026-10-12",
            "31/13/2026": None,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_date(raw), expected)
        self.assertEqual(parse_date("03/12/2026", "MDY"), "2026-03-12")
        self.assertEqual(parse_date("2026/03/12", "YMD"), "2026-03-12")

    def test_decimals(self):
        cases = {
            "1.220,00 €": "1220.00",
            "$1,234.56": "1234.56",
            "CHF 1'234.56": "1234.56",
            "1 234,56 €": "1234.56",
            "£1,234.56": "1234.56",
            "845,5": "845.5",
            "1,000": "1000",
            "-12.30": "-12.30",
            "(12.30)": "-12.30",
            "12.30-": "-12.30",
            "n/a": None,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_decimal(raw), expected)

    def test_national_identifiers(self):
        self.assertEqual(
            normalize_fiscal_code(" rss mra 80a01 h501u "),
            "RSSMRA80A01H501U",
        )
        self.assertEqual(normalize_fiscal_code(" 12345678901 "), "12345678901")
        self.assertIsNone(normalize_fiscal_code("ab"))
        self.assertEqual(
            normalize_iban(" IT 60 X 05428 11101 000000123456 "),
            "IT60X0542811101000000123456",
        )
        self.assertEqual(normalize_vat_number(" it 00000000000 "), "IT00000000000")
        self.assertEqual(normalize_alphanumeric(" cig#9876-abc/12 "), "CIG9876-ABC/12")

    def test_rule_chain(self):
        self.assertEqual(
            apply_normalization("  mario   rossi ", ["strip", "collapse_whitespace", "title_case"]),
            "Mario Rossi",
        )
        self.assertEqual(apply_normalization("ab-12", ["uppercase"]), "AB-12")
        self.assertEqual(
            apply_normalization(" it 60 x 05428 11101 000000123456 ", ["iban"]),
            "IT60X0542811101000000123456",
        )
        self.assertIsNone(apply_normalization(None, ["strip"]))

    def test_text_lines_merges_blocks_on_the_same_baseline(self):
        pages = [
            {
                "page_number": 1,
                "text_blocks": [
                    {
                        "block_id": "b2",
                        "text": "INV-9",
                        "confidence": 0.9,
                        "bounding_box": {"left": 200, "top": 10, "width": 50, "height": 12},
                    },
                    {
                        "block_id": "b1",
                        "text": "Invoice number:",
                        "confidence": 0.8,
                        "bounding_box": {"left": 10, "top": 11, "width": 120, "height": 12},
                    },
                    {
                        "block_id": "b3",
                        "text": "Next line",
                        "confidence": 1.0,
                        "bounding_box": {"left": 10, "top": 40, "width": 80, "height": 12},
                    },
                ],
            }
        ]
        lines = text_lines(pages)
        self.assertEqual([line["text"] for line in lines], ["Invoice number: INV-9", "Next line"])
        self.assertAlmostEqual(lines[0]["confidence"], 0.85)


class ExtractorTests(unittest.TestCase):
    def setUp(self):
        self.extractor = make_platform(self).extractor

    def test_detects_family_from_keywords(self):
        self.assertEqual(self.extractor.detect_family(INVOICE)[0], "invoice")
        self.assertEqual(
            self.extractor.detect_family("nothing useful")[0], "general_correspondence"
        )

    def test_extracts_and_normalizes_invoice_fields(self):
        run = self.extractor.extract("d1", "auto", ocr_output(INVOICE))
        values = {f["field_code"]: f["normalized_value"] for f in run["field_results"]}
        self.assertEqual(run["document_family"], "invoice")
        self.assertEqual(values["invoice_number"], "INV-2026-0017")
        self.assertEqual(values["invoice_date"], "2026-03-03")
        self.assertEqual(values["total_amount"], "1220.00")
        self.assertEqual(values["vat_number"], "IT00000000000")
        self.assertFalse(run["needs_human_review"])

    def test_letter_labels_do_not_capture_prose(self):
        run = self.extractor.extract(
            "d2", "auto", ocr_output(LETTER + "\nPlease refer to the file.\n")
        )
        values = {f["field_code"]: f["normalized_value"] for f in run["field_results"]}
        self.assertEqual(values["recipient_name"], "City Records Office")
        self.assertEqual(values["sender_name"], "Jane Doe")
        self.assertEqual(values["reference_number"], "AB-2026/0042")

    def test_value_on_the_line_after_the_label(self):
        run = self.extractor.extract(
            "d3", "invoice", ocr_output("Invoice number:\nX-778\nTotal: 10,00")
        )
        values = {f["field_code"]: f["normalized_value"] for f in run["field_results"]}
        self.assertEqual(values["invoice_number"], "X-778")

    def test_missing_and_invalid_values_require_review(self):
        run = self.extractor.extract("d4", "auto", ocr_output(INCOMPLETE_PERMIT))
        fields = {f["field_code"]: f for f in run["field_results"]}
        self.assertEqual(run["document_family"], "building_permit")
        self.assertIn("required_field_missing", fields["case_number"]["review_reason_codes"])
        self.assertIn("validation_pattern_mismatch", fields["request_date"]["review_reason_codes"])
        self.assertTrue(run["needs_human_review"])

    def test_validate_value_normalizes_operator_input(self):
        definition = self.extractor.field_definition("invoice", "invoice_date")
        self.assertEqual(
            self.extractor.validate_value(definition, "31 December 2026"), ("2026-12-31", [])
        )
        self.assertEqual(
            self.extractor.validate_value(definition, "tomorrow")[1],
            ["validation_pattern_mismatch"],
        )
        self.assertEqual(
            self.extractor.validate_value(definition, None)[1], ["required_field_missing"]
        )

    def test_it_pa_preset_pack_extraction(self):
        it_platform = make_platform(self, config={"config_pack": "it-pa"})
        extractor = it_platform.extractor

        # 1. Italian Administrative General Correspondence / Protocollo
        doc_text = (
            "COMUNE DI ESEMPIO\n"
            "Protocollo: PROT-2026-9874\n"
            "In data 15/04/2026\n"
            "Mittente: Mario Rossi\n"
            "Codice Fiscale: RSSMRA80A01H501U\n"
            "PEC: applicant@pec.example.test\n"
            "Oggetto: Richiesta accesso agli atti amministrativi\n"
        )
        run = extractor.extract("d_it_1", "auto", ocr_output(doc_text))
        values = {f["field_code"]: f["normalized_value"] for f in run["field_results"]}
        self.assertEqual(run["document_family"], "general_correspondence")
        self.assertEqual(values["reference_number"], "PROT-2026-9874")
        self.assertEqual(values["document_date"], "2026-04-15")
        self.assertEqual(values["sender_name"], "Mario Rossi")
        self.assertEqual(values["fiscal_code"], "RSSMRA80A01H501U")
        self.assertEqual(values["pec_address"], "applicant@pec.example.test")
        self.assertEqual(values["subject"], "Richiesta accesso agli atti amministrativi")

        # 2. Italian FatturaPA invoice
        invoice_text = (
            "Fattura n. FPA-2026/088\n"
            "Data fattura: 10/05/2026\n"
            "Cedente/Prestatore: Acme Italia Srl\n"
            "Partita IVA: IT00000000000\n"
            "Codice Fiscale: 12345678901\n"
            "Codice CIG: 9876543210\n"
            "Codice CUP: B12C34000560007\n"
            "IBAN: IT60X0542811101000000123456\n"
            "Totale documento: 5.430,50 €\n"
        )
        inv_run = extractor.extract("d_it_2", "auto", ocr_output(invoice_text))
        inv_values = {f["field_code"]: f["normalized_value"] for f in inv_run["field_results"]}
        self.assertEqual(inv_run["document_family"], "invoice")
        self.assertEqual(inv_values["invoice_number"], "FPA-2026/088")
        self.assertEqual(inv_values["invoice_date"], "2026-05-10")
        self.assertEqual(inv_values["supplier_name"], "Acme Italia Srl")
        self.assertEqual(inv_values["vat_number"], "IT00000000000")
        self.assertEqual(inv_values["fiscal_code"], "12345678901")
        self.assertEqual(inv_values["cig_code"], "9876543210")
        self.assertEqual(inv_values["cup_code"], "B12C34000560007")
        self.assertEqual(inv_values["iban"], "IT60X0542811101000000123456")
        self.assertEqual(inv_values["total_amount"], "5430.50")
        self.assertFalse(inv_run["needs_human_review"])


if __name__ == "__main__":
    unittest.main()
