"""JSON Schema contracts and lifecycle definitions for xTRACT."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACTS_DIR = Path(__file__).resolve().parent
SCHEMAS_DIR = CONTRACTS_DIR / "schemas"
LIFECYCLE_DIR = CONTRACTS_DIR / "lifecycle"

_SCHEMAS: dict[str, dict] = {}
_REGISTRY: Registry | None = None


def get_schemas() -> dict[str, dict]:
    global _SCHEMAS
    if not _SCHEMAS:
        for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
            _SCHEMAS[path.name] = json.loads(path.read_text("utf-8"))
    return _SCHEMAS


def get_registry() -> Registry:
    global _REGISTRY
    if _REGISTRY is None:
        schemas = get_schemas()
        _REGISTRY = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
        )
    return _REGISTRY


def validate_contract(schema_name: str, payload: dict | list) -> list[str]:
    """Validate a payload against a registered schema and return error messages."""
    schemas = get_schemas()
    if schema_name not in schemas:
        raise KeyError(f"Unknown contract schema: {schema_name}")
    validator = Draft202012Validator(schemas[schema_name], registry=get_registry())
    return [f"{list(e.absolute_path)}: {e.message}" for e in validator.iter_errors(payload)]


def load_lifecycle_catalog(catalog_name: str) -> dict:
    target = LIFECYCLE_DIR / catalog_name
    if not target.is_file():
        raise FileNotFoundError(f"Lifecycle catalog not found: {catalog_name}")
    return json.loads(target.read_text("utf-8"))
