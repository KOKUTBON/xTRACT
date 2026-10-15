"""xTRACT Benchmark Runner: Evaluates classification, extraction, validation, and latency."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from benchmarks.evaluator import BenchmarkEvaluator
from xtract.config import PlatformConfig
from xtract.core import Platform

BENCHMARK_DIR = Path(__file__).resolve().parent
DATASET_DIR = BENCHMARK_DIR / "dataset"
GROUND_TRUTH_FILE = DATASET_DIR / "ground_truth.json"


def run_benchmarks(quiet: bool = False) -> int:
    if not GROUND_TRUTH_FILE.is_file():
        print(f"Ground truth file missing: {GROUND_TRUTH_FILE}", file=sys.stderr)
        return 1

    ground_truth = json.loads(GROUND_TRUTH_FILE.read_text("utf-8"))
    evaluator = BenchmarkEvaluator()

    with tempfile.TemporaryDirectory() as tmp_dir:
        config = PlatformConfig(data_dir=Path(tmp_dir), worker_enabled=False)
        platform = Platform(config)

        if not quiet:
            print(f"Running xTRACT benchmark suite on {len(ground_truth)} documents...")

        for doc_filename, expected in ground_truth.items():
            doc_path = DATASET_DIR / doc_filename
            if not doc_path.is_file():
                continue

            content = doc_path.read_bytes()
            start = time.perf_counter()

            # Ingest
            doc, _ = platform.intake.ingest_document(
                institution_id="bench",
                office_id="bench",
                document_family="auto",
                filename=doc_filename,
                content=content,
                mime_type="text/plain",
            )
            # Process synchronously
            platform.process_pending()
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Retrieve workspace
            ws = platform.projections.get_document_workspace(doc["document_id"])
            summary = ws["document_summary"]
            actual_type = summary.get("document_type_code", "")
            actual_stage = ws.get("workflow_state", {}).get("stage", "")
            actual_fields = {
                f["field_code"]: f.get("current_value") or f.get("extracted_value")
                for f in ws.get("field_panels", [])
            }
            ocr_text = ws.get("viewer", {}).get("ocr_text", "")

            evaluator.record_document(
                doc_filename=doc_filename,
                expected=expected,
                actual_type=actual_type,
                actual_fields=actual_fields,
                actual_stage=actual_stage,
                ocr_text=ocr_text,
                duration_ms=elapsed_ms,
            )

    results = evaluator.summary()

    # Formatted display table
    print("\n" + "=" * 65)
    print("                xTRACT EXTRACTION BENCHMARK RESULTS")
    print("=" * 65)
    print(f"{'Task / Metric':<40} {'Result':>20}")
    print("-" * 65)
    print(f"{'Document Classification Accuracy':<40} {results['classification_accuracy']:>19}%")
    print(f"{'Overall Field Precision':<40} {results['field_precision']:>19}%")
    print(f"{'Overall Field Recall':<40} {results['field_recall']:>19}%")
    print(f"{'Overall Field F1 Score':<40} {results['field_f1']:>19}%")
    print(f"{'Field Exact Match Rate':<40} {results['exact_match_rate']:>19}%")
    print(f"{'Auto-Validation Precision':<40} {results['auto_validation_precision']:>19}%")
    print(f"{'Mean Processing Latency':<40} {results['mean_latency_ms']:>17} ms")
    print("=" * 65 + "\n")

    # Threshold checks
    ok = (
        results["classification_accuracy"] >= 90.0
        and results["field_f1"] >= 85.0
        and results["auto_validation_precision"] >= 90.0
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run_benchmarks())
