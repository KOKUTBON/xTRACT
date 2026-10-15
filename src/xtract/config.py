"""Configuration settings for xTRACT."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Base package directory and project root directory
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent.parent


def _resource_dir(packaged: str, checkout: str) -> Path:
    bundled = PACKAGE_DIR / "resources" / packaged
    return bundled if bundled.is_dir() else PROJECT_ROOT / checkout


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class PlatformConfig:
    """Runtime settings. Every value can be overridden with an XTRACT_* environment variable."""

    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("XTRACT_DATA_DIR", PROJECT_ROOT / "data"))
    )
    database_path: str | None = field(
        default_factory=lambda: os.environ.get("XTRACT_DATABASE_PATH")
    )
    storage_root: Path | None = field(
        default_factory=lambda: Path(p) if (p := os.environ.get("XTRACT_STORAGE_ROOT")) else None
    )
    config_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("XTRACT_CONFIG_DIR", PROJECT_ROOT / "config"))
    )
    host: str = field(default_factory=lambda: os.environ.get("XTRACT_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("XTRACT_PORT", "8000")))
    api_token: str = field(default_factory=lambda: os.environ.get("XTRACT_API_TOKEN", ""))
    default_institution: str = field(
        default_factory=lambda: os.environ.get("XTRACT_DEFAULT_INSTITUTION", "default")
    )
    default_office: str = field(
        default_factory=lambda: os.environ.get("XTRACT_DEFAULT_OFFICE", "general")
    )
    allowed_offices: tuple[str, ...] | None = None
    offices: list[dict] = field(default_factory=list)
    deployment_pack: str | None = None
    max_upload_bytes: int = field(
        default_factory=lambda: int(
            os.environ.get("XTRACT_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))
        )
    )
    reject_duplicates: bool = field(
        default_factory=lambda: _env_bool("XTRACT_REJECT_DUPLICATES", True)
    )
    worker_enabled: bool = field(default_factory=lambda: _env_bool("XTRACT_WORKER_ENABLED", True))
    worker_poll_seconds: float = field(
        default_factory=lambda: float(os.environ.get("XTRACT_WORKER_POLL_SECONDS", "1.0"))
    )
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip() for o in os.environ.get("XTRACT_CORS_ORIGINS", "").split(",") if o.strip()
        ]
    )
    tesseract_lang: str = field(
        default_factory=lambda: os.environ.get("XTRACT_TESSERACT_LANG", "eng")
    )
    portal_dir: Path = field(
        default_factory=lambda: (
            Path(os.environ["XTRACT_PORTAL_DIR"])
            if "XTRACT_PORTAL_DIR" in os.environ
            else _resource_dir("operator-portal", "apps/operator-portal")
        )
    )
    branding_dir: Path = field(
        default_factory=lambda: (
            Path(os.environ["XTRACT_BRANDING_DIR"])
            if "XTRACT_BRANDING_DIR" in os.environ
            else _resource_dir("branding", "assets/branding")
        )
    )
    institution_profile_path: Path | None = field(
        default_factory=lambda: (
            Path(os.environ["XTRACT_INSTITUTION_PROFILE"])
            if "XTRACT_INSTITUTION_PROFILE" in os.environ
            else None
        )
    )
    exception_taxonomy_path: Path = field(
        default_factory=lambda: (
            Path(os.environ["XTRACT_EXCEPTION_TAXONOMY"])
            if "XTRACT_EXCEPTION_TAXONOMY" in os.environ
            else PACKAGE_DIR / "contracts" / "lifecycle" / "document-exception-taxonomy.v1.json"
        )
    )
    config_pack: str | None = field(
        default_factory=lambda: os.environ.get(
            "XTRACT_CONFIG_PACK", os.environ.get("XTRACT_PRESET_PACK", "general")
        )
    )
    auth_mode: str = field(default_factory=lambda: os.environ.get("XTRACT_AUTH_MODE", "auto"))
    jwt_secret: str = field(default_factory=lambda: os.environ.get("XTRACT_JWT_SECRET", ""))
    jwt_algorithm: str = field(
        default_factory=lambda: os.environ.get("XTRACT_JWT_ALGORITHM", "HS256")
    )
    jwt_issuer: str = field(default_factory=lambda: os.environ.get("XTRACT_JWT_ISSUER", ""))
    jwt_audience: str = field(default_factory=lambda: os.environ.get("XTRACT_JWT_AUDIENCE", ""))
    trust_forwarded_headers: bool = field(
        default_factory=lambda: _env_bool("XTRACT_TRUST_FORWARDED_HEADERS", False)
    )
    oidc_issuer_url: str = field(
        default_factory=lambda: os.environ.get("XTRACT_OIDC_ISSUER_URL", "")
    )
    oidc_client_id: str = field(
        default_factory=lambda: os.environ.get("XTRACT_OIDC_CLIENT_ID", "xtract-console")
    )
    auth_policy_path: Path | None = field(
        default_factory=lambda: (
            Path(os.environ["XTRACT_AUTH_POLICY"]) if "XTRACT_AUTH_POLICY" in os.environ else None
        )
    )

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.config_dir = Path(self.config_dir)
        self.branding_dir = Path(self.branding_dir)
        if self.institution_profile_path is not None:
            self.institution_profile_path = Path(self.institution_profile_path)
        if self.auth_policy_path is not None:
            self.auth_policy_path = Path(self.auth_policy_path)
        if self.database_path is None:
            self.database_path = str(self.data_dir / "xtract.db")
        if self.storage_root is None:
            self.storage_root = self.data_dir / "storage"

    def config_file(self, name: str) -> Path:
        """Resolve a configuration file with domain/preset pack priority.

        Resolution hierarchy:
        1. Custom pack directory in config_dir (presets/<pack>/ or packs/<pack>/ or <pack>/)
        2. Custom root in config_dir
        3. Bundled pack directory in package (presets/<pack>/ or packs/<pack>/)
        4. Bundled package defaults
        """
        pack = self.config_pack.strip() if self.config_pack else None
        if pack:
            for sub in ("presets", "packs", ""):
                candidate = (
                    (self.config_dir / sub / pack / name)
                    if sub
                    else (self.config_dir / pack / name)
                )
                if candidate.is_file():
                    return candidate

        custom = self.config_dir / name
        if custom.is_file():
            return custom

        if pack:
            for sub in ("presets", "packs"):
                candidate = PACKAGE_DIR / sub / pack / name
                if candidate.is_file():
                    return candidate

        packaged = PACKAGE_DIR / "defaults" / name
        if packaged.is_file():
            return packaged
        return custom

    def available_packs(self) -> list[dict]:
        """Discover and list all installed country and domain preset packs."""
        packs: dict[str, dict] = {}
        search_dirs = [
            PACKAGE_DIR / "presets",
            PACKAGE_DIR / "packs",
            self.config_dir / "presets",
            self.config_dir / "packs",
        ]
        for base in search_dirs:
            if not base.is_dir():
                continue
            for item in sorted(base.iterdir()):
                if item.is_dir() and not item.name.startswith("."):
                    pack_id = item.name
                    manifest_file = item / "manifest.json"
                    if not manifest_file.is_file():
                        manifest_file = item / "pack.v1.json"

                    if manifest_file.is_file():
                        try:
                            meta = json.loads(manifest_file.read_text(encoding="utf-8"))
                        except (json.JSONDecodeError, OSError):
                            meta = {}
                    else:
                        meta = {}

                    info = {
                        "pack_id": meta.get("pack_id", pack_id),
                        "name": meta.get("name", pack_id.replace("-", " ").title()),
                        "version": meta.get("version", "1.0.0"),
                        "description": meta.get(
                            "description", f"Preset configuration for {pack_id}"
                        ),
                        "country_code": meta.get("country_code", "XX"),
                        "default_locale": meta.get("default_locale", "en"),
                        "supported_locales": meta.get("supported_locales", ["en"]),
                        "is_active": (pack_id == self.config_pack),
                    }
                    packs[pack_id] = info
        return list(packs.values())

    def get_institution_profile(self) -> dict:
        """Resolve institutional identity, white-label branding, and locale configuration."""
        path = self.institution_profile_path or self.config_file("institution-profile.v1.json")
        profile: dict = {}
        if path and path.is_file():
            try:
                profile = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                profile = {}

        defaults = {
            "version": "1.0.0",
            "institution_id": self.default_institution,
            "institution_name": "xTRACT",
            "app_title": "xTRACT · Operator Console",
            "tagline": "Local-First Document Intake, OCR, and Metadata Extraction",
            "logo_url": "/branding/logo-mark.svg",
            "logo_dark_url": "/branding/logo-mark.svg",
            "app_icon_url": "/branding/logo-app-icon.png",
            "favicon_url": "/branding/logo-mark.svg",
            "accent_color": "#111111",
            "accent_color_dark": "#ffffff",
            "country_code": "IT",
            "default_locale": "en",
            "supported_locales": ["en", "it"],
            "contact_email": "",
        }
        for k, v in defaults.items():
            profile.setdefault(k, v)

        if os.environ.get("XTRACT_INSTITUTION_ID"):
            profile["institution_id"] = os.environ["XTRACT_INSTITUTION_ID"]
        elif self.default_institution != "default":
            profile["institution_id"] = self.default_institution

        if os.environ.get("XTRACT_INSTITUTION_NAME"):
            profile["institution_name"] = os.environ["XTRACT_INSTITUTION_NAME"]
        if os.environ.get("XTRACT_APP_TITLE"):
            profile["app_title"] = os.environ["XTRACT_APP_TITLE"]
        if os.environ.get("XTRACT_TAGLINE"):
            profile["tagline"] = os.environ["XTRACT_TAGLINE"]
        if os.environ.get("XTRACT_BRAND_LOGO_URL"):
            profile["logo_url"] = os.environ["XTRACT_BRAND_LOGO_URL"]
        if os.environ.get("XTRACT_BRAND_APP_ICON_URL"):
            profile["app_icon_url"] = os.environ["XTRACT_BRAND_APP_ICON_URL"]
        if os.environ.get("XTRACT_BRAND_FAVICON_URL"):
            profile["favicon_url"] = os.environ["XTRACT_BRAND_FAVICON_URL"]
        if os.environ.get("XTRACT_BRAND_ACCENT_COLOR"):
            profile["accent_color"] = os.environ["XTRACT_BRAND_ACCENT_COLOR"]
        if os.environ.get("XTRACT_DEFAULT_LOCALE"):
            profile["default_locale"] = os.environ["XTRACT_DEFAULT_LOCALE"]
        if os.environ.get("XTRACT_COUNTRY_CODE"):
            profile["country_code"] = os.environ["XTRACT_COUNTRY_CODE"]

        return profile

    def get_auth_policy(self) -> dict:
        """Resolve institutional authentication, federation, and RBAC policy."""
        path = self.auth_policy_path or self.config_file("auth-policy.v1.json")
        policy: dict = {}
        if path and path.is_file():
            try:
                policy = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                policy = {}

        policy.setdefault("version", "1.0.0")
        policy.setdefault("auth_mode", self.auth_mode)
        policy.setdefault("default_role", "operator")
        return policy
