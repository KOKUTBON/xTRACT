import json
import unittest

from helpers import INCOMPLETE_PERMIT, INVOICE, LETTER, ingest_text, make_platform, schema_errors

from xtract.integration.connector import ProtocolConnector
from xtract.review.commands import CommandError


class FailingConnector(ProtocolConnector):
    def __init__(self):
        self.calls = 0

    def dispatch(self, command, connector, attempt_number):
        self.calls += 1
        return {
            "mode": "retryable_failure",
            "http_status": 503,
            "error_code": "503",
            "response": None,
        }


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.platform = make_platform(self)

    def artifacts(self, document_id, folder):
        doc = self.platform.db.get_document(document_id)
        prefix = f"{doc['institution_id']}/{document_id}/{folder}/"
        return [
            json.loads(self.platform.storage.get_object("integration-artifacts", item["key"]))
            for item in self.platform.storage.list_objects("integration-artifacts", prefix)
        ]

    def test_confident_document_is_validated_and_registered(self):
        document_id = ingest_text(self.platform, INVOICE, "invoice.txt")
        doc = self.platform.db.get_document(document_id)
        self.assertEqual(doc["current_workflow_stage"], "protocol_registered")
        self.assertEqual(doc["document_family"], "invoice")
        refs = self.platform.db.get_external_references(document_id)
        self.assertRegex(refs[0]["authoritative_value"], r"^REG-\d{4}-000001$")

        for payload in self.artifacts(document_id, "commands"):
            self.assertEqual(
                schema_errors("protocol-registration-command.v1.schema.json", payload), []
            )
        for payload in self.artifacts(document_id, "responses"):
            self.assertEqual(
                schema_errors("protocol-registration-response.v1.schema.json", payload), []
            )
        for payload in self.artifacts(document_id, "delivery-reports"):
            self.assertEqual(schema_errors("delivery-report.v1.schema.json", payload), [])
        for payload in self.artifacts(document_id, "reconciliation-reports"):
            self.assertEqual(schema_errors("reconciliation-report.v1.schema.json", payload), [])

        run_blob = self.platform.db.get_blob_objects(document_id, "derivative_document")[0]
        run = json.loads(
            self.platform.storage.get_object("documents-derivatives", run_blob["object_key"])
        )
        self.assertEqual(schema_errors("metadata-extraction-run.v1.schema.json", run), [])

    def test_registration_numbers_are_sequential(self):
        first = ingest_text(self.platform, INVOICE, "a.txt")
        second = ingest_text(self.platform, LETTER, "b.txt")
        numbers = [
            self.platform.db.get_external_references(doc_id)[0]["authoritative_value"][-6:]
            for doc_id in (first, second)
        ]
        self.assertEqual(numbers, ["000001", "000002"])

    def test_review_flow_corrects_fields_and_validates(self):
        commands = self.platform.commands
        document_id = ingest_text(self.platform, INCOMPLETE_PERMIT, "permit.txt")
        self.assertEqual(
            self.platform.db.get_document(document_id)["current_workflow_stage"], "to_be_verified"
        )

        queue = self.platform.projections.get_review_queue()
        self.assertEqual(schema_errors("review-work-queue.v1.schema.json", queue), [])
        self.assertEqual([item["document_id"] for item in queue["items"]], [document_id])

        with self.assertRaises(CommandError) as ctx:
            commands.complete_review(document_id, "reviewer")
        self.assertEqual(ctx.exception.code, "REQUIRED_FIELDS_MISSING")

        with self.assertRaises(CommandError) as ctx:
            commands.update_field(document_id, "request_date", "not a date", "reviewer")
        self.assertEqual(ctx.exception.status, 422)

        commands.update_field(document_id, "case_number", "bp-2026-77", "reviewer")
        commands.update_field(document_id, "request_date", "5 June 2026", "reviewer")
        field = self.platform.db.get_field_value(document_id, "request_date")
        self.assertEqual(field["current_value"], "2026-06-05")
        self.assertEqual(
            self.platform.db.get_field_value(document_id, "case_number")["current_value"],
            "BP-2026-77",
        )

        queue = self.platform.projections.get_review_queue()
        self.assertEqual(queue["items"][0]["queue_status"], "in_review")

        commands.complete_review(document_id, "reviewer")
        self.platform.process_pending()
        workspace = self.platform.projections.get_document_workspace(document_id)
        self.assertEqual(schema_errors("document-workspace.v1.schema.json", workspace), [])
        self.assertEqual(workspace["workflow_state"]["stage"], "protocol_registered")
        self.assertTrue(all(not f["review_required"] for f in workspace["field_panels"]))
        events = [event["event_type"] for event in workspace["audit_timeline"]]
        for expected in [
            "document.acquired",
            "ocr.executed",
            "extraction.completed",
            "review.requested",
            "review.field_corrected",
            "review.completed",
            "protocol.requested",
            "protocol.registered",
        ]:
            self.assertIn(expected, events)

    def test_reopen_discard_and_reprocess(self):
        commands = self.platform.commands
        document_id = ingest_text(self.platform, LETTER, "letter.txt")
        commands.reopen_review(document_id, "reviewer", "Check the sender")
        self.assertEqual(
            self.platform.db.get_document(document_id)["current_workflow_stage"], "to_be_verified"
        )

        request = commands.request_reprocessing(
            document_id, "extraction", "reviewer", comment="retry"
        )
        self.assertEqual(schema_errors("reprocess-request.v1.schema.json", request), [])
        with self.assertRaises(CommandError):
            commands.request_reprocessing(document_id, "ocr", "reviewer")  # still busy
        self.platform.process_pending()
        doc = self.platform.db.get_document(document_id)
        self.assertEqual(doc["current_workflow_stage"], "protocol_registered")
        refs = self.platform.db.get_external_references(document_id)
        self.assertEqual(len(refs), 1)  # the original registration number is reused
        self.assertEqual(
            doc["metadata_json"]["registration_reference"], refs[0]["authoritative_value"]
        )

        other = ingest_text(self.platform, INCOMPLETE_PERMIT, "permit.txt")
        with self.assertRaises(CommandError):
            commands.discard(other, "reviewer", "")
        commands.discard(other, "reviewer", "Duplicate paper copy")
        self.assertEqual(
            self.platform.db.get_document(other)["current_workflow_stage"], "discarded"
        )
        self.assertEqual(
            self.platform.db.get_review_tasks(document_id=other, task_status="PENDING"), []
        )
        with self.assertRaises(CommandError):
            commands.request_reprocessing(other, "ocr", "reviewer")

    def test_failed_delivery_raises_exception_and_retry_recovers(self):
        failing = FailingConnector()
        platform = make_platform(self, connectors={"local_registry": failing})
        document_id = ingest_text(platform, INVOICE, "invoice.txt")
        self.assertEqual(failing.calls, 3)
        self.assertEqual(
            platform.db.get_document(document_id)["current_workflow_stage"], "protocol_pending"
        )
        inbox = platform.projections.get_exception_inbox(status="open")
        self.assertEqual(schema_errors("exception-inbox.v1.schema.json", inbox), [])
        self.assertEqual(inbox["items"][0]["exception_code"], "protocol_system_unavailable")

        from xtract.integration.connector import LocalRegistryConnector

        platform.dispatcher.connectors["local_registry"] = LocalRegistryConnector(platform.db)
        platform.commands.request_reprocessing(document_id, "integration", "reviewer")
        platform.process_pending()
        self.assertEqual(
            platform.db.get_document(document_id)["current_workflow_stage"], "protocol_registered"
        )
        self.assertEqual(platform.projections.get_exception_inbox(status="open")["items"], [])

    def test_resolve_exception_is_audited(self):
        document_id = ingest_text(self.platform, "   \n  ", "blank.txt")
        exceptions = self.platform.db.get_exceptions(document_id, status="open")
        self.assertEqual(exceptions[0]["exception_code"], "ocr_low_text_coverage")
        self.platform.commands.resolve_exception(
            exceptions[0]["exception_id"], "reviewer", "Rescanned"
        )
        with self.assertRaises(CommandError):
            self.platform.commands.resolve_exception(exceptions[0]["exception_id"], "reviewer")
        events = [e["event_type"] for e in self.platform.db.get_audit_events(document_id)]
        self.assertIn("exception.resolved", events)

    def test_search_and_exports(self):
        invoice = ingest_text(self.platform, INVOICE, "invoice.txt")
        ingest_text(self.platform, INCOMPLETE_PERMIT, "permit.txt")
        results = self.platform.projections.search_documents(text_query="Example Supplier")
        self.assertEqual(schema_errors("search-result-set.v1.schema.json", results), [])
        self.assertEqual([hit["document_id"] for hit in results["hits"]], [invoice])

        exports = self.platform.exporter.export_json()
        self.assertEqual(len(exports), 1)  # only validated documents by default
        for payload in exports + self.platform.exporter.export_json("all"):
            self.assertEqual(schema_errors("validated-document-export.v1.schema.json", payload), [])
        total = next(m for m in exports[0]["metadata"] if m["field_code"] == "total_amount")
        self.assertEqual(total["normalized_value"], 1220.0)

        records = [
            json.loads(line) for line in self.platform.exporter.iter_jsonl("all", include_text=True)
        ]
        self.assertEqual(len(records), 2)
        self.assertIn("Example Supplier", records[0]["ocr_text"] + records[1]["ocr_text"])
        csv_text = self.platform.exporter.export_csv("all")
        self.assertTrue(csv_text.startswith("document_id,"))
        self.assertIn("INV-2026-0017", csv_text)

    def test_assistant_is_source_bounded(self):
        document_id = ingest_text(self.platform, INCOMPLETE_PERMIT, "permit.txt")
        assistant = self.platform.assistant
        cases = {
            "Should I approve this permit?": ("administrative_decision_request", "handoff"),
            "Why does this need attention?": ("review_attention_reason", "answer"),
            "What is the applicant full name?": ("field_lookup", "answer"),
            "What is the case number?": ("field_lookup", "abstain"),
            "Summarize this document": ("document_summary", "answer"),
            "Where does it mention 'Applicant'?": ("text_search", "answer"),
            "Tell me about quantum physics": ("text_search", "abstain"),
        }
        for prompt, (intent, mode) in cases.items():
            with self.subTest(prompt=prompt):
                card = assistant.answer(document_id, prompt, "reviewer")
                self.assertEqual(schema_errors("assistant-answer.v1.schema.json", card), [])
                self.assertEqual((card["intent_id"], card["response_mode"]), (intent, mode))
        attention = assistant.answer(document_id, "why?", "reviewer")
        self.assertTrue(attention["citations"])


if __name__ == "__main__":
    unittest.main()
