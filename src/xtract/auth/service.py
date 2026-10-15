"""Authentication service: resolves operator identities and handles JWT, token, and proxy federation."""

from __future__ import annotations

import hmac
import logging
from typing import TYPE_CHECKING

from xtract.auth.jwt import (
    JwtError,
    create_jwt,
    decode_jwt,
)
from xtract.auth.models import ALL_PERMISSIONS, ROLE_PERMISSIONS, AuthUser

if TYPE_CHECKING:
    from xtract.config import PlatformConfig

logger = logging.getLogger("xtract.auth")


class AuthService:
    """Manages authentication, identity federation, and RBAC authorization."""

    def __init__(self, config: PlatformConfig) -> None:
        self.config = config
        self.policy = config.get_auth_policy()

    @property
    def auth_mode(self) -> str:
        return (
            self.config.auth_mode
            if self.config.auth_mode != "auto"
            else self.policy.get("auth_mode", "auto")
        )

    @property
    def trust_proxy(self) -> bool:
        return bool(
            self.config.trust_forwarded_headers
            or self.auth_mode == "header"
            or self.policy.get("header_federation", {}).get("enabled", False)
        )

    @property
    def auth_required(self) -> bool:
        return bool(
            self.config.api_token
            or self.config.jwt_secret
            or self.trust_proxy
            or self.config.oidc_issuer_url
            or self.policy.get("oidc", {}).get("issuer_url")
            or self.auth_mode not in ("none", "auto")
        )

    def create_token(
        self,
        user_id: str,
        display_name: str | None = None,
        email: str = "",
        roles: list[str] | None = None,
        institution_id: str | None = None,
        office_id: str | None = None,
        expires_in: int = 86400,
    ) -> str:
        """Create a signed JWT token for an operator (useful for testing or local issuance)."""
        secret = self.config.jwt_secret or self.config.api_token
        if not secret:
            raise JwtError("Configure a signing secret before issuing tokens.")
        payload = {
            "sub": user_id,
            "name": display_name or user_id,
            "email": email,
            "roles": roles or ["operator"],
            "institution_id": institution_id or self.config.default_institution,
            "office_id": office_id or self.config.default_office,
        }
        if self.config.jwt_issuer:
            payload["iss"] = self.config.jwt_issuer
        if self.config.jwt_audience:
            payload["aud"] = self.config.jwt_audience
        return create_jwt(
            payload,
            secret=secret,
            algorithm=self.config.jwt_algorithm,
            expires_in=expires_in,
        )

    def authenticate(self, req) -> AuthUser | None:
        """Authenticate an incoming Request and return AuthUser context, or None if rejected."""
        # 1. Bearer Header (JWT or static API token)
        auth_header = req.header("Authorization")
        if auth_header:
            if not auth_header.lower().startswith("bearer "):
                return None
            token = auth_header[7:].strip()
            if not token:
                return None
            # Match configured shared credentials before interpreting JWT syntax.
            if self.config.api_token and hmac.compare_digest(
                token.encode(), self.config.api_token.encode()
            ):
                actor = req.actor if req.actor != "operator" else "admin"
                return AuthUser(
                    user_id=actor,
                    display_name=actor,
                    institution_id=self.config.default_institution,
                    office_id=self.config.default_office,
                    roles=["admin"],
                    auth_method="token",
                )
            # If token is JWT formatted (header.payload.signature)
            if token.count(".") == 2:
                secret = self.config.jwt_secret or self.config.api_token or ""
                try:
                    payload = decode_jwt(
                        token,
                        secret=secret,
                        algorithm=self.config.jwt_algorithm,
                        verify_signature=True,
                        expected_issuer=self.config.jwt_issuer or None,
                        expected_audience=self.config.jwt_audience or None,
                    )
                    user_id = str(payload.get("sub") or payload.get("preferred_username") or "user")
                    display_name = str(
                        payload.get("name") or payload.get("preferred_username") or user_id
                    )
                    email = str(payload.get("email", ""))
                    institution_id = str(
                        payload.get("institution_id") or self.config.default_institution
                    )
                    office_id = str(payload.get("office_id") or self.config.default_office)
                    roles = self._extract_roles(payload)
                    return AuthUser(
                        user_id=user_id,
                        display_name=display_name,
                        email=email,
                        institution_id=institution_id,
                        office_id=office_id,
                        roles=roles,
                        auth_method="jwt",
                    )
                except JwtError as exc:
                    logger.warning("JWT validation failed: %s", exc)
                    return None

            return None

        # 2. Reverse Proxy / Gateway Header Federation (SAML2/OIDC proxy gateway)
        if self.trust_proxy:
            fed_cfg = self.policy.get("header_federation", {})
            user_hdr = fed_cfg.get("user_header", "X-Forwarded-User")
            user_val = req.header(user_hdr) or req.header("X-Remote-User")
            if user_val.strip():
                user_id = user_val.strip()
                email_hdr = fed_cfg.get("email_header", "X-Forwarded-Email")
                email = req.header(email_hdr).strip()
                roles_hdr = fed_cfg.get("roles_header", "X-Forwarded-Roles")
                roles_raw = req.header(roles_hdr).strip()
                roles = (
                    [r.strip().lower() for r in roles_raw.split(",") if r.strip()]
                    if roles_raw
                    else [self.policy.get("default_role", "operator")]
                )
                inst_hdr = fed_cfg.get("institution_header", "X-Forwarded-Institution")
                inst = req.header(inst_hdr).strip() or self.config.default_institution
                office = req.header("X-Forwarded-Office").strip() or self.config.default_office
                return AuthUser(
                    user_id=user_id,
                    display_name=user_id,
                    email=email,
                    institution_id=inst,
                    office_id=office,
                    roles=roles,
                    auth_method="header",
                )

        # 3. Unauthenticated / Fallback Mode
        if self.auth_required:
            # Token is required but none or invalid was provided
            return None

        # Development / single-user mode (full privileges, actor from X-Operator-Id)
        actor = req.actor
        return AuthUser(
            user_id=actor,
            display_name=actor,
            institution_id=self.config.default_institution,
            office_id=self.config.default_office,
            roles=["admin"],
            auth_method="anonymous",
        )

    def _extract_roles(self, payload: dict) -> list[str]:
        """Extract roles from standard OIDC claims (roles, realm_access, groups)."""
        roles_claim = self.policy.get("oidc", {}).get("roles_claim", "roles")
        if roles_claim in payload and isinstance(payload[roles_claim], list):
            return [str(r).lower() for r in payload[roles_claim]]
        if "roles" in payload and isinstance(payload["roles"], list):
            return [str(r).lower() for r in payload["roles"]]
        if "groups" in payload and isinstance(payload["groups"], list):
            return [str(r).lower() for r in payload["groups"]]
        if "realm_access" in payload and isinstance(payload["realm_access"], dict):
            realm_roles = payload["realm_access"].get("roles", [])
            if isinstance(realm_roles, list):
                return [str(r).lower() for r in realm_roles]
        return [self.policy.get("default_role", "operator")]

    def get_auth_config(self) -> dict:
        """Public authentication metadata for frontends and clients."""
        return {
            "auth_required": self.auth_required,
            "auth_mode": self.auth_mode,
            "oidc_issuer_url": self.config.oidc_issuer_url,
            "oidc_client_id": self.config.oidc_client_id,
            "available_roles": list(ROLE_PERMISSIONS.keys()),
            "available_permissions": sorted(ALL_PERMISSIONS),
        }
