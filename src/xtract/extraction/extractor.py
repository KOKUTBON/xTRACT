from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

from xtract.extraction.normalizers import (
    apply_normalization,
    normalize_text,
    now_utc,
    text_lines,
)

logger = logging.getLogger("metadata-extractor")

AUTO_FAMILY = "auto"


def _load(source: dict | Path) -> dict:
    return json.loads(source.read_text(encoding="utf-8")) if isinstance(source, Path) else source


class MetadataExtractor:
    """Hybrid metadata extraction using alias anchors, regex patterns, and OCR confidence."""

    def __init__(
        self,
        alias_dictionary: dict | Path,
        field_taxonomy: dict | Path,
        extraction_policy: dict | Path,
        auto_approve_threshold: float | None = None,
        manual_review_threshold: float | None = None,
    ) -> None:
        self.alias_dictionary = _load(alias_dictionary)
        self.field_taxonomy = _load(field_taxonomy)
        self.policy = _load(extraction_policy)
        thresholds = self.policy.get("global_thresholds", {})
        self.auto_approve_threshold = (
            auto_approve_threshold
            if auto_approve_threshold is not None
            else thresholds.get("auto_validate_threshold", 0.9)
        )
        self.manual_review_threshold = (
            manual_review_threshold
            if manual_review_threshold is not None
            else thresholds.get("review_threshold", 0.7)
        )
        self.date_order = self.policy.get("date_order", "DMY")

    # ------------------------------------------------------------------ taxonomy

    def document_types(self) -> list[dict]:
        return self.field_taxonomy.get("document_types", [])

    def default_family(self) -> str:
        default = self.policy.get("default_family")
        if default:
            return default
        types = self.document_types()
        return types[0]["family_code"] if types else "generic_document"

    def get_taxonomy_for_family(self, family_code: str) -> dict:
        for document_type in self.document_types():
            if document_type.get("family_code") == family_code:
                return document_type
        return {
            "type_code": "generic_document",
            "display_name": "Generic document",
            "family_code": family_code,
            "taxonomy_version": "1.0.0",
            "fields": [],
        }

    def get_aliases_for_type(self, family_code: str, type_code: str) -> list[dict]:
        return [
            alias
            for alias in self.alias_dictionary.get("aliases", [])
            if alias.get("active", True)
            and alias.get("document_family") == family_code
            and alias.get("document_type") == type_code
        ]

    def detect_family(self, full_text: str) -> tuple[str, float]:
        """Pick the family whose keyword rules best match the text."""
        lowered = normalize_text(full_text)
        best_family, best_hits = None, 0
        for rule in self.policy.get("document_type_keyword_rules", []):
            hits = 0
            for keyword in rule.get("keywords", []):
                pattern = r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)"
                if re.search(pattern, lowered):
                    hits += 1
            if hits > best_hits:
                best_family, best_hits = rule["family_code"], hits
        if best_family:
            return best_family, min(0.99, 0.7 + 0.1 * best_hits)
        return self.default_family(), 0.5

    def select_document_type(self, family_code: str, full_text: str, taxonomy: dict) -> dict:
        lowered = normalize_text(full_text)
        for rule in self.policy.get("document_type_keyword_rules", []):
            if rule.get("family_code") != family_code:
                continue
            if any(
                re.search(r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)", lowered)
                for keyword in rule.get("keywords", [])
            ):
                return {
                    "type_code": rule["type_code"],
                    "display_name": rule["display_name"],
                    "family_code": family_code,
                    "taxonomy_version": taxonomy.get("taxonomy_version", "1.0.0"),
                    "selection_source": "system_rule",
                    "confidence_score": 0.95,
                    "is_final": True,
                }
        return {
            "type_code": taxonomy.get("type_code", "generic_document"),
            "display_name": taxonomy.get("display_name", "Generic document"),
            "family_code": taxonomy.get("family_code", family_code),
            "taxonomy_version": taxonomy.get("taxonomy_version", "1.0.0"),
            "selection_source": "system_rule",
            "confidence_score": 0.6,
            "is_final": False,
        }

    # ------------------------------------------------------------------ scoring

    def build_strategy_trace(
        self,
        alias_matched: bool,
        regex_matched: bool,
        ocr_confidence: float | None,
        validation_penalty: float,
    ) -> list[dict]:
        trace = []
        for strategy in self.policy.get("strategy_stack", []):
            if not strategy.get("enabled", True):
                continue
            strategy_id = strategy.get("strategy_id")
            weight = strategy.get("weight", 0.0)
            status, contribution, note = "not_run", 0.0, ""
            if strategy_id == "alias_rule":
                status = "matched" if alias_matched else "not_matched"
                contribution = weight if alias_matched else 0.0
                note = "Alias anchor found." if alias_matched else "No alias anchor found."
            elif strategy_id == "regex_pattern":
                status = "matched" if regex_matched else "not_matched"
                contribution = weight if regex_matched else 0.0
                note = "Pattern extracted a value." if regex_matched else "Pattern did not match."
            elif strategy_id == "ocr_confidence_signal":
                status = "matched" if ocr_confidence is not None else "not_matched"
                contribution = round((ocr_confidence or 0.0) * weight, 4)
                note = "OCR line confidence blended into the field score."
            else:
                note = "Strategy declared by policy but not implemented."
            trace.append(
                {
                    "strategy_id": strategy_id,
                    "source_kind": strategy.get("source_kind", "rule_engine"),
                    "status": status,
                    "contribution": round(contribution, 4),
                    "note": note,
                }
            )
        if validation_penalty > 0:
            trace.append(
                {
                    "strategy_id": "validation_penalty",
                    "source_kind": "rule_engine",
                    "status": "validation_penalty",
                    "contribution": round(-validation_penalty, 4),
                    "note": "Value failed the field validation pattern.",
                }
            )
        return trace

    def _match_alias(self, alias: dict, lines: list[dict]) -> tuple[dict, str | None] | None:
        """Return the first line anchored by the alias, plus the regex value if any."""
        anchor = normalize_text(alias.get("alias_text", ""))
        pattern = alias.get("value_regex")
        regex = re.compile(pattern, re.IGNORECASE) if pattern else None
        first_anchor = None
        for index, line in enumerate(lines):
            if anchor and anchor not in normalize_text(line["text"]):
                continue
            first_anchor = first_anchor or line
            if not regex:
                return line, None
            candidates = [line["text"]]
            if index + 1 < len(lines):
                candidates.append(f"{line['text']} {lines[index + 1]['text']}")
            for candidate in candidates:
                match = regex.search(candidate)
                if match:
                    value = match.groupdict().get("value") or (
                        match.group(1)
                        if match.lastindex and match.lastindex >= 1
                        else match.group(0)
                    )
                    if value and value.strip():
                        return line, value.strip()
        return (first_anchor, None) if first_anchor else None

    def extract_field(
        self, field_definition: dict, field_aliases: list[dict], lines: list[dict]
    ) -> dict:
        penalty_weight = self.policy.get("global_thresholds", {}).get("validation_penalty", 0.25)
        review_threshold = field_definition.get("review_threshold", self.manual_review_threshold)
        required = field_definition.get("required", False)
        best = None

        for alias in field_aliases:
            matched = self._match_alias(alias, lines)
            if not matched:
                continue
            line, raw_value = matched
            reasons: list[str] = []
            penalty = 0.0
            normalized = apply_normalization(
                raw_value, field_definition.get("normalization_rules", []), self.date_order
            )
            if normalized is not None and normalized == "":
                normalized = None
            if normalized is None and required:
                reasons.append("required_field_missing")
            pattern = field_definition.get("validation_pattern")
            if normalized is not None and pattern and re.fullmatch(pattern, normalized) is None:
                reasons.append("validation_pattern_mismatch")
                penalty = penalty_weight
            trace = self.build_strategy_trace(
                alias_matched=True,
                regex_matched=raw_value is not None,
                ocr_confidence=line.get("confidence"),
                validation_penalty=penalty,
            )
            score = round(min(1.0, max(0.0, sum(item["contribution"] for item in trace))), 4)
            if normalized is not None and score < review_threshold:
                reasons.append("low_confidence")
            candidate = {
                "field_code": field_definition["field_code"],
                "label": field_definition["label"],
                "value_type": field_definition["value_type"],
                "required": required,
                "raw_value": raw_value,
                "normalized_value": normalized,
                "display_value": raw_value,
                "null_reason": "not_found" if normalized is None else None,
                "confidence_score": score if normalized is not None else 0.0,
                "review_required": bool(reasons),
                "review_reason_codes": sorted(set(reasons)),
                "matched_alias_ids": [alias["alias_id"]] if "alias_id" in alias else [],
                "source_page_number": line.get("page_number"),
                "source_bounding_box": line.get("bounding_box"),
                "source_text": line.get("text"),
                "strategy_trace": trace,
            }
            if best is None or (
                (candidate["normalized_value"] is not None, candidate["confidence_score"])
                > (best["normalized_value"] is not None, best["confidence_score"])
            ):
                best = candidate
        if best:
            return best

        return {
            "field_code": field_definition["field_code"],
            "label": field_definition["label"],
            "value_type": field_definition["value_type"],
            "required": required,
            "raw_value": None,
            "normalized_value": None,
            "display_value": None,
            "null_reason": "not_found",
            "confidence_score": 0.0,
            "review_required": required,
            "review_reason_codes": ["required_field_missing"] if required else [],
            "matched_alias_ids": [],
            "source_page_number": None,
            "source_bounding_box": None,
            "source_text": None,
            "strategy_trace": self.build_strategy_trace(False, False, None, 0.0),
        }

    def validate_value(
        self, field_definition: dict, value: str | None
    ) -> tuple[str | None, list[str]]:
        """Normalize an operator-entered value and report validation problems."""
        if value is not None:
            value = apply_normalization(
                value, field_definition.get("normalization_rules", []), self.date_order
            )
            value = value if value not in ("", None) else None
        problems = []
        if value is None and field_definition.get("required"):
            problems.append("required_field_missing")
        pattern = field_definition.get("validation_pattern")
        if value is not None and pattern and re.fullmatch(pattern, value) is None:
            problems.append("validation_pattern_mismatch")
        return value, problems

    def field_definition(self, family_code: str, field_code: str) -> dict | None:
        for field in self.get_taxonomy_for_family(family_code).get("fields", []):
            if field["field_code"] == field_code:
                return field
        return None

    def extract(
        self,
        document_id: str,
        document_family: str,
        ocr_output: dict,
        source_ocr_path: str = "",
    ) -> dict:
        """Run extraction against OCR output and return a metadata-extraction-run payload."""
        full_text = ocr_output.get("full_text", "")
        known = {t["family_code"] for t in self.document_types()}
        if not document_family or document_family == AUTO_FAMILY or document_family not in known:
            document_family, _ = self.detect_family(full_text)

        taxonomy = self.get_taxonomy_for_family(document_family)
        candidate = self.select_document_type(document_family, full_text, taxonomy)
        aliases = self.get_aliases_for_type(document_family, candidate["type_code"])
        if not aliases:
            aliases = self.get_aliases_for_type(document_family, taxonomy.get("type_code", ""))
        lines = text_lines(ocr_output.get("pages", []))

        field_results = []
        for field_definition in taxonomy.get("fields", []):
            field_aliases = [
                a for a in aliases if a.get("field_code") == field_definition["field_code"]
            ]
            field_results.append(self.extract_field(field_definition, field_aliases, lines))

        return {
            "schema_version": "1.0.0",
            "run_id": str(uuid.uuid4()),
            "document_id": document_id,
            "processing_status": "success",
            "source_ocr_output_path": source_ocr_path,
            "document_family": document_family,
            "document_type_candidate": candidate,
            "field_results": field_results,
            "needs_human_review": any(item["review_required"] for item in field_results),
            "extracted_at": now_utc(),
        }
