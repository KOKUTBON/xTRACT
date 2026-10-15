"""Institution implementation bundles and preflight checks (no runtime data writes)."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from xtract.auth.service import AuthService
from xtract.config import PACKAGE_DIR, PlatformConfig

CONFIG_NAMES = (
    "institution-profile",
    "auth-policy",
    "field-taxonomy",
    "alias-dictionary",
    "extraction-policy",
    "ocr-routing-policy",
    "connector-catalog",
    "integration-policy",
)


class DeploymentError(ValueError):
    pass


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise DeploymentError(f"Cannot read valid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise DeploymentError(f"Expected a JSON object: {path.name}")
    return value


def validate_schema(name: str, value: dict) -> None:
    schemas = [read_json(p) for p in (PACKAGE_DIR / "contracts" / "schemas").glob("*.json")]
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)
    schema = read_json(PACKAGE_DIR / "contracts" / "schemas" / name)
    errors = list(Draft202012Validator(schema, registry=registry).iter_errors(value))
    if errors:
        # Report paths, not field values: configuration diagnostics must not echo secrets.
        locations = [".".join(map(str, e.absolute_path)) or "root" for e in errors]
        raise DeploymentError(f"Invalid {name}: {', '.join(locations)}")


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", "utf-8")


def initialize(
    root: Path, institution: str, name: str, pack: str = "general", locale: str = "en"
) -> Path:
    root = root.resolve()
    if root.exists():
        raise DeploymentError(
            "Destination already exists; institution bundles are never overwritten."
        )
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", institution) or institution in (".", ".."):
        raise DeploymentError(
            "Institution ID must contain 1–64 letters, numbers, dots, underscores or hyphens."
        )
    if pack not in {"general", "it-pa"}:
        raise DeploymentError("Choose a bundled pack: general or it-pa.")
    source = PACKAGE_DIR / "presets" / pack
    profile = read_json(source / "institution-profile.v1.json")
    if locale not in profile["supported_locales"]:
        raise DeploymentError("Locale is not supported by this pack.")
    profile.update(
        institution_id=institution,
        institution_name=name,
        app_title=f"{name} · Document Console",
        default_locale=locale,
    )
    validate_schema("institution-profile.v1.schema.json", profile)
    manifest = {
        "version": "1.0.0",
        "institution_id": institution,
        "base_pack": pack,
        "offices": [{"office_id": "general", "name": "General office", "enabled": True}],
        "runtime": {
            "host": "127.0.0.1",
            "port": 8000,
            "default_office": "general",
            "tesseract_lang": "ita+eng" if locale == "it" else "eng",
            "max_upload_bytes": 52428800,
        },
    }
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".xtract-setup-", dir=root.parent) as tmp:
        staging = Path(tmp) / "bundle"
        (staging / "config").mkdir(parents=True)
        for config_name in CONFIG_NAMES:
            shutil.copy2(source / f"{config_name}.v1.json", staging / "config")
        write_json(staging / "config/institution-profile.v1.json", profile)
        policy_path = staging / "config/auth-policy.v1.json"
        policy = read_json(policy_path)
        policy["auth_mode"] = "jwt"
        write_json(policy_path, policy)
        # Starter connectors are templates; remote delivery is an implementation choice.
        catalog = read_json(staging / "config/connector-catalog.v1.json")
        channels = {c["connector_id"]: c["channel_type"] for c in catalog["connectors"]}
        integration_path = staging / "config/integration-policy.v1.json"
        integration = read_json(integration_path)
        for route in integration["routes"]:
            if channels.get(route["target_connector_id"]) != "local_registry":
                route["enabled"] = False
        write_json(integration_path, integration)
        branding = PlatformConfig().branding_dir
        if branding.is_dir():
            shutil.copytree(branding, staging / "branding")
        else:
            raise DeploymentError("Bundled branding assets are unavailable.")
        write_json(staging / "deployment.json", manifest)
        validate_bundle(staging)
        (staging / "IMPLEMENTATION.md").write_text(
            "# Institution implementation\n\n"
            "1. Review deployment.json: offices, host, port and OCR languages.\n"
            "2. Customize config/institution-profile.v1.json and branding/.\n"
            "3. Confirm document families, aliases, extraction and review rules.\n"
            "4. Configure actual protocol endpoints and credential environment variables.\n"
            "   The default local registry is not an external protocol integration.\n"
            "5. Set XTRACT_JWT_SECRET through your deployment secret manager.\n"
            "   For initial token issuance, optionally configure XTRACT_API_TOKEN.\n"
            "6. Run validate-config and doctor with --deployment pointing to this folder.\n"
            "7. Configure HTTPS, backup/restore, monitoring and access to the server.\n"
            "8. Complete representative document and operator acceptance tests before go-live.\n\n"
            "Keep config/ and deployment.json under controlled version management.\n"
            "Keep secrets and data/ out of version control. Do not edit core application files.\n",
            "utf-8",
        )
        (staging / ".gitignore").write_text("data/\n.env\n*.key\n", "utf-8")
        staging.rename(root)
    return root


def validate_bundle(root: Path) -> dict:
    root = root.resolve()
    manifest = read_json(root / "deployment.json")
    validate_schema("institution-deployment.v1.schema.json", manifest)
    configs = {}
    for name in CONFIG_NAMES:
        configs[name] = read_json(root / "config" / f"{name}.v1.json")
        validate_schema(f"{name}.v1.schema.json", configs[name])
    profile = configs["institution-profile"]
    if profile["institution_id"] != manifest["institution_id"]:
        raise DeploymentError("Institution identity differs between manifest and profile.")
    if profile["default_locale"] not in profile["supported_locales"]:
        raise DeploymentError("Default locale is not in supported_locales.")
    offices = [o["office_id"] for o in manifest["offices"]]
    if len(offices) != len(set(offices)):
        raise DeploymentError("Duplicate office IDs.")
    active_offices = [o["office_id"] for o in manifest["offices"] if o["enabled"]]
    if manifest["runtime"]["default_office"] not in active_offices:
        raise DeploymentError("Default office must exist and be enabled.")
    taxonomy = configs["field-taxonomy"]["document_types"]
    families = {t["family_code"] for t in taxonomy}
    fields = {
        (t["family_code"], t["type_code"], f["field_code"]) for t in taxonomy for f in t["fields"]
    }
    for alias in configs["alias-dictionary"]["aliases"]:
        if (alias["document_family"], alias["document_type"], alias["field_code"]) not in fields:
            raise DeploymentError("Alias refers to an unknown document field.")
        try:
            re.compile(alias["value_regex"])
        except re.error as exc:
            raise DeploymentError("Invalid alias regular expression.") from exc
    if configs["extraction-policy"]["default_family"] not in families:
        raise DeploymentError("Unknown default extraction family.")
    catalog = {c["connector_id"] for c in configs["connector-catalog"]["connectors"]}
    if len(catalog) != len(configs["connector-catalog"]["connectors"]):
        raise DeploymentError("Duplicate connector IDs.")
    integration = configs["integration-policy"]
    if integration["default_connector_id"] not in catalog:
        raise DeploymentError("Unknown default connector.")
    for route in integration["routes"]:
        if route["target_connector_id"] not in catalog:
            raise DeploymentError("Integration route targets an unknown connector.")
        if route["document_family"] != "*" and route["document_family"] not in families:
            raise DeploymentError("Integration route uses an unknown document family.")
    return manifest


def load_config(root: Path) -> PlatformConfig:
    root = root.resolve()
    manifest = validate_bundle(root)
    cfg = PlatformConfig(
        data_dir=root / "data",
        database_path=str(root / "data/xtract.db"),
        storage_root=root / "data/storage",
        config_dir=root / "config",
        config_pack=None,
        branding_dir=root / "branding",
        institution_profile_path=root / "config/institution-profile.v1.json",
        auth_policy_path=root / "config/auth-policy.v1.json",
        default_institution=manifest["institution_id"],
        **manifest["runtime"],
    )
    cfg.allowed_offices = tuple(o["office_id"] for o in manifest["offices"] if o["enabled"])
    cfg.offices = manifest["offices"]
    cfg.deployment_pack = manifest["base_pack"]
    profile = cfg.get_institution_profile()
    validate_schema("institution-profile.v1.schema.json", profile)
    if profile["institution_id"] != manifest["institution_id"]:
        raise DeploymentError("An environment override conflicts with the deployment institution.")
    return cfg


def preflight(cfg: PlatformConfig) -> dict:
    """Check effective settings without creating a database or printing credentials."""
    errors, warnings = [], []
    auth = AuthService(cfg)
    if auth.auth_mode not in ("auto", "none", "token", "jwt", "oidc", "header"):
        errors.append("Unknown authentication mode.")
    if not auth.auth_required:
        errors.append(
            "Configure authenticated access; anonymous mode is unsuitable for an institution deployment."
        )
    if auth.auth_mode in ("jwt", "token", "auto") and not (cfg.jwt_secret or cfg.api_token):
        errors.append("Configure XTRACT_JWT_SECRET or XTRACT_API_TOKEN.")
    if cfg.jwt_algorithm != "HS256":
        errors.append("Only HS256 JWT signing is supported.")
    if (cfg.jwt_secret or cfg.api_token) and len(cfg.jwt_secret or cfg.api_token) < 32:
        errors.append("Use a signing secret of at least 32 characters generated securely.")
    if auth.auth_mode == "oidc":
        errors.append(
            "Direct OIDC login is not implemented; configure a trusted authentication proxy."
        )
    if auth.trust_proxy:
        warnings.append(
            "Ensure the authentication proxy strips identity headers and blocks direct server access."
        )
    if cfg.host not in ("127.0.0.1", "localhost"):
        warnings.append("Use a reverse proxy with HTTPS and restrict network access.")
    if not (cfg.portal_dir / "index.html").is_file():
        errors.append("Operator portal assets are missing.")
    if not cfg.branding_dir.is_dir():
        errors.append("Branding assets are missing.")
    from xtract.ocr.engines import default_engines

    engines = {
        key: engine.availability()[0]
        for key, engine in default_engines(languages=cfg.tesseract_lang).items()
    }
    if not engines.get("tesseract"):
        warnings.append(
            "Tesseract is unavailable; scanned-document OCR cannot be accepted for go-live."
        )
    catalog = read_json(cfg.config_file("connector-catalog.v1.json"))["connectors"]
    integration = read_json(cfg.config_file("integration-policy.v1.json"))
    used_connectors = {integration["default_connector_id"]} | {
        route["target_connector_id"] for route in integration["routes"] if route["enabled"]
    }
    if any(c["status"] == "active" and c["channel_type"] == "local_registry" for c in catalog):
        warnings.append(
            "The local registry assigns local references; validate the institution's real protocol integration separately."
        )
    for connector in catalog:
        if connector["status"] != "active" or connector["channel_type"] == "local_registry":
            continue
        if not str(connector.get("base_url", "")).startswith("https://"):
            messages = errors if connector["connector_id"] in used_connectors else warnings
            messages.append(
                f"Connector {connector['connector_id']} has no HTTPS endpoint; verify it before enabling remote delivery."
            )
        if (
            connector["connector_id"] in used_connectors
            and connector["auth_profile"] == "bearer_token"
        ):
            if not os.environ.get(connector.get("auth_token_env", "")):
                errors.append(
                    f"Connector {connector['connector_id']} is missing its environment-backed credential."
                )
    warnings.append(
        "Backup restore, accessibility, load and institutional acceptance checks remain go-live responsibilities."
    )
    return {
        "institution_id": cfg.default_institution,
        "ready_to_start": not errors,
        "errors": errors,
        "warnings": warnings,
        "ocr_engines": engines,
    }
