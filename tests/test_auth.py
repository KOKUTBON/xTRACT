"""Tests for sovereign identity, JWT tokens, and RBAC authentication."""

from __future__ import annotations

import unittest

from xtract.auth.jwt import (
    JwtError,
    create_jwt,
    decode_jwt,
)
from xtract.auth.models import (
    ROLE_PERMISSIONS,
    AuthUser,
)
from xtract.auth.service import AuthService
from xtract.config import PlatformConfig


class DummyRequest:
    """Mock HTTP request for auth testing."""

    def __init__(self, headers: dict[str, str] | None = None, actor: str = "operator") -> None:
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self._actor = actor

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")

    @property
    def actor(self) -> str:
        return self._actor


class TestJwt(unittest.TestCase):
    """Test sovereign HMAC-SHA256 JWT encoding and decoding."""

    def test_jwt_encode_decode_roundtrip(self) -> None:
        payload = {"sub": "user123", "name": "Mario Rossi", "roles": ["operator"]}
        secret = "super-secret-key-12345"
        token = create_jwt(payload, secret=secret, expires_in=3600)
        self.assertEqual(token.count("."), 2)

        decoded = decode_jwt(token, secret=secret)
        self.assertEqual(decoded["sub"], "user123")
        self.assertEqual(decoded["name"], "Mario Rossi")
        self.assertEqual(decoded["roles"], ["operator"])
        self.assertIn("exp", decoded)
        self.assertIn("iat", decoded)

    def test_jwt_invalid_signature_rejected(self) -> None:
        token = create_jwt({"sub": "user1"}, secret="correct-secret")
        with self.assertRaises(JwtError) as ctx:
            decode_jwt(token, secret="wrong-secret")
        self.assertIn("signature", str(ctx.exception).lower())

    def test_jwt_expired_token_rejected(self) -> None:
        token = create_jwt({"sub": "user1"}, secret="key", expires_in=-60)
        with self.assertRaises(JwtError) as ctx:
            decode_jwt(token, secret="key", clock_skew_seconds=0)
        self.assertIn("expired", str(ctx.exception).lower())

    def test_jwt_issuer_and_audience_validation(self) -> None:
        token = create_jwt(
            {"sub": "user1", "iss": "https://id.gov.it", "aud": "xtract-api"},
            secret="key",
        )
        # Matching issuer & audience
        decoded = decode_jwt(
            token,
            secret="key",
            expected_issuer="https://id.gov.it",
            expected_audience="xtract-api",
        )
        self.assertEqual(decoded["sub"], "user1")

        # Wrong issuer
        with self.assertRaises(JwtError):
            decode_jwt(token, secret="key", expected_issuer="https://other.gov.it")

        # Wrong audience
        with self.assertRaises(JwtError):
            decode_jwt(token, secret="key", expected_audience="other-audience")


class TestAuthModels(unittest.TestCase):
    """Test RBAC role permissions and AuthUser behaviors."""

    def test_role_permissions_mapping(self) -> None:
        self.assertIn("admin:manage", ROLE_PERMISSIONS["admin"])
        self.assertNotIn("admin:manage", ROLE_PERMISSIONS["supervisor"])
        self.assertIn("doc:discard", ROLE_PERMISSIONS["supervisor"])
        self.assertNotIn("doc:discard", ROLE_PERMISSIONS["operator"])
        self.assertIn("doc:approve", ROLE_PERMISSIONS["operator"])
        self.assertNotIn("doc:approve", ROLE_PERMISSIONS["viewer"])
        self.assertIn("doc:read", ROLE_PERMISSIONS["viewer"])

    def test_auth_user_admin_bypass(self) -> None:
        admin_user = AuthUser(user_id="adm", display_name="Admin", roles=["admin"])
        self.assertTrue(admin_user.has_permission("doc:read"))
        self.assertTrue(admin_user.has_permission("admin:manage"))
        self.assertTrue(admin_user.has_permission("non_existent_perm"))

    def test_auth_user_viewer_permissions(self) -> None:
        viewer = AuthUser(user_id="view1", display_name="Viewer", roles=["viewer"])
        self.assertTrue(viewer.has_permission("doc:read"))
        self.assertTrue(viewer.has_permission("export:read"))
        self.assertFalse(viewer.has_permission("field:edit"))
        self.assertFalse(viewer.has_permission("doc:approve"))
        self.assertFalse(viewer.has_permission("doc:discard"))

    def test_auth_user_multi_role_union(self) -> None:
        user = AuthUser(user_id="u1", display_name="User", roles=["viewer", "operator"])
        self.assertTrue(user.has_permission("doc:read"))
        self.assertTrue(user.has_permission("field:edit"))
        self.assertTrue(user.has_permission("doc:approve"))
        self.assertFalse(user.has_permission("doc:discard"))


