from __future__ import annotations

import re

from xtract.review.projections import now_utc
from xtract.storage.database import RuntimeDatabase

DECISION_BOUNDARY = (
    "The assistant explains and cites evidence from this document only. Approvals, "
    "rejections, eligibility, and legal determinations stay with the operator."
)
SUGGESTED_PROMPTS = [
    "Why does this document need attention?",
    "Summarize this document",
    "Which fields were corrected?",
    "What is the registration status?",
    "Show the audit history",
]
STOPWORDS = {
    "what", "which", "where", "when", "does", "this", "that", "with", "from", "have", "show",
    "find", "tell", "about", "document", "there", "value", "field", "please", "mention",
    "mentions", "contain", "contains", "text", "search", "the", "and", "for", "is", "are",
}  # fmt: skip

INTENT_KEYWORDS = [
    (
        "administrative_decision_request",
        ["approve", "reject", "grant", "deny", "eligible", "eligibility", "decide", "decision",
         "legal", "lawful", "should i accept", "should we accept", "approva", "rifiuta"],
    ),
    ("review_attention_reason", ["why", "attention", "flag", "verify", "problem", "issue",
                                 "wrong", "review", "perché", "perche"]),
    ("field_correction_summary", ["correct", "changed", "edited", "modified", "who changed"]),
    ("integration_status_summary", ["registration", "registered", "protocol", "integration",
                                    "delivery", "delivered", "sync", "reference number"]),
    ("audit_summary", ["audit", "timeline", "history", "events", "happened"]),
    ("document_summary", ["summary", "summarize", "summarise", "overview", "describe",
                          "what is this", "riassunto"]),
]  # fmt: skip


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[\w\-/.]+", text.lower()) if len(t) > 2 and t not in STOPWORDS]


