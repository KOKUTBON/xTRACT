import json
import unittest

from helpers import ROOT, SCHEMA_FILES, schema_errors
from jsonschema import Draft202012Validator

CONFIG_SCHEMAS = {
    "field-taxonomy.v1.json": "field-taxonomy.v1.schema.json",
    "alias-dictionary.v1.json": "alias-dictionary.v1.schema.json",
    "extraction-policy.v1.json": "extraction-policy.v1.schema.json",
    "ocr-routing-policy.v1.json": "ocr-routing-policy.v1.schema.json",
    "connector-catalog.v1.json": "connector-catalog.v1.schema.json",
    "integration-policy.v1.json": "integration-policy.v1.schema.json",
    "institution-profile.v1.json": "institution-profile.v1.schema.json",
    "auth-policy.v1.json": "auth-policy.v1.schema.json",
}
LIFECYCLE_SCHEMAS = {
    "document-lifecycle.v1.json": "document-lifecycle.v1.schema.json",
    "audit-event-catalog.v1.json": "audit-event-catalog.v1.schema.json",
    "document-exception-taxonomy.v1.json": "document-exception-taxonomy.v1.schema.json",
}


def load(path):
    return json.loads(path.read_text("utf-8"))


class ContractTests(unittest.TestCase):
    def test_every_schema_is_a_valid_draft_2020_12_schema(self):
        self.assertTrue(SCHEMA_FILES)
        for path in SCHEMA_FILES:
            with self.subTest(schema=path.name):
                Draft202012Validator.check_schema(load(path))

    def test_default_configuration_matches_its_schemas(self):
        for config_name, schema_name in CONFIG_SCHEMAS.items():
            with self.subTest(config=config_name):
                payload = load(ROOT / "config" / config_name)
                self.assertEqual(schema_errors(schema_name, payload), [])

    def test_lifecycle_catalogs_match_their_schemas(self):
        for name, schema_name in LIFECYCLE_SCHEMAS.items():
            with self.subTest(catalog=name):
                payload = load(ROOT / "src" / "xtract" / "contracts" / "lifecycle" / name)
                self.assertEqual(schema_errors(schema_name, payload), [])

    def test_aliases_reference_known_fields_and_compile(self):
        import re

        taxonomy = load(ROOT / "config" / "field-taxonomy.v1.json")
        fields = {
            (t["family_code"], t["type_code"], f["field_code"])
            for t in taxonomy["document_types"]
            for f in t["fields"]
        }
        for alias in load(ROOT / "config" / "alias-dictionary.v1.json")["aliases"]:
            key = (alias["document_family"], alias["document_type"], alias["field_code"])
            self.assertIn(key, fields, alias["alias_text"])
            re.compile(alias["value_regex"])

    def test_integration_routes_target_catalog_connectors(self):
        catalog = {
            c["connector_id"]
            for c in load(ROOT / "config" / "connector-catalog.v1.json")["connectors"]
        }
        for route in load(ROOT / "config" / "integration-policy.v1.json")["routes"]:
            self.assertIn(route["target_connector_id"], catalog)

    def test_preset_pack_manifests_match_schema(self):
        preset_dirs = [
            ROOT / "src" / "xtract" / "presets",
            ROOT / "config" / "presets",
        ]
        for base in preset_dirs:
            if not base.is_dir():
                continue
            for pack_dir in base.iterdir():
                if pack_dir.is_dir() and not pack_dir.name.startswith("."):
                    manifest = pack_dir / "manifest.json"
                    if manifest.is_file():
                        with self.subTest(pack=pack_dir.name, path=str(manifest)):
                            self.assertEqual(
                                schema_errors("domain-pack.v1.schema.json", load(manifest)), []
                            )

    def test_preset_configurations_match_their_schemas(self):
        preset_dirs = [
            ROOT / "src" / "xtract" / "presets",
            ROOT / "config" / "presets",
        ]
        for base in preset_dirs:
            if not base.is_dir():
                continue
            for pack_dir in base.iterdir():
                if pack_dir.is_dir() and not pack_dir.name.startswith("."):
                    for config_name, schema_name in CONFIG_SCHEMAS.items():
                        cfg_file = pack_dir / config_name
                        if cfg_file.is_file():
                            with self.subTest(pack=pack_dir.name, config=config_name):
                                self.assertEqual(schema_errors(schema_name, load(cfg_file)), [])

    def test_preset_aliases_reference_known_fields_and_compile(self):
        import re

        preset_dirs = [
            ROOT / "src" / "xtract" / "presets",
            ROOT / "config" / "presets",
        ]
        for base in preset_dirs:
            if not base.is_dir():
                continue
            for pack_dir in base.iterdir():
                if not pack_dir.is_dir() or pack_dir.name.startswith("."):
                    continue
                tax_file = pack_dir / "field-taxonomy.v1.json"
                alias_file = pack_dir / "alias-dictionary.v1.json"
                if tax_file.is_file() and alias_file.is_file():
                    taxonomy = load(tax_file)
                    fields = {
                        (t["family_code"], t["type_code"], f["field_code"])
                        for t in taxonomy["document_types"]
                        for f in t["fields"]
                    }
                    for alias in load(alias_file)["aliases"]:
                        key = (
                            alias["document_family"],
                            alias["document_type"],
                            alias["field_code"],
                        )
                        self.assertIn(key, fields, f"{pack_dir.name}: {alias['alias_text']}")
                        re.compile(alias["value_regex"])


if __name__ == "__main__":
    unittest.main()
