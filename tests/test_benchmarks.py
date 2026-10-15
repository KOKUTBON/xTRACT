"""Unit and regression tests for xTRACT benchmark suite and evaluator."""

from __future__ import annotations

import unittest

from benchmarks.evaluator import (
    BenchmarkEvaluator,
    character_error_rate,
    levenshtein_distance,
    word_error_rate,
)
from benchmarks.run_benchmark import run_benchmarks


class TestEvaluator(unittest.TestCase):
    def test_levenshtein_distance(self):
        self.assertEqual(levenshtein_distance("", ""), 0)
        self.assertEqual(levenshtein_distance("kitten", "sitting"), 3)
        self.assertEqual(levenshtein_distance("rosettacode", "raisethysword"), 8)

    def test_cer_and_wer(self):
        self.assertEqual(character_error_rate("hello", "hello"), 0.0)
        self.assertGreater(character_error_rate("hello", "world"), 0.0)
        self.assertEqual(word_error_rate("the quick brown fox", "the quick brown fox"), 0.0)
        self.assertGreater(word_error_rate("the quick brown fox", "the fast brown fox"), 0.0)

    def test_benchmark_evaluator_summary(self):
        evaluator = BenchmarkEvaluator()
        evaluator.record_document(
            doc_filename="test.txt",
            expected={"type_code": "invoice", "fields": {"invoice_number": "123"}},
            actual_type="invoice",
            actual_fields={"invoice_number": "123"},
            actual_stage="validated",
            ocr_text="invoice 123",
            duration_ms=15.0,
        )
        summary = evaluator.summary()
        self.assertEqual(summary["document_count"], 1)
        self.assertEqual(summary["classification_accuracy"], 100.0)
        self.assertEqual(summary["field_f1"], 100.0)
        self.assertEqual(summary["exact_match_rate"], 100.0)
        self.assertEqual(summary["auto_validation_precision"], 100.0)


class TestBenchmarkRunner(unittest.TestCase):
    def test_run_benchmarks_pass(self):
        exit_code = run_benchmarks(quiet=True)
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