class DocumentAssistant:
    """Deterministic, source-bounded question answering over one document's stored data."""

    def __init__(self, database: RuntimeDatabase) -> None:
        self.db = database

    def classify(self, prompt: str, fields: list[dict]) -> tuple[str, dict | None]:
        lowered = prompt.lower().strip()
        if not lowered:
            return "review_attention_reason", None
        for intent, keywords in INTENT_KEYWORDS[:1]:
            if any(keyword in lowered for keyword in keywords):
                return intent, None
        for field in fields:
            label = field["label"].lower()
            if label in lowered or field["field_code"].replace("_", " ") in lowered:
                return "field_lookup", field
        for intent, keywords in INTENT_KEYWORDS[1:]:
            if any(keyword in lowered for keyword in keywords):
                return intent, None
        return "text_search", None

    def answer(self, document_id: str, prompt: str, actor: str) -> dict | None:
        doc = self.db.get_document(document_id)
        if not doc:
            return None
        prompt = (prompt or "").strip()[:500]
        fields = self.db.get_field_values(document_id)
        intent, field = self.classify(prompt, fields)
        handler = getattr(self, f"_{intent}")
        card = (
            handler(doc, fields, prompt, field)
            if intent == "field_lookup"
            else handler(doc, fields, prompt)
        )

        limitations = [
            "Answers use only this document's OCR text, field values, review tasks, and audit trail."
        ]
        confidence = doc["metadata_json"].get("ocr_avg_confidence")
        if confidence is not None and confidence < 0.85:
            limitations.append(
                f"OCR confidence is {confidence:.0%}; compare quoted text with the original file."
            )
        card.update(
            {
                "schema_version": "1.0.0",
                "document_id": document_id,
                "prompt": prompt,
                "intent_id": intent,
                "limitations": limitations + card.pop("extra_limitations", []),
                "decision_boundary": DECISION_BOUNDARY,
                "suggested_prompts": SUGGESTED_PROMPTS,
                "generated_at": now_utc(),
            }
        )
        self.db.record_audit_event(
            event_type="assistant.answered",
            institution_id=doc["institution_id"],
            document_id=document_id,
            actor_type="operator",
            actor_id=actor,
            action_code="ASSISTANT_ANSWERED",
            payload={"intent": intent, "response_mode": card["response_mode"]},
        )
        return card

    # ------------------------------------------------------------------ citations

    @staticmethod
    def _field_citation(field: dict) -> dict:
        return {
            "source_type": "field_value",
            "source_label": field["label"],
            "locator": f"field:{field['field_code']}",
            "evidence_excerpt": field.get("source_text") or str(field.get("current_value") or "—"),
        }

    def _line_citations(self, document_id: str, terms: list[str], limit: int = 5) -> list[dict]:
        text = self.db.get_document_text(document_id)["full_text"]
        citations = []
        for number, line in enumerate(text.splitlines(), start=1):
            if line.strip() and any(term in line.lower() for term in terms):
                citations.append(
                    {
                        "source_type": "ocr_text",
                        "source_label": "OCR text",
                        "locator": f"line {number}",
                        "evidence_excerpt": line.strip()[:240],
                    }
                )
                if len(citations) >= limit:
                    break
        return citations

    # ------------------------------------------------------------------ intents

    def _administrative_decision_request(self, doc, fields, prompt):
        return {
            "response_mode": "handoff",
            "title": "This decision belongs to an operator",
            "answer_text": "I can summarize the evidence, open review items, and history of this "
            "document, but I do not approve, reject, or assess eligibility. Please decide "
            "using your institution's procedure.",
            "citations": [],
        }

    def _review_attention_reason(self, doc, fields, prompt):
        tasks = self.db.get_review_tasks(document_id=doc["document_id"], task_status="PENDING")
        exceptions = self.db.get_exceptions(document_id=doc["document_id"], status="open")
        if not tasks and not exceptions:
            return {
                "response_mode": "answer",
                "title": "Nothing needs attention",
                "answer_text": f"The document is in stage '{doc['current_workflow_stage']}' with no "
                "pending review tasks or open exceptions.",
                "citations": [],
            }
        by_code = {f["field_code"]: f for f in fields}
        parts, citations = [], []
        for task in tasks:
            payload = task["payload_json"]
            reasons = ", ".join(task["reason_codes"]).replace("_", " ") or "manual review"
            value = payload.get("current_value")
            parts.append(
                f"{payload.get('label', 'Document')}: {reasons}"
                + (
                    f" (current value '{value}')"
                    if value not in (None, "")
                    else " (no value found)"
                )
            )
            field = by_code.get(payload.get("field_code"))
            citations.append(
                self._field_citation(field)
                if field
                else {
                    "source_type": "review_task",
                    "source_label": payload.get("label", "Review task"),
                    "locator": f"task:{task['review_task_id']}",
                    "evidence_excerpt": payload.get("reason", reasons),
                }
            )
        for exc in exceptions:
            message = exc["payload_json"].get("message", exc["exception_code"])
            parts.append(f"Exception {exc['exception_code']}: {message}")
            citations.append(
                {
                    "source_type": "exception",
                    "source_label": exc["exception_code"],
                    "locator": f"exception:{exc['exception_id']}",
                    "evidence_excerpt": message[:240],
                }
            )
        return {
            "response_mode": "answer",
            "title": f"{len(tasks)} review item(s), {len(exceptions)} open exception(s)",
            "answer_text": "; ".join(parts) + ".",
            "citations": citations,
        }

    def _field_correction_summary(self, doc, fields, prompt):
        revisions = [
            r
            for r in self.db.get_field_revisions(doc["document_id"])
            if r["lifecycle_stage"] == "validated"
        ]
        by_code = {f["field_code"]: f for f in fields}
        changes = [
            r for r in revisions
            if by_code.get(r["field_code"]) and r["value"] != by_code[r["field_code"]]["extracted_value"]
        ]  # fmt: skip
        if not changes:
            return {
                "response_mode": "answer",
                "title": "No corrections",
                "answer_text": f"{len(revisions)} field value(s) were confirmed; none differ from "
                "the extracted values.",
                "citations": [],
            }
        parts = [
            f"{by_code[r['field_code']]['label']} changed from "
            f"'{by_code[r['field_code']]['extracted_value'] or '—'}' to '{r['value'] or '—'}' by "
            f"{r['actor_id']}"
            for r in changes
        ]
        return {
            "response_mode": "answer",
            "title": f"{len(changes)} correction(s)",
            "answer_text": "; ".join(parts) + ".",
            "citations": [self._field_citation(by_code[r["field_code"]]) for r in changes],
        }

    def _integration_status_summary(self, doc, fields, prompt):
        refs = self.db.get_external_references(doc["document_id"])
        failures = [
            e for e in self.db.get_exceptions(document_id=doc["document_id"], status="open")
            if e["exception_code"] == "protocol_system_unavailable"
        ]  # fmt: skip
        citations = [
            {
                "source_type": "external_reference",
                "source_label": ref["target_system"],
                "locator": f"{ref['reference_type']}:{ref['authoritative_value']}",
                "evidence_excerpt": f"{ref['sync_status']} at {ref.get('synced_at') or 'unknown'}",
            }
            for ref in refs
        ]
        if refs:
            text = "; ".join(
                f"{r['reference_type'].replace('_', ' ')} {r['authoritative_value']} in "
                f"{r['target_system']} ({r['sync_status']})"
                for r in refs
            )
            title = "Registered"
        elif failures:
            text = failures[0]["payload_json"].get("message", "Delivery failed.")
            title = "Delivery failed"
        else:
            text = (
                f"No registration yet. The document is in stage '{doc['current_workflow_stage']}'; "
                "registration runs after validation when an integration route is configured."
            )
            title = "Not registered"
        return {
            "response_mode": "answer",
            "title": title,
            "answer_text": text,
            "citations": citations,
        }

    def _audit_summary(self, doc, fields, prompt):
        events = self.db.get_audit_events(doc["document_id"])
        recent = events[-6:]
        citations = [
            {
                "source_type": "audit_event",
                "source_label": event["event_type"],
                "locator": event["event_timestamp"],
                "evidence_excerpt": f"{event['actor_id']} · {event['action_code']}",
            }
            for event in recent
        ]
        actors = sorted({e["actor_id"] for e in events})
        return {
            "response_mode": "answer",
            "title": f"{len(events)} audit event(s)",
            "answer_text": f"{len(events)} events recorded by {', '.join(actors) or 'nobody'}. "
            f"Most recent: {', '.join(e['event_type'] for e in reversed(recent))}.",
            "citations": citations,
        }

    def _document_summary(self, doc, fields, prompt):
        meta = doc["metadata_json"]
        filled = [f for f in fields if f["current_value"] not in (None, "")]
        values = "; ".join(f"{f['label']}: {f['current_value']}" for f in filled) or "no values"
        return {
            "response_mode": "answer",
            "title": meta.get("document_type_display_name") or "Document summary",
            "answer_text": f"'{doc.get('title')}' is classified as "
            f"{meta.get('document_type_display_name') or doc['document_family']} and is in stage "
            f"'{doc['current_workflow_stage']}'. Extracted {len(filled)}/{len(fields)} fields — "
            f"{values}.",
            "citations": [self._field_citation(f) for f in filled[:6]],
        }

    def _field_lookup(self, doc, fields, prompt, field):
        value = field["current_value"]
        if value in (None, ""):
            return {
                "response_mode": "abstain",
                "title": f"{field['label']} not found",
                "answer_text": f"No value for {field['label']} was found in the OCR text. "
                "Check the original file and enter it manually if present.",
                "citations": [],
            }
        status = (
            "validated"
            if field["lifecycle_stage"] == "validated"
            else "extracted, not yet verified"
        )
        return {
            "response_mode": "answer",
            "title": field["label"],
            "answer_text": f"{field['label']} is '{value}' ({status}"
            + (
                f", confidence {field['confidence_score']:.0%})."
                if field["confidence_score"] is not None
                else ")."
            ),
            "citations": [self._field_citation(field)],
        }

    def _text_search(self, doc, fields, prompt):
        quoted = re.findall(r"[\"“']([^\"”']{2,})[\"”']", prompt)
        terms = [q.lower() for q in quoted] or _tokens(prompt)
        citations = self._line_citations(doc["document_id"], terms) if terms else []
        if not citations:
            return {
                "response_mode": "abstain",
                "title": "No supporting evidence",
                "answer_text": "I could not find text in this document that answers the question. "
                "Try one of the suggested prompts or search for an exact word in quotes.",
                "citations": [],
            }
        return {
            "response_mode": "answer",
            "title": f"{len(citations)} matching line(s)",
            "answer_text": "The OCR text mentions "
            + ", ".join(f"'{t}'" for t in terms[:5])
            + " on the lines cited below.",
            "citations": citations,
        }
