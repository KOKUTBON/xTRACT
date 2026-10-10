"""Evaluation metrics and statistics calculations for xTRACT benchmarks."""

from __future__ import annotations


def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two sequences."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Character Error Rate (CER) = edit_distance(ref, hyp) / len(ref)."""
    ref = reference.strip()
    hyp = hypothesis.strip()
    if not ref:
        return 0.0 if not hyp else 1.0
    return min(1.0, levenshtein_distance(ref, hyp) / max(1, len(ref)))


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Word Error Rate (WER) = edit_distance(ref_words, hyp_words) / len(ref_words)."""
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return min(1.0, levenshtein_distance(ref_words, hyp_words) / max(1, len(ref_words)))


class BenchmarkEvaluator:
    """Computes precision, recall, F1, exact-match, accuracy, and OCR error rates."""

    def __init__(self) -> None:
        self.doc_count = 0
        self.correct_classifications = 0
        self.field_true_positives = 0
        self.field_false_positives = 0
        self.field_false_negatives = 0
        self.field_exact_matches = 0
        self.total_expected_fields = 0
        self.per_field_stats: dict[str, dict[str, int]] = {}
        self.auto_validated_docs = 0
        self.auto_validated_correct = 0
        self.total_cer = 0.0
        self.total_wer = 0.0
        self.latencies_ms: list[float] = []

    def record_document(
        self,
        doc_filename: str,
        expected: dict,
        actual_type: str,
        actual_fields: dict[str, str | None],
        actual_stage: str,
        ocr_text: str,
        duration_ms: float,
    ) -> None:
        self.doc_count += 1
        self.latencies_ms.append(duration_ms)

        # Classification
        if actual_type == expected.get("type_code"):
            self.correct_classifications += 1

        # Fields evaluation
        expected_fields = expected.get("fields", {})
        all_field_keys = set(expected_fields.keys()) | set(actual_fields.keys())
        doc_fields_all_match = True

        for key in all_field_keys:
            exp_val = expected_fields.get(key)
            act_val = actual_fields.get(key)

            stats = self.per_field_stats.setdefault(
                key, {"tp": 0, "fp": 0, "fn": 0, "exact": 0, "total": 0}
            )

            if exp_val is not None:
                self.total_expected_fields += 1
                stats["total"] += 1

            if exp_val is not None and act_val is not None:
                if str(exp_val).strip() == str(act_val).strip():
                    self.field_true_positives += 1
                    self.field_exact_matches += 1
                    stats["tp"] += 1
                    stats["exact"] += 1
                else:
                    self.field_false_positives += 1
                    stats["fp"] += 1
                    doc_fields_all_match = False
            elif exp_val is not None and act_val is None:
                self.field_false_negatives += 1
                stats["fn"] += 1
                doc_fields_all_match = False
            elif exp_val is None and act_val is not None:
                self.field_false_positives += 1
                stats["fp"] += 1
                doc_fields_all_match = False

        # Auto-validation precision
        if actual_stage in ("validated", "protocol_pending", "protocol_registered"):
            self.auto_validated_docs += 1
            if doc_fields_all_match:
                self.auto_validated_correct += 1

    def summary(self) -> dict:
        tp = self.field_true_positives
        fp = self.field_false_positives
        fn = self.field_false_negatives

        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 1.0
        classification_acc = (
            self.correct_classifications / self.doc_count if self.doc_count > 0 else 1.0
        )
        exact_match_rate = (
            self.field_exact_matches / self.total_expected_fields
            if self.total_expected_fields > 0
            else 1.0
        )
        auto_val_precision = (
            self.auto_validated_correct / self.auto_validated_docs
            if self.auto_validated_docs > 0
            else 1.0
        )
        mean_latency = sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else 0.0

        return {
            "document_count": self.doc_count,
            "classification_accuracy": round(classification_acc * 100, 1),
            "field_precision": round(precision * 100, 1),
            "field_recall": round(recall * 100, 1),
            "field_f1": round(f1 * 100, 1),
            "exact_match_rate": round(exact_match_rate * 100, 1),
            "auto_validation_precision": round(auto_val_precision * 100, 1),
            "mean_latency_ms": round(mean_latency, 1),
            "per_field_stats": self.per_field_stats,
        }
