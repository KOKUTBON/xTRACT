# Research exports

The repository ships without documents, databases, or pre-populated records.
Process your own permitted source documents, verify extracted fields in the
portal, and export via the menu or CLI.

- CSV: one row per field, including document identity, original extraction,
  current value, correction flag, OCR confidence, source text, and reviewer.
- JSON: an array of document interchange payloads.
- JSON Lines: one research record per document, with `document`, `source`, and
  `field_provenance`; `--include-text` also adds `ocr_text` and `ocr_pages`.

Exports default to validated and registered stages. `--stage all` includes
unfinished and discarded records. Unfinished records have `export_stage: draft`. Check `trace.workflow_stage`,
`document_type.is_final`, and each field's `lifecycle_stage` before treating a
value as ground truth. Confidence is a heuristic, not calibrated probability.
Source text and field values can contain personal information even when full
OCR text is excluded. CSV values are preserved verbatim for research fidelity;
import untrusted strings as text in spreadsheet software.

The software's MIT license does not grant rights to uploaded documents or their
contents. Review permissions and anonymize records before sharing a dataset.
For evaluation, split by source document rather than individual field to avoid
leakage; compare extracted and reviewed values by family and OCR engine.
