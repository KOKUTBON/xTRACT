# Configuration

xTRACT runs with sensible zero-configuration defaults out of the box. To customize settings, set environment variables in your shell or service/container environment. The [`.env.example`](../.env.example) template can be loaded by your service manager or Docker's `--env-file`; the application does not automatically load `.env` files. Defaults are defined in [`src/xtract/config.py`](../src/xtract/config.py).

For institutional installations, use a [separate deployment bundle](institution-implementation.md)
and select it with `xtract --deployment /path/to/institution COMMAND`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `XTRACT_HOST` | `127.0.0.1` | Bind address |
| `XTRACT_PORT` | `8000` | HTTP port |
| `XTRACT_DATA_DIR` | `./data` | Private runtime directory |
| `XTRACT_DATABASE_PATH` | `data/xtract.db` | Override SQLite database path |
| `XTRACT_STORAGE_ROOT` | `data/storage` | Override local object storage root |
| `XTRACT_CONFIG_DIR` | `./config` | Policy and taxonomy directory |
| `XTRACT_API_TOKEN` | empty | Shared API bearer token (`Authorization: Bearer <token>`) |
| `XTRACT_AUTH_MODE` | `auto` | Authentication mode: `auto`, `none`, `token`, `jwt`, `oidc`, or `header` |
| `XTRACT_JWT_SECRET` | empty | HS256 signing key; falls back to a configured API token |
| `XTRACT_JWT_ISSUER` | empty | Expected JWT issuer |
| `XTRACT_JWT_AUDIENCE` | empty | Expected JWT audience |
| `XTRACT_TRUST_FORWARDED_HEADERS` | `false` | Trust identity headers from an authentication proxy |
| `XTRACT_DEFAULT_INSTITUTION` | `default` | Intake namespace |
| `XTRACT_DEFAULT_OFFICE` | `general` | Intake office identifier |
| `XTRACT_MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Maximum original upload file size |
| `XTRACT_REJECT_DUPLICATES` | `true` | Reject duplicate content per institution via SHA-256 |
| `XTRACT_WORKER_ENABLED` | `true` | Run background job worker thread alongside server |
| `XTRACT_WORKER_POLL_SECONDS` | `1.0` | Queue poll interval in seconds |
| `XTRACT_CORS_ORIGINS` | empty | Comma-separated allowed CORS origins |
| `XTRACT_TESSERACT_LANG` | `eng` | Installed Tesseract language codes (e.g. `ita+eng`) |

Use `xtract --data-dir /private/path serve` or `python xtract.py --data-dir /private/path serve` to override the data
directory. Global CLI options precede the subcommand.

## Authentication

Anonymous administrator access is available for local development when the mode is
`auto` or `none` and no API token, JWT secret, OIDC issuer, or trusted proxy is configured.
Configuring any of these requires authentication, even in `none` mode. Explicit
protected modes reject anonymous requests even when their credentials are missing.
When the configured mode is `auto`, the authentication policy's mode is used.
Invalid supplied credentials are rejected instead of falling back to anonymous access.

JWT signatures are always verified with `XTRACT_JWT_SECRET` or the configured API
token. There is no built-in signing secret. OIDC issuer settings alone do not
implement OIDC login or public-key verification; use a trusted authentication proxy
for federation until a complete OIDC integration is available.

`POST /api/v1/auth/token` requires a verified user with `admin:manage`, or the
configured shared API token in the request's `api_token` field. Anonymous local
administrators cannot issue tokens. For a JWT-only installation, provision the
initial administrator token through trusted server-side tooling using the configured
signing key. Requested roles must be supported roles, and token lifetimes must be
between 1 and 86400 seconds. A proxy administrator also needs a signing key configured
to issue JWTs.

Enable header federation only behind a trusted authentication proxy that strips
client-supplied identity headers and prevents direct access to the application server.

## Institution boundaries

API document access is limited to the institution in the verified identity, including
institution administrators. Searches, review queues, exceptions, dashboard counts,
and CSV/JSON/JSONL exports use that institution automatically. Explicit foreign
institution filters or uploads return `403`; foreign document and exception identifiers
return `404`. These checks run before document commands, downloads, or assistant calls.
Uploads without an institution or office use the signed-in user's defaults.

An institution administrator can issue tokens only for their own institution.
The deployment's shared API token is a bootstrap credential that can provision
tokens for other institutions; keep it with deployment administrators rather than
distributing it to institutional operators. Direct API calls using that shared token
are scoped to `XTRACT_DEFAULT_INSTITUTION`.

These boundaries cover the HTTP API. Server-side workers and CLI exports are trusted
administrative tools and can process all institutions. Database and filesystem access
must remain restricted to deployment administrators. Offices within one institution
currently share access; office-level isolation is not implemented.

The JSON configuration files in `config/` (also packaged in `src/xtract/defaults/` as fallback) contain document taxonomy, field aliases,
extraction rules, OCR routing, connector definitions, and integration policy.
They are application configuration, not sample documents. To add a family:
1. Extend the taxonomy and aliases in `config/field-taxonomy.v1.json` and `config/alias-dictionary.v1.json`.
2. Add detection keywords to `config/extraction-policy.v1.json`.
3. Validate schemas and contracts with `make ci`.

JSON Schemas for all contracts are located in [`src/xtract/contracts/schemas/`](../src/xtract/contracts/schemas/).

The default connector assigns local sequential registration references. Remote registration
requires configuring an HTTPS connector and its credential environment variable;
never put credentials in the connector catalog.

Scanned PDFs and multi-frame images are limited to 50 pages per file. Split larger
files before uploading; they are rejected rather than silently truncated. Each
Tesseract page has an individual 120-second execution timeout as well as a total document deadline guard.
Mixed PDFs with scanned pages fall back to OCR even when other pages contain embedded text.
