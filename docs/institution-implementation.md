# Institution implementation handbook

xTRACT is one application with a separate implementation bundle for each institution.
Keep institution customization in configuration, rather than maintaining a fork of the
application. The initial supported deployment model is one application installation,
database and document store per institution. HTTP identity boundaries also protect
institutional data when a database contains multiple institutions, but configuration,
branding, document rules and connectors are installation-wide.

## Create an implementation

Install a tested application release and its OCR dependencies, then create a bundle:

```sh
xtract init-institution --output /srv/xtract/city-demo \
  --institution city-demo --name "City Demo" --pack it-pa --locale it
xtract --deployment /srv/xtract/city-demo validate-config
xtract --deployment /srv/xtract/city-demo doctor
```

Use `general` for the international base configuration or `it-pa` for the Italian
administrative starter configuration. These are starting points for implementation;
a pack does not certify compliance or validate an institution's actual integrations.
Creation refuses to overwrite an existing folder. Invalid setup is staged and rejected
before a bundle is published. Validation and doctor do not create a runtime database.

The bundle contains:

| Location | Purpose |
| --- | --- |
| `deployment.json` | Institution ID, base pack, office directory, runtime settings |
| `config/institution-profile.v1.json` | Display name, branding URLs, colours, locale |
| `config/auth-policy.v1.json` | Authentication and role-claim configuration |
| Other `config/*.json` files | Taxonomy, aliases, extraction, OCR, connectors, routing |
| `branding/` | Institution logo and icon assets |
| `IMPLEMENTATION.md` | Local implementation checklist |
| `data/` | Database and document artifacts, created only during runtime |

Keep deployment.json, config and branding in a controlled configuration repository.
Keep secrets and runtime documents outside that repository. Configuration is loaded
at startup; restart the application after approving a configuration change.

## Configure the institution

Edit the institution profile and replace the logo/icon files in branding. Asset URLs
should use `/branding/...`. The portal's content security policy expects local assets.
Set the country, supported languages and default language deliberately; adding a locale
identifier does not automatically translate the application or its extraction rules.

Define offices in deployment.json using stable IDs, display names and enabled flags.
The default office must exist and be enabled. The upload dialog lists enabled offices,
and the API and deployment CLI reject uploads to unknown or disabled offices.
Offices are organizational labels; access isolation currently operates at institution
level, not office level.

Review the taxonomy with institutional operators. Define the document families,
required fields, labels, validation patterns, aliases and extraction policies they
actually use. Test representative documents, including poor scans and missing fields,
before enabling automatic validation. Configuration validation checks JSON schemas,
identity consistency, office defaults, alias regexes and references, and integration
connector references. It does not prove extraction accuracy.

The initial policy uses JWT authentication and requires a private signing key supplied
through `XTRACT_JWT_SECRET` in the service environment or secret manager. Use a securely
generated key of at least 32 characters. Secrets do not belong in deployment.json.
For an installation behind an authentication gateway, configure header federation and
block direct server access; the gateway must strip client-supplied identity headers.
Direct OIDC login and public-key verification are not implemented.

Provision an initial administrator from the trusted server environment:

```sh
xtract --deployment /srv/xtract/city-demo issue-token \
  --user records-admin --role admin --expires-in 3600
```

This prints a bearer credential. Deliver it privately and enter it in the portal's
API-token setting. The command requires a configured signing key and an enabled office,
and issues tokens only for the selected institution. This is initial provisioning;
central account lifecycle, federation and revocation require further product work.

The local registry issues local sequential references. Connectors with no remote
endpoint must not be treated as a successful integration with the institution's
protocol system. Configure real endpoints, environment-backed credentials, mappings,
retry policy and reconciliation with that system's owner. Verify delivery, rejection,
timeout, retry and duplicate-request behavior in the institution's test environment.
Generated bundles disable remote delivery routes initially. Enable them only after
configuration; preflight blocks enabled remote routes without HTTPS endpoints or
their required bearer credentials.

## Acceptance and go-live

```sh
xtract --deployment /srv/xtract/city-demo validate-config
xtract --deployment /srv/xtract/city-demo doctor
xtract --deployment /srv/xtract/city-demo serve
```

`doctor` returns a nonzero status for blocking errors and reports warnings separately.
`ready_to_start` means the checked runtime prerequisites pass; it is not production
certification. Deployment startup performs validation and preflight before opening
the database. The default bind address is loopback; provide HTTPS through a reverse
proxy and use a supervised application service for network installation.

Before go-live, record acceptance evidence for authentication and institution isolation,
real document extraction/review, connector reconciliation, accessibility, concurrent
operator workload, monitoring, and restoration of both the database and document store.
Agree who owns the application, configuration, infrastructure, training and support.

For upgrades, preserve the institution bundle and private data, stage the new release,
validate the effective configuration, run acceptance tests, and obtain an approved
backup and rollback plan before changing production. Automatic database migrations,
backup/restore tooling and release rollback remain future implementation work.

## Product milestones

| Milestone | Current state |
| --- | --- |
| Verified HTTP authentication and institution boundaries | Implemented and regression-tested |
| Separate institution bundles, provisioning, validation and preflight | Implemented |
| Bundled console, branding and preset resources in Python packages | Implemented; validate release artifacts |
| Administrative configuration UI with preview and approval history | Planned |
| Complete SSO, account lifecycle and token revocation | Planned |
| Versioned migrations and backup/restore tooling | Planned |
| Supervised production deployment and operational monitoring | Planned |
| Tamper-resistant audit and enforced retention workflows | Planned |
| Institution-specific connector and document acceptance | Required for each implementation |
