# Security Policy

## Supported Versions

Security fixes are applied to the latest release on the default branch.

| Version | Supported |
| --- | --- |
| 0.1.x | :white_check_mark: |

## Reporting a Vulnerability

Please report suspected vulnerabilities privately through GitHub's **Report a vulnerability** button (Security → Advisories) on this repository. Do not open a public issue.

Include the affected component, version, reproduction steps, expected vs. observed behavior, and impact. Always use synthetic documents in proof-of-concept tests — never real personal data, credentials, or production files.

Reports are acknowledged promptly, and disclosure is coordinated responsibly with the reporter.

## Security Architecture & Safe Deployment

xTRACT is designed with a **local-first security model**:
- **Zero Third-Party Egress**: The software performs all parsing, OCR, extraction, and assistant queries on the local machine without transmitting documents or metadata to external AI or cloud providers.
- **Verified Authentication**: Protected API endpoints require a verified bearer token or explicitly trusted proxy identity when authentication is configured. Health, branding, pack discovery, and authentication metadata are public. The token endpoint separately requires verified administrator credentials or the configured shared API token. Anonymous development users cannot mint tokens. JWT signatures are always verified, and no built-in signing secret exists. Query-string tokens (`?access_token=...`) cannot authenticate requests.
- **Institution Isolation**: HTTP document access, mutations, exception resolution, statistics, queues, and exports are scoped to the authenticated institution, including administrators. Institution administrators cannot mint tokens for another institution. The deployment shared API token can provision institutional tokens and must be restricted to deployment administrators. CLI, filesystem, and database access are trusted administrative capabilities; offices within an institution share access.
- **Session-Scoped Portal Storage**: In the operator portal, authentication credentials are stored exclusively in `sessionStorage` rather than `localStorage`, preventing cross-tab persistence and lingering sessions across browser restarts.
- **Memory-Safe Object Previews**: Document previews and downloads fetch binary content with explicit Bearer headers, create transient in-memory `blob:` URLs, and immediately revoke them upon completion to prevent memory exhaustion and unauthorized object exposure.
- **Denial of Service & Decompression Bomb Protection**: The OCR engine enforces page dimension limits (`MAX_PAGE_DIMENSION = 5000px`), per-page pixel caps (`MAX_PAGE_PIXELS = 25M`), total document pixel caps (`MAX_TOTAL_PIXELS = 100M`), and maximum document page counts (50 pages). Page timeouts (120s) and global execution deadlines abort stalled or malicious documents.
- **Content Security Policy (CSP)**: HTTP responses enforce strict CSP headers (`frame-src 'self' blob:; object-src 'self' blob:; X-Frame-Options: DENY; X-Content-Type-Options: nosniff`).

When deploying on a network:
- Put the server behind a reverse proxy terminating TLS (HTTPS).
- Restrict filesystem access to `data/` using appropriate operating system file permissions.
- Integrate an identity provider (e.g. OIDC or reverse-proxy authentication) if multi-operator identity verification is required.

## Private reporting contact

Email [kokutbon@gmail.com](mailto:kokutbon@gmail.com) with subject `[xTRACT] Security report`. Include affected version/commit, reproduction using synthetic data, preconditions and impact. Do not include live credentials or personal data. This mailbox is the fallback while the repository is private or GitHub's reporting form is unavailable.

After publication, prefer [GitHub private vulnerability reporting](https://github.com/KOKUTBON/xTRACT/security/advisories/new) when enabled. Acknowledgment and remediation depend on maintainer availability; no response deadline is guaranteed. Coordinate disclosure and fixes privately.
