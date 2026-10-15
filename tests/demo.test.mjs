import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createDemoAdapter } from "../apps/operator-portal/modules/demo.js";

const seed = JSON.parse(readFileSync(new URL("../apps/operator-portal/demo/fixtures.json", import.meta.url)));
const base = "/api/v1/";
const id = seed.documents[0].document_id;
const newAdapter = () => createDemoAdapter(seed, () => "Test reviewer");
const post = (body = {}) => ({ method: "POST", body });

test("initial queue, search, filters and counts agree", async () => {
  const demo = newAdapter();
  const stats = await demo.request(base + "stats");
  assert.equal(stats.documents_total, 3);
  assert.equal(stats.pending_review, 1);
  assert.equal(stats.open_exceptions, 1);
  assert.equal((await demo.request(base + "review-queue")).items[0].document_id, id);
  assert.equal((await demo.request(base + "documents?q=Northwind&stage=protocol_registered")).hits.length, 1);
  assert.equal((await demo.request(base + "documents?q=no-match")).hits.length, 0);
  const workspace = await demo.request(base + `documents/${id}`);
  workspace.field_panels[0].current_value = "changed externally";
  assert.notEqual((await demo.request(base + `documents/${id}`)).field_panels[0].current_value, "changed externally");
});

test("validation, edits, approval, registration, reopen and discard update workflow", async () => {
  const demo = newAdapter();
  const path = base + `documents/${id}`;
  await assert.rejects(demo.request(path + "/fields/request_date", { method: "PUT", body: { value: "2026-02-31" } }), (e) => e.status === 422);
  await assert.rejects(demo.request(path + "/review/complete", post()), (e) => e.status === 422);
  await demo.request(path + "/fields/request_date", { method: "PUT", body: { value: "2026-03-31" } });
  await demo.request(path + "/fields/case_number", { method: "PUT", body: { value: "BP-2026-0042" } });
  assert.equal((await demo.request(path + "/review/complete", post())).workflow_state.stage, "validated");
  assert.equal((await demo.request(base + "stats")).pending_review, 0);
  const registered = await demo.request(path + "/integration/retry", post());
  assert.equal(registered.workflow_state.stage, "protocol_registered");
  assert.match(registered.external_references[0].reference_id, /^DEMO-/);
  const reopened = await demo.request(path + "/review/reopen", post({ reason: "Check again" }));
  assert.equal(reopened.workflow_state.stage, "to_be_verified");
  assert.equal(reopened.document_summary.registration_reference, null);
  assert.equal((await demo.request(path + "/discard", post({ reason: "Demo" }))).workflow_state.stage, "discarded");
  await assert.rejects(demo.request(path + "/fields/request_date", { method: "PUT", body: { value: "2026-01-01" } }), (e) => e.status === 409);
});

test("confirmation and reprocessing preserve audit and reset extraction values", async () => {
  const demo = newAdapter();
  const path = base + `documents/${id}`;
  const doc = await demo.request(path);
  const field = doc.field_panels.find((f) => f.current_value && f.value_type === "string");
  const verified = await demo.request(path + `/fields/${field.field_code}/confirm`, post());
  assert.equal(verified.field_panels.find((f) => f.field_code === field.field_code).review_required, false);
  const rerun = await demo.request(path + "/reprocess", post({ scope: "ocr", comment: "Try again" }));
  assert.equal(rerun.field_panels.every((f) => f.review_required), true);
  assert.equal(rerun.audit_timeline.at(-1).details_summary, "Try again");
});

test("exception resolution and source previews use current document data", async () => {
  const demo = newAdapter();
  await demo.request(base + "exceptions/demo-missing-reference/resolve", post({ comment: "Checked source" }));
  assert.equal((await demo.request(base + "stats")).open_exceptions, 0);
  assert.equal((await demo.download(base + `documents/${id}/source`)).headers.get("content-type"), "text/plain;charset=utf-8");
  assert.equal(await (await demo.download(base + `documents/${id}/source`)).text(), seed.documents[0].viewer.ocr_text);
});