class TestAuthService(unittest.TestCase):
    """Test identity resolution across JWT, static token, and proxy headers."""

    def setUp(self) -> None:
        self.cfg = PlatformConfig(
            api_token="test-api-secret",
            jwt_secret="jwt-secret-xyz",
            default_institution="it-comune-demo",
            default_office="protocollo",
        )
        self.service = AuthService(self.cfg)

    def test_jwt_authentication(self) -> None:
        token = self.service.create_token(
            user_id="mrossi",
            display_name="Mario Rossi",
            email="mario@example.it",
            roles=["operator"],
        )
        req = DummyRequest(headers={"Authorization": f"Bearer {token}"})
        user = self.service.authenticate(req)
        self.assertIsNotNone(user)
        self.assertEqual(user.user_id, "mrossi")
        self.assertEqual(user.display_name, "Mario Rossi")
        self.assertEqual(user.roles, ["operator"])
        self.assertEqual(user.auth_method, "jwt")
        self.assertTrue(user.has_permission("doc:approve"))
        self.assertFalse(user.has_permission("doc:discard"))

    def test_static_token_authentication(self) -> None:
        req = DummyRequest(
            headers={"Authorization": "Bearer test-api-secret"},
            actor="admin-actor",
        )
        user = self.service.authenticate(req)
        self.assertIsNotNone(user)
        self.assertEqual(user.roles, ["admin"])
        self.assertEqual(user.auth_method, "token")
        self.assertTrue(user.has_permission("admin:manage"))

    def test_invalid_bearer_token(self) -> None:
        req = DummyRequest(headers={"Authorization": "Bearer invalid-token"})
        user = self.service.authenticate(req)
        self.assertIsNone(user)

    def test_reverse_proxy_header_federation_when_trusted(self) -> None:
        trusted_cfg = PlatformConfig(
            trust_forwarded_headers=True,
            default_institution="it-comune-demo",
        )
        service = AuthService(trusted_cfg)
        req = DummyRequest(
            headers={
                "X-Forwarded-User": "giulia.bianchi",
                "X-Forwarded-Email": "giulia@comune.example.it",
                "X-Forwarded-Roles": "supervisor,auditor",
                "X-Forwarded-Institution": "prefettura-mi",
            }
        )
        user = service.authenticate(req)
        self.assertIsNotNone(user)
        self.assertEqual(user.user_id, "giulia.bianchi")
        self.assertEqual(user.email, "giulia@comune.example.it")
        self.assertEqual(user.roles, ["supervisor", "auditor"])
        self.assertEqual(user.institution_id, "prefettura-mi")
        self.assertEqual(user.auth_method, "header")
        self.assertTrue(user.has_permission("doc:discard"))

    def test_reverse_proxy_header_ignored_when_untrusted(self) -> None:
        untrusted_cfg = PlatformConfig(
            api_token="secret",
            trust_forwarded_headers=False,
        )
        service = AuthService(untrusted_cfg)
        req = DummyRequest(headers={"X-Forwarded-User": "untrusted-user"})
        user = service.authenticate(req)
        self.assertIsNone(user)

    def test_anonymous_dev_fallback(self) -> None:
        dev_cfg = PlatformConfig(api_token="")
        service = AuthService(dev_cfg)
        req = DummyRequest(actor="dev-user")
        user = service.authenticate(req)
        self.assertIsNotNone(user)
        self.assertEqual(user.user_id, "dev-user")
        self.assertEqual(user.roles, ["admin"])
        self.assertEqual(user.auth_method, "anonymous")

    def test_protected_configurations_never_fall_back_to_anonymous(self):
        configurations = [
            {"auth_mode": mode} for mode in ("jwt", "token", "oidc", "header", "unknown")
        ] + [
            {"jwt_secret": "signing-secret"},
            {"trust_forwarded_headers": True},
            {"oidc_issuer_url": "https://identity.example.test"},
        ]
        for settings in configurations:
            with self.subTest(settings=settings):
                service = AuthService(PlatformConfig(api_token="", **settings))
                self.assertTrue(service.get_auth_config()["auth_required"])
                self.assertIsNone(service.authenticate(DummyRequest()))

    def test_policy_requires_authentication(self):
        for policy in (
            {"auth_mode": "jwt"},
            {"header_federation": {"enabled": True}},
            {"oidc": {"issuer_url": "https://identity.example.test"}},
        ):
            with self.subTest(policy=policy):
                service = AuthService(PlatformConfig(api_token="", jwt_secret=""))
                service.policy = policy
                self.assertTrue(service.auth_required)
                self.assertIsNone(service.authenticate(DummyRequest()))

    def test_unverified_credentials_rejected_even_in_development(self):
        service = AuthService(PlatformConfig(api_token="", jwt_secret=""))
        forged = create_jwt({"sub": "attacker", "roles": ["admin"]}, "attacker-key")
        for authorization in ("Bearer arbitrary", "Bearer ", "Basic arbitrary", f"Bearer {forged}"):
            with self.subTest(authorization=authorization):
                self.assertIsNone(
                    service.authenticate(DummyRequest({"Authorization": authorization}))
                )
        with self.assertRaises(JwtError):
            service.create_token("admin", roles=["admin"])

    def test_jwt_only_accepts_verified_tokens(self):
        service = AuthService(
            PlatformConfig(api_token="", jwt_secret="test-signing-key", auth_mode="jwt")
        )
        valid = service.create_token("operator", roles=["operator"])
        forged = create_jwt({"sub": "attacker", "roles": ["admin"]}, "wrong-key")
        self.assertEqual(
            service.authenticate(DummyRequest({"Authorization": f"Bearer {valid}"})).roles,
            ["operator"],
        )
        self.assertIsNone(service.authenticate(DummyRequest({"Authorization": f"Bearer {forged}"})))

    def test_dotted_shared_token_is_verified(self):
        service = AuthService(PlatformConfig(api_token="shared.token.value"))
        user = service.authenticate(DummyRequest({"Authorization": "Bearer shared.token.value"}))
        self.assertEqual(user.auth_method, "token")

    def test_oidc_claim_roles_extraction(self) -> None:
        # Standard OIDC realm_access claim
        keycloak_payload = {
            "sub": "user-kc",
            "realm_access": {"roles": ["viewer", "default-roles"]},
        }
        roles = self.service._extract_roles(keycloak_payload)
        self.assertEqual(roles, ["viewer", "default-roles"])

        # Groups claim
        adfs_payload = {"sub": "user-ad", "groups": ["operator"]}
        roles2 = self.service._extract_roles(adfs_payload)
        self.assertEqual(roles2, ["operator"])


if __name__ == "__main__":
    unittest.main()
