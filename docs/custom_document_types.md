# Custom Document Extraction Schemas Tutorial

xTRACT uses a schema-driven architecture where document classification, field definitions, normalization rules, and review policies are configured via versioned JSON contracts. This allows institutions and developers to support custom document types (e.g. shipping manifests, medical bills, utility statements) without modifying application code or maintaining separate forks.

This guide walks through defining, configuring, and verifying a custom document type end-to-end.

---

## Architecture Overview

Document extraction in xTRACT relies on three interconnected configuration files located under `config/` (or within your custom institution implementation bundle):

1. **[`config/field-taxonomy.v1.json`](../config/field-taxonomy.v1.json)**: Declares document families, specific document types, and their expected fields with data types, normalization chains, and validation regexes.
2. **[`config/alias-dictionary.v1.json`](../config/alias-dictionary.v1.json)**: Maps textual label variations, synonyms, and anchor regexes found in OCR text to specific `field_code` targets.
3. **[`config/extraction-policy.v1.json`](../config/extraction-policy.v1.json)**: Configures confidence thresholds, auto-validation gates, and mandatory review rules per document family.

---

## Step 1: Define Fields in `field-taxonomy.v1.json`

Add your new document type entry under `"document_types"` in `config/field-taxonomy.v1.json`.

### Supported Value Types

| Value Type | Description | Normalized Representation |
| :--- | :--- | :--- |
| `string` | Single-line text string | Trimmed string |
| `text` | Multi-line text block | String preserving newlines |
| `date` | Calendar date | ISO format (`YYYY-MM-DD`) |
| `decimal` | Numeric amount / currency | Standard decimal string (e.g. `1234.50`) |
| `integer` | Whole integer value | Integer string |
| `boolean` | Boolean flag | Boolean string (`true` / `false`) |
| `identifier` | Alphanumeric reference code | Formatted uppercase identifier |
| `code` | Controlled taxonomy/system code | Normalized code token |

### Normalization Rules

Fields support chained normalization rules applied sequentially before validation:
- `strip`: Removes leading and trailing whitespace.
- `collapse_whitespace`: Collapses multiple internal spaces into a single space.
- `uppercase` / `lowercase` / `title_case`: Case conversions.
- `date_iso`: Converts international date representations (`DD/MM/YYYY`, `MM/DD/YYYY`, localized text) into `YYYY-MM-DD`.
- `decimal`: Parses localized currency formats (`1.234,50 €`, `$1,234.50`) into standard floating-point numbers.
- `fiscal_code` / `vat_number` / `iban`: Standardized national and banking identifier normalizers.

### Example: Shipping Manifest Document Type

```json
{
  "type_code": "shipping_manifest",
  "display_name": "Shipping Manifest / Bill of Lading",
  "family_code": "shipping_manifest",
  "taxonomy_version": "1.0.0",
  "fields": [
    {
      "field_code": "tracking_number",
      "label": "Tracking / Waybill Number",
      "value_type": "identifier",
      "required": true,
      "review_threshold": 0.85,
      "normalization_rules": ["strip", "uppercase"],
      "validation_pattern": "^[A-Z0-9\\-]{6,32}$"
    },
    {
      "field_code": "ship_date",
      "label": "Shipment Date",
      "value_type": "date",
      "required": true,
      "review_threshold": 0.80,
      "normalization_rules": ["strip", "date_iso"],
      "validation_pattern": "^\\d{4}-\\d{2}-\\d{2}$"
    },
    {
      "field_code": "carrier_name",
      "label": "Carrier / Logistics Provider",
      "value_type": "string",
      "required": false,
      "review_threshold": 0.75,
      "normalization_rules": ["strip", "collapse_whitespace"],
      "validation_pattern": "^[^\\d\\n]{2,80}$"
    },
    {
      "field_code": "total_weight_kg",
      "label": "Total Weight (kg)",
      "value_type": "decimal",
      "required": false,
      "review_threshold": 0.80,
      "normalization_rules": ["strip", "decimal"],
      "validation_pattern": "^\\d+(\\.\\d{1,2})?$"
    }
  ]
}
```

---

## Step 2: Define Aliases in `alias-dictionary.v1.json`

OCR text often contains formatting variations, localized phrases, or abbreviated labels (e.g. "Waybill #", "Tracking No.", "AWB:"). Define these aliases under `"aliases"` in `config/alias-dictionary.v1.json`.

Each alias entry must reference an existing `(document_family, document_type, field_code)` defined in your taxonomy:

