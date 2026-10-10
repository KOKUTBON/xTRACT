/** Static demo transport. Documents and changes live only in this page's memory. */
const copy = (value) => structuredClone(value);
const now = () => new Date().toISOString();
const fail = (status, message, error = "DEMO_ERROR") => {
  throw Object.assign(new Error(message), { status, body: { message, error } });
};

export function createDemoAdapter(seed, operator = () => "Demo operator") {
  const documents = copy(seed.documents);
  const find = (id) => documents.find((doc) => doc.document_id === id) || fail(404, "Document not found.");
  const issues = () => documents.flatMap((doc) => doc.exception_context.map((exc) => ({ ...exc, document_id: doc.document_id })));
  function audit(doc, event, details = "") {
    doc.audit_timeline.push({ event_type: event, occurred_at: now(), actor_id: operator(), outcome: "success", details_summary: details });
  }
  function update(doc) {
    const stage = doc.workflow_state.stage;
    doc.permitted_actions = stage === "discarded" ? ["open_audit"] : ["open_audit", "request_reprocessing", "correct_field",
      ...(stage === "to_be_verified" ? ["complete_review", "discard_document"] : ["reopen_review"]),
      ...(stage === "validated" || stage === "protocol_pending" ? ["retry_integration"] : [])];
    doc.workflow_state.updated_at = now();
    doc.queue_context.reason_codes = [...new Set(doc.field_panels.flatMap((field) => field.review_reason_codes))];
    return copy(doc);
  }
  function validate(field, value, force = false) {
    if (force) return;
    const validDate = field.value_type !== "date" || !value || (
      /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
    );
    if ((field.required && !value) || (value && field.validation_pattern && !new RegExp(field.validation_pattern).test(value)) || !validDate) {
      fail(422, `Invalid value for ${field.label}.`, "VALIDATION_FAILED");
    }
  }
  function verify(field, value) {
    field.current_value = value;
    field.validated_value = value;
    field.review_required = false;
    field.review_reason_codes = [];
    field.snapshots.push({ lifecycle_stage: "validated", value, created_at: now(), created_by: operator(), note: "Browser demo review" });
  }
  function exportRecord(doc) {
    return { demo: true, document_id: doc.document_id, source_filename: doc.document_summary.source_filename,
      workflow_stage: doc.workflow_state.stage, fields: Object.fromEntries(doc.field_panels.map((f) => [f.field_code, f.current_value])),
      field_provenance: copy(doc.field_panels), audit_timeline: copy(doc.audit_timeline) };
  }
  function assistant(doc, prompt) {
    const text = prompt.toLowerCase();
    const pending = doc.field_panels.filter((f) => f.review_required);
    let answer;
    let evidence;
    let source = "OCR text";
    if (/audit|history|cronologia/.test(text)) {
      answer = doc.audit_timeline.map((e) => `${e.event_type}: ${e.details_summary}`).join("\n");
      evidence = doc.audit_timeline.at(-1)?.event_type || "No events";
      source = "Audit trail";
    } else if (/correct|modific|corrett/.test(text)) {
      const changed = doc.field_panels.filter((f) => f.extracted_value !== f.current_value);
      answer = changed.length ? changed.map((f) => `${f.label}: ${f.extracted_value ?? "missing"} → ${f.current_value ?? "empty"}`).join("; ") : "No fields have been corrected.";
      evidence = answer;
      source = "Field history";
    } else if (/regist|protocol|status|stato/.test(text)) {
      answer = `Workflow stage: ${doc.workflow_state.stage}. ${doc.external_references.map((r) => r.reference_id).join(", ") || "No registration reference."}`;
      evidence = answer;
      source = "Workflow state";
    } else if (/attention|review|verify|verific|attenzione/.test(text)) {
      answer = pending.length ? `Fields requiring verification: ${pending.map((f) => f.label).join(", ")}. Check them against the source before completing review.` : "All fields are clear.";
      evidence = pending.map((f) => `${f.label}: ${f.current_value ?? "missing"}`).join("; ") || answer;
      source = "Extracted fields";
    } else if (/summar|riass|sintesi/.test(text)) {
      answer = `${doc.document_summary.document_type_display_name}: ${doc.viewer.ocr_text.replace(/\n+/g, " ")}`;
      evidence = doc.viewer.ocr_text;
    } else {
      return { title: "Demo assistant", response_mode: "handoff", answer_text: "This demo supports summaries, review reasons, corrections, registration status, and audit history. Choose a suggested question.", citations: [], limitations: ["Scripted responses; no AI service is connected."], decision_boundary: "Review decisions remain with the operator." };
    }
    return { title: "Demo assistant", response_mode: "answer", answer_text: answer,
      citations: [{ source_label: source, locator: doc.document_summary.source_filename, evidence_excerpt: evidence }],
      limitations: ["Scripted response from the demo document; no AI service is connected."], decision_boundary: "Review decisions remain with the operator." };
  }

  async function request(path, { method = "GET", body = {} } = {}) {
    const url = new URL(path, "https://demo.invalid");
    const route = url.pathname.replace(/^\/api\/v1\//, "");
    if (method === "GET") {
      if (route === "auth/me") return { display_name: operator(), roles: ["operator"], permissions: ["admin:manage"], institution_id: "default" };
      if (route === "branding") return copy(seed.branding);
      if (route === "config") return copy(seed.config);
      if (route === "stats") return { documents_total: documents.length, documents_by_stage: documents.reduce((counts, doc) => {
        counts[doc.workflow_state.stage] = (counts[doc.workflow_state.stage] || 0) + 1; return counts;
      }, {}), pending_review: documents.filter((doc) => doc.workflow_state.stage === "to_be_verified").length, open_exceptions: issues().filter((exc) => exc.status === "open").length };
      if (route === "review-queue") return { items: documents.filter((doc) => doc.workflow_state.stage === "to_be_verified").map((doc) => ({
        document_id: doc.document_id, reason_codes: [...new Set(doc.field_panels.flatMap((field) => field.review_reason_codes))],
        document_summary: { ...doc.document_summary, excerpt: `${doc.field_panels.filter((f) => f.review_required).length} fields to verify` },
      })) };
      if (route === "documents") {
        const query = (url.searchParams.get("q") || "").toLowerCase();
        const stage = url.searchParams.get("stage");
        return { hits: documents.filter((doc) => (!stage || doc.workflow_state.stage === stage) && `${doc.document_summary.title} ${doc.viewer.ocr_text} ${doc.field_panels.map((f) => f.current_value).join(" ")}`.toLowerCase().includes(query)).map((doc) => ({
          ...doc.document_summary, document_id: doc.document_id, workflow_stage: doc.workflow_state.stage,
          matched_text_excerpt: doc.viewer.ocr_text.slice(0, 160), external_reference_ids: doc.external_references.map((ref) => ref.reference_id),
        })) };
      }
      if (route === "exceptions") return { items: issues().filter((exc) => !url.searchParams.get("status") || exc.status === url.searchParams.get("status")) };
    }
    if (route === "documents" && method === "POST") {
      if (!body.filename?.toLowerCase().endsWith(".txt") || (body.mime_type && body.mime_type !== "text/plain")) fail(415, "The browser demo accepts UTF-8 .txt files only. PDF/image OCR requires the local server.");
      let bytes;
      try { bytes = Uint8Array.from(atob(body.content_base64), (c) => c.charCodeAt(0)); } catch { fail(400, "Invalid file content."); }
      if (bytes.length > seed.config.max_upload_bytes) fail(413, "The demo file limit is 1 MiB.");
      let content;
      try { content = new TextDecoder("utf-8", { fatal: true }).decode(bytes); } catch { fail(422, "Use a UTF-8 text file."); }
      if (!content.trim()) fail(422, "The document is empty.");
      if (documents.some((doc) => doc.viewer.ocr_text === content)) fail(409, "This document already exists in the demo.");
      const family = body.document_family === "auto" ? (/invoice/i.test(content) ? "invoice" : /building permit/i.test(content) ? "building_permit" : "general_correspondence") : body.document_family;
      const type = seed.taxonomy.document_types.find((t) => t.family_code === family) || fail(422, "Unknown document type.");
      const doc = copy(seed.documents[0]);
      doc.document_id = `demo-${crypto.randomUUID()}`;
      doc.document_summary = { ...doc.document_summary, title: body.filename, source_filename: body.filename, document_family: family, document_type_code: type.type_code, document_type_display_name: type.display_name, mime_type: "text/plain", byte_size: bytes.length, created_at: now(), ocr_engine: "demo-text", ocr_confidence: 1, registration_reference: null, sha256: null };
      doc.viewer = { source_filename: body.filename, page_count: 1, ocr_text: content };
      doc.workflow_state.stage = "to_be_verified";
      doc.field_panels = type.fields.map((f) => ({ ...f, current_value: null, extracted_value: null, validated_value: null, review_required: true, review_reason_codes: ["operator_review_required"], confidence_score: 0, source_text: null, source_page_number: 1, aliases: [], snapshots: [] }));
      doc.audit_timeline = [];
      doc.review_history = [];
      doc.exception_context = [];
      doc.external_references = [];
      doc.processing = { active: false, jobs: [] };
      documents.unshift(doc);
      audit(doc, "demo.document.added", "Text read in browser; fill in fields manually. Extraction is simulated.");
      update(doc);
      return { document_id: doc.document_id };
    }
    const exception = route.match(/^exceptions\/([^/]+)\/resolve$/);
    if (exception && method === "POST") {
      const doc = documents.find((d) => d.exception_context.some((exc) => exc.exception_id === exception[1])) || fail(404, "Exception not found.");
      doc.exception_context.find((exc) => exc.exception_id === exception[1]).status = "resolved";
      audit(doc, "demo.exception.resolved", body.comment);
      return { status: "resolved" };
    }
    const match = route.match(/^documents\/([^/]+)(?:\/(.*))?$/);
    if (!match) fail(404, `Unsupported demo route: ${method} ${route}`);
    const doc = find(decodeURIComponent(match[1]));
    const action = match[2] || "";
    if (method === "GET" && !action) return copy(doc);
    if (method === "POST" && action === "assistant") return assistant(doc, body.prompt || "");
    const fieldMatch = action.match(/^fields\/([^/]+)(\/confirm)?$/);
    if (fieldMatch && ((method === "PUT" && !fieldMatch[2]) || (method === "POST" && fieldMatch[2]))) {
      if (!doc.permitted_actions.includes("correct_field")) fail(409, "This document cannot be edited.");
      const field = doc.field_panels.find((f) => f.field_code === fieldMatch[1]) || fail(404, "Field not found.");
      const value = fieldMatch[2] ? field.current_value : body.value;
      validate(field, value, body.force);
      verify(field, value);
      audit(doc, "demo.field.confirmed", `${field.label}=${value ?? ""}`);
      return update(doc);
    }
    const permission = { "review/complete": "complete_review", "review/reopen": "reopen_review", discard: "discard_document", "integration/retry": "retry_integration", reprocess: "request_reprocessing" }[action];
    if (method !== "POST" || !permission) fail(404, `Unsupported demo route: ${method} ${route}`);
    if (!doc.permitted_actions.includes(permission)) fail(409, "Action is not available at this workflow stage.");
    if (action === "review/complete") {
      doc.field_panels.forEach((f) => validate(f, f.current_value));
      doc.field_panels.filter((f) => f.review_required).forEach((f) => verify(f, f.current_value));
      doc.workflow_state.stage = "validated";
    } else if (action === "review/reopen" || action === "reprocess") {
      doc.workflow_state.stage = "to_be_verified";
      if (action === "reprocess") doc.field_panels.forEach((f) => {
        f.current_value = f.extracted_value; f.validated_value = null;
        f.review_required = true; f.review_reason_codes = ["operator_review_required"];
      });
      doc.external_references = [];
      doc.document_summary.registration_reference = null;
    } else if (action === "discard") doc.workflow_state.stage = "discarded";
    else if (action === "integration/retry") {
      doc.workflow_state.stage = "protocol_registered";
      const reference = `DEMO-${doc.document_id.slice(0, 8).toUpperCase()}`;
      doc.document_summary.registration_reference = reference;
      doc.external_references = [{ system_name: "Demo registry", reference_type: "protocol", reference_id: reference, status: "synchronized", synchronized_at: now() }];
    }
    audit(doc, `demo.${action.replaceAll("/", ".")}`, body.reason || body.comment || "Simulated in browser");
    return update(doc);
  }

  async function download(path) {
    const route = new URL(path, "https://demo.invalid").pathname;
    const source = route.match(/^\/api\/v1\/documents\/([^/]+)\/source$/);
    if (source) return new Response(find(source[1]).viewer.ocr_text, { headers: { "Content-Type": "text/plain;charset=utf-8" } });
    const single = route.match(/^\/api\/v1\/documents\/([^/]+)\/export$/);
    const records = single ? [exportRecord(find(single[1]))] : documents.filter((doc) => ["validated", "protocol_pending", "protocol_registered"].includes(doc.workflow_state.stage)).map(exportRecord);
    let data, type, filename;
    if (route === "/api/v1/export/fields.csv") {
      const cell = (value) => `"${String(value ?? "").replace(/^[=+@-]/, "'$&").replaceAll('"', '""')}"`;
      data = "document_id,source_filename,field_code,value\r\n" + records.flatMap((r) => Object.entries(r.fields).map(([code, value]) => [r.document_id, r.source_filename, code, value].map(cell).join(","))).join("\r\n");
      type = "text/csv;charset=utf-8"; filename = "demo-fields.csv";
    } else if (route === "/api/v1/export/documents.jsonl") {
      data = records.map((r) => JSON.stringify({ ...r, ...(path.includes("include_text=true") ? { ocr_text: find(r.document_id).viewer.ocr_text } : {}) })).join("\n") + "\n";
      type = "application/x-ndjson"; filename = "demo-documents.jsonl";
    } else if (single || route === "/api/v1/export/documents.json") {
      data = JSON.stringify(single ? records[0] : records, null, 2);
      type = "application/json"; filename = single ? `${records[0].document_id}.json` : "demo-documents.json";
    } else fail(404, "Unsupported demo download.");
    return new Response(data, { headers: { "Content-Type": type, "Content-Disposition": `attachment; filename="${filename}"` } });
  }
  return { request, download };
}

let adapter;
export async function getDemoAdapter(operator) {
  adapter ||= fetch(new URL("../demo/fixtures.json", import.meta.url)).then(async (res) => {
    if (!res.ok) throw new Error("Could not load demo fixtures.");
    return createDemoAdapter(await res.json(), operator);
  });
  return adapter;
}
