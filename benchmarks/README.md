# xTRACT Benchmark Suite

This directory contains the reproducible evaluation suite for **xTRACT** (`KOKUTBON/xTRACT`).

It evaluates end-to-end document intake, OCR processing, document classification, field extraction, validation rules, and runtime latency against synthetic test documents covering administrative and financial document archetypes.

---

## Metrics Measured

1. **Document Classification Accuracy**:
   $$\text{Accuracy} = \frac{\text{Correctly Classified Documents}}{\text{Total Documents}}$$
   Measures whether documents are properly assigned to their respective taxonomy types (e.g. `invoice`, `general_correspondence`, `building_permit_application`, `residence_application`).

2. **Field Extraction Precision, Recall, and F1-Score**:
   $$\text{Precision} = \frac{\text{TP}}{\text{TP} + \text{FP}}, \quad \text{Recall} = \frac{\text{TP}}{\text{TP} + \text{FN}}, \quad \text{F1} = \frac{2 \cdot \text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$$
   Measures whether extracted fields match expected ground-truth values and whether non-present fields are properly omitted.

3. **Field Exact Match Rate**:
   $$\text{Exact Match} = \frac{\text{Exact Field Value Matches}}{\text{Total Expected Fields}}$$

4. **Auto-Validation Precision**:
   $$\text{Auto-Val Precision} = \frac{\text{Auto-Approved Documents without Errors}}{\text{Total Auto-Approved Documents}}$$
   Ensures that documents automatically validated without operator intervention do not contain erroneous fields.

5. **Mean Processing Latency**:
   End-to-end processing time (in milliseconds) from intake ingestion through text extraction and queue processing.

6. **OCR Quality Metrics (CER & WER)**:
   Character Error Rate (CER) and Word Error Rate (WER) using Levenshtein distance calculations against canonical references.

---

## Directory Layout

- `dataset/`: Contains synthetic test documents and `ground_truth.json` containing ground-truth metadata.
- `evaluator.py`: Implements CER, WER, Levenshtein distance, and aggregate statistical scoring (`BenchmarkEvaluator`).
- `run_benchmark.py`: Standalone CLI execution script that instantiates a temporary xTRACT platform, executes synchronous processing across all dataset files, and prints a formatted results table.

---

## How to Run

### Via Python Module:
```bash
python3 -m benchmarks.run_benchmark
```

### Via CLI:
```bash
xtract benchmark
```

### Via Pytest / CI:
```bash
pytest tests/test_benchmarks.py
```
