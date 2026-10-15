"""Sovereign local JSON Web Token (JWT) encode and decode utilities."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class JwtError(Exception):
    """Base exception for JWT processing errors."""


class JwtFormatError(JwtError):
    """Malformed token structure or claims."""


class JwtSignatureError(JwtError):
    """Signature mismatch or unsupported algorithm."""


class JwtExpiredError(JwtError):
    """Token has expired."""


def base64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def base64url_decode(value: str) -> bytes:
    """Base64url decode with padding compensation."""
    rem = len(value) % 4
    if rem > 0:
        value += "=" * (4 - rem)
    return base64.urlsafe_b64decode(value.encode("utf-8"))


def create_jwt(
    payload: dict,
    secret: str,
    algorithm: str = "HS256",
    expires_in: int = 3600,
) -> str:
    """Create a signed JWT token using HMAC-SHA256."""
    now = int(time.time())
    data = dict(payload)
    if "iat" not in data:
        data["iat"] = now
    if "exp" not in data and expires_in is not None and expires_in != 0:
        data["exp"] = now + expires_in

    header = {"alg": algorithm, "typ": "JWT"}
    header_json = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_json = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")

    header_b64 = base64url_encode(header_json)
    payload_b64 = base64url_encode(payload_json)
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    if algorithm == "HS256":
        sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    else:
        raise JwtSignatureError(f"Unsupported algorithm: {algorithm}")

    sig_b64 = base64url_encode(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_jwt(
    token: str,
    secret: str | None = None,
    algorithm: str = "HS256",
    verify_signature: bool = True,
    expected_issuer: str | None = None,
    expected_audience: str | None = None,
    clock_skew_seconds: int = 30,
) -> dict:
    """Decode and validate a JWT token."""
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise JwtFormatError("Invalid token format (expected header.payload.signature)")

    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(base64url_decode(header_b64).decode("utf-8"))
        payload = json.loads(base64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise JwtFormatError(f"Failed to decode token JSON: {exc}") from exc

    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise JwtFormatError("Token header and payload must be JSON objects")

    if verify_signature:
        if not secret:
            raise JwtSignatureError("JWT secret required for signature verification")
        if header.get("alg") != algorithm:
            raise JwtSignatureError(
                f"Algorithm mismatch: token specified {header.get('alg')}, expected {algorithm}"
            )
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        if algorithm == "HS256":
            expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        else:
            raise JwtSignatureError(f"Unsupported algorithm: {algorithm}")
        try:
            provided_sig = base64url_decode(sig_b64)
        except Exception as exc:
            raise JwtSignatureError("Malformed signature encoding") from exc

        if not hmac.compare_digest(expected_sig, provided_sig):
            raise JwtSignatureError("Invalid token signature")

    now = int(time.time())
    if "exp" in payload:
        try:
            exp = int(payload["exp"])
            if now > exp + clock_skew_seconds:
                raise JwtExpiredError(f"Token expired at {exp} (current time {now})")
        except ValueError as exc:
            raise JwtFormatError("Invalid exp claim") from exc

    if "nbf" in payload:
        try:
            nbf = int(payload["nbf"])
            if now < nbf - clock_skew_seconds:
                raise JwtFormatError(f"Token not active before {nbf}")
        except ValueError as exc:
            raise JwtFormatError("Invalid nbf claim") from exc

    if expected_issuer and payload.get("iss") != expected_issuer:
        raise JwtFormatError(
            f"Issuer mismatch: expected {expected_issuer}, got {payload.get('iss')}"
        )

    if expected_audience:
        aud = payload.get("aud")
        if isinstance(aud, list):
            if expected_audience not in aud:
                raise JwtFormatError(f"Audience {expected_audience} not in token audiences {aud}")
        elif aud != expected_audience:
            raise JwtFormatError(f"Audience mismatch: expected {expected_audience}, got {aud}")

    return payload
