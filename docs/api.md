# HTTP API

The portal and API share an origin. Requests and responses use JSON unless noted.
When authentication is enabled (`XTRACT_API_TOKEN`), set `Authorization: Bearer <token>`.
Query-string credentials (`?access_token=...`) are **strictly rejected** to prevent token leakage in server logs, proxy access logs, and browser history.
`X-Operator-Id` supplies an audit label for backoffice actions; it is not an identity authority.

For the full machine-readable OpenAPI 3.1.0 contract, see [`docs/openapi.yaml`](openapi.yaml).

## Endpoint Overview

| Method | Path under /api/v1 | Action |
| --- | --- | --- |
| GET | /health | Public health status and version info |
| GET | /config | Document families, limits, available OCR engines, stages |
| GET | /stats | Workflow stage totals and job statistics |
| POST | /documents | Ingest document (`content_base64` or `text_content`) |
| GET | /documents | Search documents with `q`, `stage`, `institution_id`, `limit` (max 1000) |
| GET | /documents/{id} | Workspace read model (fields, history, audit, actions) |
| GET | /documents/{id}/source | Original bytes; `download=1` sets attachment disposition |
| GET | /documents/{id}/ocr | Normalized OCR JSON output with line bounding boxes |
| GET | /documents/{id}/export | Research record; optional `include_text=true` |
| PUT | /documents/{id}/fields/{field} | Set value, optional `comment` and boolean `force` |
| POST | /documents/{id}/fields/{field}/confirm | Confirm extracted value |
| POST | /documents/{id}/review/complete | Complete review and promote to validated |
| POST | /documents/{id}/review/reopen | Reopen validated document with reason |
| POST | /documents/{id}/discard | Discard unprocessable document with reason |
| POST | /documents/{id}/reprocess | Queue scope: `all`, `ocr`, `extraction`, `integration` |
| POST | /documents/{id}/integration/retry | Retry institutional registration dispatch |
| POST | /documents/{id}/assistant | Ask a local source-bounded question with citations |
| GET | /review-queue | Pending human review tasks |
| GET | /exceptions | System and pipeline exceptions (`open` or `resolved`) |
| POST | /exceptions/{id}/resolve | Mark exception resolved with comment |
| GET | /export/fields.csv | CSV export of extracted vs verified fields |
| GET | /export/documents.json | JSON array export of validated documents |
| GET | /export/documents.jsonl | Streaming JSON Lines export; optional `include_text=true` |

Uploads accept optional `document_family` (default `auto`), `mime_type`, `title`,
`institution_id`, and `office_id`. Successful upload returns `201 Accepted` and identifiers;
processing is asynchronous. Poll the document workspace to observe stage updates.
Exports accept `stage=validated` (default), `all`, or a specific workflow stage.
Errors return `error`, `message`, and `details` with standard HTTP error status codes.
Respect workspace `permitted_actions` to avoid `409 Conflict` transitions.
