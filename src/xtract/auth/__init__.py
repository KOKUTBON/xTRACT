"""Institutional identity federation (OIDC / SAML2 / JWT) and RBAC for xTRACT."""

from xtract.auth.jwt import (
    JwtError,
    JwtExpiredError,
    JwtFormatError,
    JwtSignatureError,
    create_jwt,
    decode_jwt,
)
from xtract.auth.models import ALL_PERMISSIONS, ROLE_PERMISSIONS, AuthUser
from xtract.auth.service import AuthService

__all__ = [
    "ALL_PERMISSIONS",
    "AuthService",
    "AuthUser",
    "JwtError",
    "JwtExpiredError",
    "JwtFormatError",
    "JwtSignatureError",
    "ROLE_PERMISSIONS",
    "create_jwt",
    "decode_jwt",
]
