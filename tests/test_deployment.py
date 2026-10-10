"""Implementation bundles must fail safely before runtime data is created."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import call

from xtract.api.app import create_app
from xtract.cli import main
from xtract.config import PlatformConfig
from xtract.core import Platform
from xtract.deployment import (
    DeploymentError,
    initialize,
    load_config,
    preflight,
    read_json,
    validate_bundle,
    write_json,
)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(
            os.environ,
            {k: v for k, v in os.environ.items() if not k.startswith("XTRACT_")},
            clear=True,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root = (Path(self.tmp.name) / "city").resolve()
        initialize(self.root, "city-demo", "City Demo", "it-pa", "it")

    def test_bundle_loads_identity_rules_and_private_paths(self):
        cfg = load_config(self.root)
        self.assertEqual(cfg.default_institution, "city-demo")
        self.assertEqual(cfg.get_institution_profile()["institution_name"], "City Demo")
        self.assertEqual(cfg.get_institution_profile()["default_locale"], "it")
        self.assertEqual(cfg.get_auth_policy()["auth_mode"], "jwt")
        self.assertEqual(cfg.database_path, str(self.root / "data/xtract.db"))
        self.assertEqual(cfg.allowed_offices, ("general",))
        self.assertEqual(
            cfg.config_file("field-taxonomy.v1.json"), self.root / "config/field-taxonomy.v1.json"
        )
        self.assertFalse((self.root / "data").exists())

    def test_existing_installation_is_never_overwritten(self):
        before = (self.root / "deployment.json").read_bytes()
        with self.assertRaises(DeploymentError):
            initialize(self.root, "other", "Other Institution")
        self.assertEqual((self.root / "deployment.json").read_bytes(), before)

    def test_incomplete_and_inconsistent_bundles_are_rejected(self):
        path = self.root / "config/institution-profile.v1.json"
        original = read_json(path)
        write_json(path, {**original, "institution_id": "other"})
        with self.assertRaises(DeploymentError):
            load_config(self.root)
        write_json(path, original)
        path.unlink()
        with self.assertRaises(DeploymentError):
            load_config(self.root)
        self.assertFalse((self.root / "data").exists())

    def test_invalid_offices_regex_and_connector_references_are_rejected(self):
        manifest = read_json(self.root / "deployment.json")
        manifest["offices"][0]["enabled"] = False
        write_json(self.root / "deployment.json", manifest)
        with self.assertRaisesRegex(DeploymentError, "Default office"):
            validate_bundle(self.root)
        manifest["offices"][0]["enabled"] = True
        write_json(self.root / "deployment.json", manifest)
        path = self.root / "config/alias-dictionary.v1.json"
        aliases = read_json(path)
        original = aliases["aliases"][0]["value_regex"]
        aliases["aliases"][0]["value_regex"] = "["
        write_json(path, aliases)
        with self.assertRaisesRegex(DeploymentError, "regular expression"):
            validate_bundle(self.root)
        aliases["aliases"][0]["value_regex"] = original
        write_json(path, aliases)
        path = self.root / "config/integration-policy.v1.json"
        integration = read_json(path)
        integration["routes"][0]["target_connector_id"] = "missing"
        write_json(path, integration)
        with self.assertRaisesRegex(DeploymentError, "unknown connector"):
            validate_bundle(self.root)

    def test_doctor_and_startup_require_credentials_without_creating_data(self):
        cfg = load_config(self.root)
        self.assertFalse(preflight(cfg)["ready_to_start"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--deployment", str(self.root), "serve"]), 1)
        self.assertFalse((self.root / "data").exists())
        cfg.jwt_secret = "private-signing-secret-for-implementation-test"
        result = preflight(cfg)
        self.assertTrue(result["ready_to_start"])
        self.assertNotIn(cfg.jwt_secret, json.dumps(result))

    def test_cli_validation_and_separate_installations(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--deployment", str(self.root), "validate-config"]), 0)
        self.assertIn("city-demo", output.getvalue())
        other = Path(self.tmp.name) / "other"
        initialize(other, "other", "Other Institution")
        self.assertNotEqual(load_config(other).database_path, load_config(self.root).database_path)

    def test_disabled_or_unknown_offices_cannot_receive_uploads(self):
        cfg = load_config(self.root)
        cfg.jwt_secret = "test-signing-secret"
        platform = Platform(cfg)
        token = platform.auth.create_token("operator")
        app = create_app(platform)
        headers = {"Authorization": f"Bearer {token}"}
        body = {
            "filename": "request.txt",
            "text_content": "Institution request",
            "office_id": "missing",
        }
        self.assertEqual(call(app, "POST", "/api/v1/documents", body, headers)[0], 422)
        body.pop("office_id")
        status, _, document = call(app, "POST", "/api/v1/documents", body, headers)
        self.assertEqual(status, 201)
        self.assertEqual(platform.db.get_document(document["document_id"])["office_id"], "general")

    def test_custom_root_overrides_bundled_pack(self):
        cfg = PlatformConfig(config_dir=self.root / "config", config_pack="general")
        self.assertEqual(
            cfg.config_file("institution-profile.v1.json"),
            self.root / "config/institution-profile.v1.json",
        )

    def test_deployment_uses_exactly_the_validated_files(self):
        extra = self.root / "config/presets/it-pa"
        extra.mkdir(parents=True)
        (extra / "field-taxonomy.v1.json").write_text("{}", "utf-8")
        cfg = load_config(self.root)
        self.assertEqual(cfg.deployment_pack, "it-pa")
        self.assertEqual(
            cfg.config_file("field-taxonomy.v1.json"), self.root / "config/field-taxonomy.v1.json"
        )

    def test_environment_cannot_change_deployment_identity(self):
        with patch.dict(os.environ, {"XTRACT_INSTITUTION_ID": "foreign"}):
            with self.assertRaisesRegex(DeploymentError, "conflicts"):
                load_config(self.root)

    def test_invalid_setup_is_atomic(self):
        target = Path(self.tmp.name) / "invalid"
        with self.assertRaises(DeploymentError):
            initialize(target, "../escape", "Invalid")
        self.assertFalse(target.exists())

    def test_remote_route_without_endpoint_blocks_startup(self):
        path = self.root / "config/integration-policy.v1.json"
        policy = read_json(path)
        policy["routes"][0]["target_connector_id"] = "agid_protocollo_hub"
        write_json(path, policy)
        cfg = load_config(self.root)
        cfg.jwt_secret = "secure-test-signing-secret-for-implementation"
        report = preflight(cfg)
        self.assertFalse(report["ready_to_start"])
        self.assertTrue(any("HTTPS endpoint" in error for error in report["errors"]))

    def test_server_side_user_provisioning_is_scoped_and_requires_credentials(self):
        args = [
            "--deployment",
            str(self.root),
            "issue-token",
            "--user",
            "records-admin",
            "--role",
            "admin",
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 1)
        with patch.dict(
            os.environ, {"XTRACT_JWT_SECRET": "secure-test-signing-key-for-user-provisioning"}
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(args), 0)
            from xtract.auth.jwt import decode_jwt

            payload = decode_jwt(output.getvalue().strip(), secret=os.environ["XTRACT_JWT_SECRET"])
            self.assertEqual(payload["institution_id"], "city-demo")
            self.assertEqual(payload["roles"], ["admin"])
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args + ["--office", "missing"]), 1)
        self.assertFalse((self.root / "data").exists())