test("uploads remain browser text, reject duplicates and unsupported formats", async () => {
  const demo = newAdapter();
  const payload = { filename: "sample.txt", mime_type: "text/plain", content_base64: Buffer.from("Subject: Café archive request\nDate: 2026-10-05").toString("base64"), document_family: "auto" };
  const uploaded = await demo.request(base + "documents", post(payload));
  const doc = await demo.request(base + `documents/${uploaded.document_id}`);
  assert.match(doc.viewer.ocr_text, /Café/);
  assert.equal(doc.field_panels.every((f) => f.current_value === null && f.review_required), true);
  assert.equal(doc.document_summary.registration_reference, null);
  await assert.rejects(demo.request(base + "documents", post(payload)), (e) => e.status === 409);
  await assert.rejects(demo.request(base + "documents", post({ ...payload, filename: "scan.pdf", mime_type: "application/pdf" })), (e) => e.status === 415);
  await assert.rejects(demo.request(base + "documents", post({ ...payload, content_base64: "/w==" })), (e) => e.status === 422);
  assert.equal((await newAdapter().request(base + "stats")).documents_total, 3);
});

test("assistant cites supported answers and hands off unknown questions", async () => {
  const demo = newAdapter();
  const path = base + `documents/${id}/assistant`;
  const answer = await demo.request(path, post({ prompt: "Why does this document need attention?" }));
  assert.equal(answer.response_mode, "answer");
  assert.equal(answer.citations[0].source_label, "Extracted fields");
  assert.equal((await demo.request(path, post({ prompt: "What is the weather?" }))).response_mode, "handoff");
});

test("all export formats include review edits and escape CSV cells", async () => {
  const demo = newAdapter();
  const registered = seed.documents[1].document_id;
  await demo.request(base + `documents/${registered}/fields/supplier_name`, { method: "PUT", body: { value: '=HYPERLINK("bad")', force: true } });
  const csv = await (await demo.download(base + "export/fields.csv")).text();
  assert.ok(csv.includes('"\'=HYPERLINK(""bad"")"'));
  const single = await (await demo.download(base + `documents/${registered}/export`)).json();
  assert.equal(single.fields.supplier_name, '=HYPERLINK("bad")');
  assert.equal(single.demo, true);
  assert.equal((await (await demo.download(base + "export/documents.json")).json()).length, 2);
  const jsonl = await (await demo.download(base + "export/documents.jsonl?include_text=true")).text();
  assert.equal(jsonl.trim().split("\n").map(JSON.parse).every((r) => r.ocr_text), true);
  await assert.rejects(demo.request(base + "unsupported"), (e) => e.status === 404);
});

test("demo transport never sends API requests or reads server tokens", async () => {
  const originalFetch = globalThis.fetch;
  const originalDocument = globalThis.document;
  const originalWindow = globalThis.window;
  const requests = [];
  globalThis.document = { querySelector: () => ({ content: "demo" }) };
  globalThis.window = {
    localStorage: { getItem: () => null },
    sessionStorage: { getItem: () => assert.fail("Demo must not read server tokens") },
  };
  globalThis.fetch = async (url) => {
    requests.push(String(url));
    assert.match(String(url), /\/demo\/fixtures\.json$/);
    return Response.json(seed);
  };
  try {
    const client = await import("../apps/operator-portal/modules/api.js");
    assert.equal(client.demoMode, true);
    assert.equal(client.settings.token, "");
    assert.equal((await client.api(base + "stats")).documents_total, 3);
    assert.equal(await client.fetchSourceBlob(id).then((blob) => blob.text()), seed.documents[0].viewer.ocr_text);
    assert.equal((await client.fetchDownload(base + "export/documents.json")).ok, true);
    assert.equal(requests.length, 1);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.document = originalDocument;
    globalThis.window = originalWindow;
  }
});