```json
{
  "alias_id": "alias-ship-track-01",
  "document_family": "shipping_manifest",
  "document_type": "shipping_manifest",
  "field_code": "tracking_number",
  "alias_text": "Tracking Number",
  "locale": "en",
  "priority": 1,
  "value_regex": "(?:Tracking\\s*(?:Number|No\\.?|#)|AWB|Waybill\\s*#?):?\\s*([A-Z0-9\\-]{6,32})"
},
{
  "alias_id": "alias-ship-date-01",
  "document_family": "shipping_manifest",
  "document_type": "shipping_manifest",
  "field_code": "ship_date",
  "alias_text": "Shipment Date",
  "locale": "en",
  "priority": 1,
  "value_regex": "(?:Ship(?:ment)?\\s*Date|Dispatched\\s*On):?\\s*(\\d{1,2}[\\/\\.\\-]\\d{1,2}[\\/\\.\\-]\\d{2,4}|\\d{4}-\\d{2}-\\d{2})"
},
{
  "alias_id": "alias-ship-carrier-01",
  "document_family": "shipping_manifest",
  "document_type": "shipping_manifest",
  "field_code": "carrier_name",
  "alias_text": "Carrier",
  "locale": "en",
  "priority": 1,
  "value_regex": "(?:Carrier|Logistics\\s*Partner):?\\s*([^\\d\\n]{2,80})"
},
{
  "alias_id": "alias-ship-weight-01",
  "document_family": "shipping_manifest",
  "document_type": "shipping_manifest",
  "field_code": "total_weight_kg",
  "alias_text": "Total Weight",
  "locale": "en",
  "priority": 1,
  "value_regex": "(?:Total\\s*Weight|Gross\\s*Mass):?\\s*([0-9.,]+)\\s*(?:kg|KG)?"
}
```

---

## Step 3: Configure Policies in `extraction-policy.v1.json`

In `config/extraction-policy.v1.json`, configure family-level validation thresholds, mandatory fields, and auto-validation criteria:

```json
{
  "family_code": "shipping_manifest",
  "display_name": "Shipping Manifest",
  "auto_validation_enabled": true,
  "min_document_confidence": 0.85,
  "required_fields": [
    "tracking_number",
    "ship_date"
  ],
  "require_all_mandatory_fields": true,
  "routing_rules": {
    "default_office": "logistics",
    "fallback_stage": "manual_review"
  }
}
```

---

## Step 4: Validate Contract Compliance with `make test`

xTRACT enforces strict schema validation for all configuration files using JSON Schema (Draft 2020-12).

Before deploying or running extraction, verify that:
1. All JSON files conform to their respective JSON Schema specifications.
2. All alias entries reference valid, declared document types and field codes.
3. All regular expressions compile cleanly.

Run the test suite:

```bash
make test
# Or directly:
pytest tests/test_contracts.py -v
```

If any field code is misspelled or regex pattern is malformed, `test_contracts.py` will report the exact line and schema discrepancy.

---

## Step 5: Test End-to-End Extraction with CLI

Once validated, verify real document extraction using the CLI:

### Create a Sample Document (`manifest.txt`)

```text
GLOBAL LOGISTICS SERVICES
Bill of Lading / Shipping Manifest
Carrier: Trans-Atlantic Freight
Ship Date: 12/03/2026
Tracking Number: TRK-998241-EU
Total Weight: 450.50 kg
```

### Run Extraction in JSON Format

```bash
xtract run manifest.txt --family shipping_manifest --format json
```

Output:
```json
{
  "document_id": "...",
  "source_filename": "manifest.txt",
  "document_family": "shipping_manifest",
  "document_type_code": "shipping_manifest",
  "workflow_stage": "protocol_registered",
  "fields": {
    "tracking_number": "TRK-998241-EU",
    "ship_date": "2026-03-12",
    "carrier_name": "Trans-Atlantic Freight",
    "total_weight_kg": "450.50"
  }
}
```

### Run Extraction in Tabular CSV Format

```bash
xtract run manifest.txt --family shipping_manifest --format csv
```

Output:
```csv
document_id,source_filename,document_family,document_type_code,workflow_stage,carrier_name,ship_date,total_weight_kg,tracking_number
...,manifest.txt,shipping_manifest,shipping_manifest,protocol_registered,Trans-Atlantic Freight,2026-03-12,450.50,TRK-998241-EU
```

---

## Best Practices

1. **Avoid Overly Broad Regexes**: Anchor regexes to clear prefixes (e.g. `(?:Tracking\\s*#):?\\s*(...)`) to avoid false positive cross-field captures.
2. **Review Thresholds**: Set `review_threshold` higher (`>= 0.85`) for critical financial or legal fields to ensure human-in-the-loop review on low-contrast scans.
3. **Use Isolated Bundles**: In production, create institution-specific bundles via `xtract init-institution` rather than editing global defaults directly.
