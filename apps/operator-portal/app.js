import {
  settings,
  demoMode,
  fetchDownload,
  api,
  fetchSourceBlob,
  sourceBlobManager,
  setAuthHandler,
} from "./modules/api.js";
import {
  STAGE_LABELS,
  STAGE_TONE,
  STAGE_ICONS,
  LIFECYCLE,
  REASON_LABELS,
  ACTION_LABELS,
  el,
  icon,
  fileGlyph,
  meter,
  initials,
  relativeTime,
  formatBytes,
  percent,
  formatDate,
  stagePill,
} from "./modules/ui.js";
import {
  SUPPORTED_LOCALES,
  currentLocale,
  initLocale,
  setLocale,
  onLocaleChange,
  t,
  getListMeta,
  getSuggestedPrompts,
  applyI18n,
} from "./modules/i18n.js";

const POLL_BUSY_MS = 2500;
const POLL_IDLE_MS = 15000;

const LISTS = new Proxy({}, {
  get: (_, prop) => getListMeta(prop),
});

const THEMES = ["system", "light", "dark"];
const THEME_ICONS = { system: "system", light: "sun", dark: "moon" };

const state = {
  config: null,
  user: null,
  list: "queue",
  listIds: [],
  selectedId: null,
  workspace: null,
  view: "text",
  panel: "assistant",
  query: "",
  stage: "",
  highlightLine: null,
  pollTimer: null,
  busy: false,
  branding: null,
};

const $ = (selector) => document.querySelector(selector);
const nodes = {
  pageTitle: $("#app-page-title"),
  appFavicon: $("#app-favicon"),
  appTouchIcon: $("#app-apple-touch-icon"),
  brandLink: $("#nav-brand-link"),
  brandLogo: $("#nav-brand-logo"),
  emptyBrandLogo: $("#empty-brand-logo"),
  institutionName: $("#institution-name-display"),
  institutionTagline: $("#institution-tagline-display"),
  packNameDisplay: $("#pack-name-display"),
  pipeline: $("#pipeline"),
  list: $("#item-list"),
  listTitle: $("#list-title"),
  listEyebrow: $("#list-eyebrow"),
  listCount: $("#list-count"),
  listFilters: $("#list-filters"),
  crumb: $("#crumb-list"),
  searchForm: $("#search-form"),
  searchText: $("#search-text"),
  stageFilter: $("#stage-filter"),
  engineStatus: $("#engine-status"),
  emptyWorkspace: $("#empty-workspace"),
  documentView: $("#document-view"),
  title: $("#workspace-title"),
  glyph: $("#doc-glyph"),
  stagePill: $("#stage-pill"),
  docType: $("#doc-type"),
  docMeta: $("#doc-meta"),
  lifecycle: $("#lifecycle"),
  actionBar: $("#action-bar"),
  banner: $("#processing-banner"),
  bannerText: $("#processing-text"),
  viewerMeta: $("#viewer-meta"),
  ocrLines: $("#ocr-lines"),
  original: $("#original-view"),
  fieldsMeta: $("#fields-meta"),
  fieldsProgress: $("#fields-progress"),
  fieldList: $("#field-list"),
  assistantForm: $("#assistant-form"),
  assistantPrompt: $("#assistant-prompt"),
  assistantSubmit: $("#assistant-submit"),
  assistantSuggestions: $("#assistant-suggestions"),
  assistantAnswer: $("#assistant-answer"),
  docExceptions: $("#doc-exceptions"),
  docReferences: $("#doc-references"),
  docJobs: $("#doc-jobs"),
  docAudit: $("#doc-audit"),
  tabCountExceptions: $("#tab-count-exceptions"),
  live: $("#status-live"),
  toasts: $("#toasts"),
  operatorInitials: $("#operator-initials"),
  userRoleDisplay: $("#settings-user-role-display"),
  userRoleWrap: $("#settings-user-role-wrap"),
  themeButton: $("#theme-button"),
  themeIcon: $("#theme-icon"),
  dropOverlay: $("#drop-overlay"),
};

// ---------------------------------------------------------------- utilities

function announce(message) {
  nodes.live.textContent = "";
  window.requestAnimationFrame(() => { nodes.live.textContent = message; });
}

const TOAST_ICONS = { success: "check-circle", danger: "exception", info: "info" };

function toast(message, tone = "info") {
  const item = el("div", { class: `toast ${tone}` }, icon(TOAST_ICONS[tone] || "info"), el("span", { text: message }));
  nodes.toasts.append(item);
  window.setTimeout(() => item.remove(), tone === "danger" ? 8000 : 4000);
  announce(message);
}

async function run(action, successMessage) {
  if (state.busy) return null;
  state.busy = true;
  document.body.classList.add("busy");
  try {
    const result = await action();
    if (successMessage) toast(successMessage, "success");
    return result;
  } catch (error) {
    toast(error.message, "danger");
    return null;
  } finally {
    state.busy = false;
    document.body.classList.remove("busy");
  }
}

function emptyState(iconName, text) {
  return el("li", { class: "empty" }, icon(iconName), el("span", { text }));
}

function humanize(code = "") {
  return code.replaceAll("_", " ").replaceAll(".", " · ");
}

async function downloadAuthenticated(url, fallbackName = "export") {
  const res = await fetchDownload(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") || "";
  let filename = fallbackName;
  const match = disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)/i);
  if (match) filename = decodeURIComponent(match[1]);
  const objUrl = URL.createObjectURL(blob);
  const anchor = el("a", { href: objUrl, download: filename });
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objUrl), 2000);
}

// ---------------------------------------------------------------- branding

function applyBranding(profile) {
  if (!profile) return;
  if (profile.app_title) {
    document.title = profile.app_title;
    if (nodes.pageTitle) nodes.pageTitle.textContent = profile.app_title;
  }
  if (profile.favicon_url && nodes.appFavicon) {
    nodes.appFavicon.href = profile.favicon_url;
  }
  if (profile.app_icon_url && nodes.appTouchIcon) {
    nodes.appTouchIcon.href = profile.app_icon_url;
  }
  if (profile.logo_url) {
    if (nodes.brandLogo) {
      nodes.brandLogo.src = profile.logo_url;
      nodes.brandLogo.alt = profile.institution_name || "";
    }
    if (nodes.emptyBrandLogo) {
      nodes.emptyBrandLogo.src = profile.logo_url;
    }
  }
  if (profile.institution_name) {
    if (nodes.brandLink) {
      nodes.brandLink.setAttribute("aria-label", `${profile.institution_name} home`);
    }
    if (nodes.institutionName) {
      nodes.institutionName.textContent = profile.institution_name;
    }
  }
  if (profile.tagline && nodes.institutionTagline) {
    nodes.institutionTagline.textContent = profile.tagline;
  }
  if (profile.accent_color) {
    document.documentElement.style.setProperty("--brand-accent", profile.accent_color);
  }
}

// ---------------------------------------------------------------- theme

function currentTheme() {
  return document.documentElement.dataset.theme || "system";
}

function applyTheme(theme) {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  try {
    if (theme === "system") window.localStorage.removeItem("xtract.theme");
    else window.localStorage.setItem("xtract.theme", theme);
  } catch { /* storage unavailable */ }
  nodes.themeIcon.setAttribute("href", `#i-${THEME_ICONS[theme]}`);
  nodes.themeButton.dataset.tip = `Theme: ${theme}`;
}

function cycleTheme() {
  const next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
  applyTheme(next);
  announce(`Theme: ${next}`);
}

// ---------------------------------------------------------------- pipeline & counts

const PIPELINE = [
  ["acquired", "Queued"],
  ["ocr_executed", "Extracting"],
  ["to_be_verified", "Needs review"],
  ["validated", "Validated"],
  ["protocol_pending", "Registering"],
  ["protocol_registered", "Registered"],
];

async function refreshStats() {
  const stats = await api("/api/v1/stats");
  const byStage = stats.documents_by_stage || {};
  const total = stats.documents_total || 0;
  const share = (count) => (total ? `${Math.max(4, Math.round((count / total) * 100))}%` : "0%");

  const stageButton = (stage, label, extra = "") => {
    const count = byStage[stage] || 0;
    const button = el("button", {
      type: "button",
      class: `stage ${extra}`.trim(),
      "data-tone": STAGE_TONE[stage] === "info" ? null : STAGE_TONE[stage],
      "aria-pressed": String(state.list === "documents" && state.stage === stage),
      title: `Show ${STAGE_LABELS[stage] || stage} documents`,
      onclick: () => filterByStage(state.stage === stage && state.list === "documents" ? "" : stage),
    },
    el("span", { class: "stage-icon" }, icon(STAGE_ICONS[stage] || "documents", "")),
    el("strong", { text: count }),
    el("span", { text: label }),
    el("i", { class: "bar", "aria-hidden": "true" }));
    button.style.setProperty("--share", count ? share(count) : "0%");
    return button;
  };

  const flow = [];
  PIPELINE.forEach(([stage, fallbackLabel], index) => {
    if (index) flow.push(el("span", { class: "flow-arrow", "aria-hidden": "true" }, icon("chevron-right")));
    flow.push(stageButton(stage, STAGE_LABELS[stage] || fallbackLabel));
  });
  nodes.pipeline.replaceChildren(
    ...flow,
    el("span", { class: "flow-sep", "aria-hidden": "true" }),
    stageButton("failed", STAGE_LABELS.failed || "Failed", "side"),
    el("button", {
      type: "button",
      class: "stage side",
      "data-tone": stats.open_exceptions ? "danger" : null,
      onclick: () => setList("exceptions"),
      title: "Show open exceptions",
    },
    el("span", { class: "stage-icon" }, icon("exception", "")),
    el("strong", { text: stats.open_exceptions || 0 }),
    el("span", { text: t("tab_issues", "Open issues") })),
  );

  $("#count-queue").textContent = stats.pending_review || "";
  $("#count-documents").textContent = total || "";
  $("#count-exceptions").textContent = stats.open_exceptions || "";
  return stats;
}

function renderEngineStatus() {
  const engines = state.config?.ocr_engines || [];
  if (!engines.length) { nodes.engineStatus.hidden = true; return; }
  const available = engines.filter((engine) => engine.available);
  nodes.engineStatus.hidden = false;
  nodes.engineStatus.classList.toggle("degraded", available.length < engines.length);
  nodes.engineStatus.title = engines.map((e) => `${e.engine_id}: ${e.available ? "available" : e.reason}`).join("\n");
  nodes.engineStatus.replaceChildren(
    el("span", { class: "dot", "aria-hidden": "true" }),
    `OCR ${available.length}/${engines.length} · local`,
  );
}

// ---------------------------------------------------------------- lists

function listButton(documentId, { title, subtitle, excerpt, tags = [], stage, filename, mime, time }) {
  const active = documentId === state.selectedId;
  const button = el(
    "button",
    {
      type: "button",
      class: `item-button${active ? " active" : ""}`,
      "aria-current": active ? "true" : null,
      "data-doc": documentId,
      onclick: () => selectDocument(documentId),
    },
    fileGlyph(filename || title, mime),
    el("span", { class: "item-body" },
      el("span", { class: "item-title" }, el("span", { text: title }), stage ? stagePill(stage) : null),
      subtitle ? el("span", { class: "item-meta", text: [subtitle, time].filter(Boolean).join(" · ") }) : null,
      excerpt ? el("span", { class: "item-excerpt", text: excerpt }) : null,
      tags.length ? el("span", { class: "item-tags" }, ...tags) : null,
    ),
  );
  return el("li", {}, button);
}

async function refreshList() {
  let items = [];
  const ids = [];
  if (state.list === "queue") {
    const queue = await api("/api/v1/review-queue");
    items = queue.items.map((item) => {
      ids.push(item.document_id);
      return listButton(item.document_id, {
        title: item.document_summary.source_filename,
        filename: item.document_summary.source_filename,
        subtitle: item.document_summary.document_type_display_name,
        excerpt: item.document_summary.excerpt,
        tags: item.reason_codes.map((code) => el("span", { class: "tag warn", text: REASON_LABELS[code] || humanize(code) })),
      });
    });
    if (!items.length) items = [emptyState("check-circle", "Queue is clear. New uploads that need checking appear here.")];
  } else if (state.list === "documents") {
    const params = new URLSearchParams();
    if (state.query) params.set("q", state.query);
    if (state.stage) params.set("stage", state.stage);
    const result = await api(`/api/v1/documents?${params}`);
    items = result.hits.map((hit) => {
      ids.push(hit.document_id);
      return listButton(hit.document_id, {
        title: hit.source_filename,
        filename: hit.source_filename,
        subtitle: hit.document_type_display_name,
        excerpt: hit.matched_text_excerpt,
        stage: hit.workflow_stage,
        tags: hit.external_reference_ids.map((ref) => el("span", { class: "tag mono", text: ref })),
      });
    });
    if (!items.length) {
      items = [state.query || state.stage
        ? emptyState("search", "No documents match these filters.")
        : emptyState("documents", "No documents yet. Drop files anywhere to upload.")];
    }
  } else {
    const inbox = await api("/api/v1/exceptions?status=open");
    items = inbox.items.map((item) => {
      ids.push(item.document_id);
      return listButton(item.document_id, {
        title: humanize(item.exception_code),
        filename: "alert.txt",
        subtitle: `${item.severity} · ${relativeTime(item.opened_at)}`,
        excerpt: item.message,
      });
    });
    if (!items.length) items = [emptyState("shield", "No open exceptions. Everything is flowing.")];
  }
  state.listIds = ids;
  nodes.listCount.textContent = ids.length ? String(ids.length) : "";
  nodes.list.replaceChildren(...items);
  renderListFilters();
}

function renderListFilters() {
  const chips = [];
  if (state.list === "documents" && state.query) {
    chips.push(el("button", { type: "button", class: "btn small", onclick: () => { nodes.searchText.value = ""; state.query = ""; setList("documents"); } },
      icon("search", "xs"), `“${state.query}”`, icon("close", "xs")));
  }
  if (state.list === "documents" && state.stage) {
    chips.push(el("button", { type: "button", class: "btn small", onclick: () => filterByStage("") },
      icon("filter", "xs"), STAGE_LABELS[state.stage] || state.stage, icon("close", "xs")));
  }
  nodes.listFilters.hidden = !chips.length;
  nodes.listFilters.replaceChildren(...chips);
}

function setList(list) {
  state.list = list;
  document.querySelectorAll("[data-list]").forEach((item) => {
    if (item.dataset.list === list) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  nodes.listTitle.textContent = LISTS[list].title;
  nodes.listEyebrow.textContent = LISTS[list].eyebrow;
  nodes.crumb.textContent = LISTS[list].title;
  syncLocation();
  refreshList().catch((error) => toast(error.message, "danger"));
  refreshStats().catch(() => {});
}

function filterByStage(stage) {
  state.stage = stage;
  nodes.stageFilter.value = stage;
  setList("documents");
}

function moveSelection(step) {
  if (!state.listIds.length) return;
  const index = state.listIds.indexOf(state.selectedId);
  const next = index < 0 ? 0 : Math.min(state.listIds.length - 1, Math.max(0, index + step));
  selectDocument(state.listIds[next]).then(() => {
    nodes.list.querySelector(`[data-doc="${state.listIds[next]}"]`)?.scrollIntoView({ block: "nearest" });
  });
}

// ---------------------------------------------------------------- workspace

async function selectDocument(documentId) {
  sourceBlobManager.revoke();
  nodes.original.dataset.docId = "";
  nodes.original.dataset.loaded = "";
  state.selectedId = documentId;
  state.highlightLine = null;
  nodes.assistantAnswer.hidden = true;
  try {
    const workspace = await api(`/api/v1/documents/${documentId}`);
    if (state.selectedId !== documentId) return;
    state.workspace = workspace;
  } catch (error) {
    toast(error.message, "danger");
    return;
  }
  renderWorkspace();
  nodes.list.querySelectorAll(".item-button").forEach((button) => {
    const active = button.dataset.doc === documentId;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  });
  announce(`Opened ${state.workspace.document_summary.title}`);
  syncLocation();
  schedulePoll();
}

// Keep the open document and list in the URL so views can be linked and restored.
function syncLocation() {
  const params = new URLSearchParams();
  if (state.list !== "queue") params.set("list", state.list);
  if (state.selectedId) params.set("doc", state.selectedId);
  const hash = params.toString();
  if (hash !== window.location.hash.slice(1)) window.history.replaceState(null, "", hash ? `#${hash}` : window.location.pathname);
}

function readLocation() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const list = params.get("list");
  return { list: LISTS[list] ? list : null, doc: params.get("doc") };
}

async function reloadWorkspace() {
  if (!state.selectedId) return;
  const id = state.selectedId;
  const workspace = await api(`/api/v1/documents/${id}`);
  if (state.selectedId !== id) return;
  state.workspace = workspace;
  renderWorkspace();
}

function renderWorkspace() {
  const ws = state.workspace;
  const hasDoc = Boolean(ws);
  nodes.emptyWorkspace.hidden = hasDoc;
  nodes.documentView.hidden = !hasDoc;
  nodes.assistantPrompt.disabled = !hasDoc;
  nodes.assistantSubmit.disabled = !hasDoc;
  if (!hasDoc) return;

  const summary = ws.document_summary;
  const stage = ws.workflow_state.stage;
  nodes.title.textContent = summary.title;
  nodes.glyph.replaceWith(Object.assign(fileGlyph(summary.source_filename, summary.mime_type, "lg"), { id: "doc-glyph" }));
  nodes.glyph = $("#doc-glyph");
  nodes.stagePill.replaceWith(Object.assign(stagePill(stage), { id: "stage-pill" }));
  nodes.stagePill = $("#stage-pill");
  nodes.docType.textContent = summary.document_type_display_name || humanize(summary.document_family);
  nodes.docMeta.textContent = [
    summary.mime_type,
    formatBytes(summary.byte_size),
    `added ${relativeTime(summary.created_at)}`,
    summary.registration_reference ? `ref ${summary.registration_reference}` : "",
    `${ws.institution_id} / ${ws.office_id}`,
  ].filter(Boolean).join("  ·  ");
  nodes.docMeta.title = formatDate(summary.created_at);

  nodes.banner.hidden = !ws.processing.active;
  nodes.documentView.classList.toggle("processing", Boolean(ws.processing.active));
  const activeJob = ws.processing.jobs.find((job) => ["pending", "processing", "failed"].includes(job.status));
  nodes.bannerText.textContent = activeJob
    ? `Processing: ${activeJob.job_type.replace(".", " → ").replaceAll("_", " ")} (${activeJob.status})`
    : `Processing: ${STAGE_LABELS[stage] || stage}`;

  renderLifecycle(ws);
  renderActions(ws);
  renderViewer(ws);
  renderFields(ws);
  renderExceptions(ws);
  renderReferences(ws);
  renderJobs(ws);
  renderAudit(ws);
  renderSuggestions();
}

function renderLifecycle(ws) {
  const stage = ws.workflow_state.stage;
  let currentIndex = LIFECYCLE.findIndex(([code]) => code === stage);
  const terminal = stage === "failed" || stage === "discarded";
  if (terminal) {
    // Show how far the document got before it left the happy path.
    const reached = ws.audit_timeline.map((event) => event.event_type).join(" ");
    currentIndex = reached.includes("review") ? 2 : reached.includes("ocr") ? 1 : 0;
  }
  nodes.lifecycle.replaceChildren(...LIFECYCLE.map(([code, label], index) => {
    let cls = index < currentIndex ? "done" : index === currentIndex ? "current" : "";
    let text = label;
    if (index === currentIndex) {
      if (terminal) { cls += " danger"; text = STAGE_LABELS[stage]; }
      else if (STAGE_TONE[code] === "warn") cls += " warn";
      else if (code === "protocol_registered" || code === "validated") cls += " success";
      if (ws.processing.active) cls += " active";
    }
    return el("li", { class: cls || null, "aria-current": index === currentIndex ? "step" : null, text });
  }));
}

function renderActions(ws) {
  const actions = [];
  const permitted = new Set(ws.permitted_actions);
  const id = ws.document_id;
  const userPerms = state.user?.permissions ? new Set(state.user.permissions) : null;
  const canReprocess = !userPerms || userPerms.has("doc:reprocess") || userPerms.has("admin:manage");
  const canDiscard = !userPerms || userPerms.has("doc:discard") || userPerms.has("admin:manage");
  const canApprove = !userPerms || userPerms.has("doc:approve") || userPerms.has("admin:manage");

  if (permitted.has("request_reprocessing") && canReprocess) {
    actions.push(el("button", { type: "button", class: "btn ghost", onclick: () => $("#reprocess-dialog").showModal() },
      icon("refresh"), ACTION_LABELS.request_reprocessing));
  }
  actions.push(el("button", {
    type: "button",
    class: "btn ghost",
    title: "Download the validated export for this document",
    onclick: () => downloadAuthenticated(`/api/v1/documents/${id}/export`, `${id}.json`).catch((err) => toast(`Export failed: ${err.message}`, "danger")),
  }, icon("download"), "Export"));
  if (permitted.has("discard_document") && canDiscard) {
    actions.push(el("button", {
      type: "button",
      class: "btn danger",
      onclick: () => askReason("Discard document", "Discarded documents leave the workflow. The file and audit trail are kept.", async (reason) => {
        state.workspace = await api(`/api/v1/documents/${id}/discard`, { method: "POST", body: { reason } });
      }, "Document discarded."),
    }, icon("trash"), ACTION_LABELS.discard_document));
  }
  if (permitted.has("retry_integration") && canReprocess) {
    actions.push(el("button", {
      type: "button",
      class: "btn",
      onclick: () => run(async () => {
        await api(`/api/v1/documents/${id}/integration/retry`, { method: "POST", body: {} });
        await afterMutation();
      }, "Registration retry queued."),
    }, icon("registry"), ACTION_LABELS.retry_integration));
  }
  if (permitted.has("reopen_review") && canApprove) {
    actions.push(el("button", {
      type: "button",
      class: "btn",
      onclick: () => askReason("Reopen review", "The document returns to the review queue.", async (reason) => {
        state.workspace = await api(`/api/v1/documents/${id}/review/reopen`, { method: "POST", body: { reason } });
      }, "Review reopened."),
    }, icon("review"), ACTION_LABELS.reopen_review));
  }
  if (permitted.has("complete_review") && canApprove) {
    actions.push(el("button", { type: "button", class: "btn primary", onclick: () => completeReview() },
      icon("check"), ACTION_LABELS.complete_review));
  }
  nodes.actionBar.replaceChildren(...actions);
}

function renderViewer(ws) {
  const lines = ws.viewer.ocr_text ? ws.viewer.ocr_text.split("\n") : [];
  nodes.viewerMeta.textContent = [
    `${ws.viewer.page_count} page${ws.viewer.page_count === 1 ? "" : "s"}`,
    ws.document_summary.ocr_engine || "",
    ws.document_summary.ocr_confidence !== null && ws.document_summary.ocr_confidence !== undefined
      ? `conf ${percent(ws.document_summary.ocr_confidence)}` : "",
  ].filter(Boolean).join(" · ");

  if (!lines.length) {
    nodes.ocrLines.replaceChildren(emptyState(ws.processing.active ? "scan" : "text", ws.processing.active ? "Reading the document…" : "No text was recognized in this document."));
  } else {
    nodes.ocrLines.replaceChildren(...lines.map((line, index) => el("li", {
      class: state.highlightLine === index ? "highlight" : null,
      "data-line": index,
      text: line || " ",
    })));
  }
  const showText = state.view === "text";
  nodes.ocrLines.hidden = !showText;
  nodes.original.hidden = showText;
  document.querySelectorAll("[data-view]").forEach((tab) => {
    tab.setAttribute("aria-selected", String(tab.dataset.view === state.view));
  });
  if (!showText) renderOriginal(ws);
}

async function renderOriginal(ws) {
  const mime = ws.document_summary.mime_type || "";
  const filename = ws.document_summary.source_filename || "document";

  if (nodes.original.dataset.docId === ws.document_id && nodes.original.dataset.loaded) return;
  nodes.original.dataset.docId = ws.document_id;
  nodes.original.dataset.loaded = "";
  nodes.original.replaceChildren(el("div", { class: "skeleton" }));

  try {
    const blob = await fetchSourceBlob(ws.document_id);
    const src = sourceBlobManager.create(blob);
    nodes.original.dataset.loaded = "true";

    let viewer;
    if (mime.startsWith("image/") && mime !== "image/tiff") {
      viewer = el("img", { src, alt: `Original of ${ws.document_summary.title}` });
    } else if (mime === "application/pdf" || mime === "text/plain") {
      viewer = el("iframe", { src, title: "Original file" });
    } else {
      viewer = el("p", { class: "empty", text: "This file type cannot be previewed in the browser." });
    }
    nodes.original.replaceChildren(
      viewer,
      el("a", { class: "button", href: src, download: filename }, icon("download"), "Download original"),
    );
  } catch (err) {
    nodes.original.replaceChildren(
      el("p", { class: "empty", text: `Could not load original file: ${err.message}` }),
    );
  }
}

function highlightSource(field) {
  if (!field.source_text || !state.workspace?.viewer.ocr_text) return;
  const needle = field.source_text.trim().toLowerCase();
  const lines = state.workspace.viewer.ocr_text.split("\n");
  let index = lines.findIndex((line) => line.trim().toLowerCase() === needle);
  if (index < 0) index = lines.findIndex((line) => line.trim() && needle.includes(line.trim().toLowerCase()));
  if (index < 0) index = lines.findIndex((line) => line.toLowerCase().includes(needle.split(" ")[0]));
  if (index < 0) return;
  state.highlightLine = index;
  state.view = "text";
  renderViewer(state.workspace);
  nodes.ocrLines.querySelector(`[data-line="${index}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
}

function renderFields(ws) {
  const userPerms = state.user?.permissions ? new Set(state.user.permissions) : null;
  const canEdit = !userPerms || userPerms.has("field:edit") || userPerms.has("admin:manage");
  const editable = ws.permitted_actions.includes("correct_field") && canEdit;
  const total = ws.field_panels.length;
  const needing = ws.field_panels.filter((field) => field.review_required).length;
  const done = total - needing;
  nodes.fieldsMeta.textContent = total
    ? needing ? `${needing} of ${total} to verify` : `All ${total} fields clear`
    : "";
  const pct = total ? Math.round((done / total) * 100) : 0;
  nodes.fieldsProgress.hidden = !total;
  nodes.fieldsProgress.style.setProperty("--p", String(pct));
  nodes.fieldsProgress.classList.toggle("complete", total > 0 && !needing);
  nodes.fieldsProgress.firstElementChild.textContent = `${done}/${total}`;
  if (!total) {
    nodes.fieldList.replaceChildren(el("p", { class: "empty" }, icon(ws.processing.active ? "bolt" : "text"), ws.processing.active ? "Fields appear after extraction." : "No fields were extracted for this document."));
    return;
  }
  nodes.fieldList.replaceChildren(...ws.field_panels.map((field) => fieldCard(ws, field, editable)));
}

function fieldCard(ws, field, editable) {
  const inputId = `field-${field.field_code}`;
  const input = el("input", {
    id: inputId,
    type: "text",
    inputmode: ["decimal", "integer"].includes(field.value_type) ? "decimal" : null,
    value: field.current_value ?? "",
    placeholder: field.value_type === "date" ? "YYYY-MM-DD" : "Enter value",
    disabled: !editable,
    spellcheck: "false",
    "aria-describedby": `${inputId}-meta`,
  });
  input.value = field.current_value ?? "";
  input.addEventListener("input", () => input.classList.toggle("dirty", input.value !== (field.current_value ?? "")));

  const save = async (force = false) => {
    const value = input.value.trim();
    const result = await run(async () => {
      try {
        state.workspace = await api(`/api/v1/documents/${ws.document_id}/fields/${field.field_code}`, {
          method: "PUT",
          body: { value: value === "" ? null : value, force },
        });
      } catch (error) {
        if (error.status === 422 && error.body?.error === "VALIDATION_FAILED" && !force) {
          if (window.confirm(`${error.message}\n\nKeep this value anyway?`)) return "force";
          return null;
        }
        throw error;
      }
      renderWorkspace();
      await refreshSide();
      return "saved";
    });
    if (result === "force") await save(true);
    else if (result === "saved") toast(`${field.label} saved.`, "success");
  };

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); save(); }
  });

  const verified = !field.review_required && field.snapshots.some((s) => s.lifecycle_stage === "validated");
  const status = field.review_required
    ? el("span", { class: "pill warn", text: "Verify" })
    : verified
      ? el("span", { class: "pill success", text: "Verified" })
      : field.current_value === null || field.current_value === ""
        ? el("span", { class: "pill neutral", text: "Empty" })
        : el("span", { class: "pill neutral", text: "Extracted" });

  const locate = field.source_text
    ? el("button", { type: "button", class: "small link", title: "Highlight the source line in the OCR text", onclick: () => highlightSource(field) }, icon("locate", "xs"), "Locate")
    : null;

  const buttons = el("div", { class: "field-actions" },
    locate,
    editable && field.review_required && field.current_value
      ? el("button", {
        type: "button",
        class: "small",
        onclick: () => run(async () => {
          state.workspace = await api(`/api/v1/documents/${ws.document_id}/fields/${field.field_code}/confirm`, { method: "POST", body: {} });
          renderWorkspace();
          await refreshSide();
        }, `${field.label} confirmed.`),
      }, icon("check", "xs"), "Confirm")
      : null,
    editable ? el("button", { type: "button", class: "small", onclick: () => save() }, "Save") : null,
  );

  const changed = field.extracted_value !== field.current_value;
  const signal = field.extracted_value === null && field.current_value !== null
    ? "Entered by operator"
    : field.extracted_value === null ? "Not found in text" : percent(field.confidence_score);
  const history = field.snapshots.length > 1 ? el("details", { class: "history" },
    el("summary", {}, icon("chevron-right", "xs"), `History · ${field.snapshots.length} versions`),
    el("ol", {}, ...field.snapshots.map((snapshot) => el("li", {},
      el("strong", { text: snapshot.value ?? "—" }),
      el("span", { class: "item-meta", text: `${snapshot.lifecycle_stage} · ${snapshot.created_by} · ${formatDate(snapshot.created_at)}` }),
    ))),
  ) : null;

  return el("section", { class: `field-card${field.review_required ? " attention" : verified ? " verified" : ""}` },
    el("header", {},
      el("label", { for: inputId }, field.label, field.required ? el("span", { class: "required", title: "Required", text: " *" }) : null,
        el("span", { class: "code", text: field.field_code })),
      status,
    ),
    input,
    el("div", { class: "field-foot" },
      el("p", { id: `${inputId}-meta`, class: "field-signal" },
        field.extracted_value === null ? null : meter(field.confidence_score),
        el("span", { class: field.extracted_value === null ? "item-meta" : "meter-value", text: signal }),
        changed && field.extracted_value ? el("span", { class: "item-meta", text: `was “${field.extracted_value}”` }) : null,
        ...field.review_reason_codes.map((code) => el("span", { class: "tag warn", text: REASON_LABELS[code] || humanize(code) })),
      ),
      buttons,
    ),
    history,
  );
}

function renderExceptions(ws) {
  const open = ws.exception_context.filter((exc) => exc.status === "open").length;
  nodes.tabCountExceptions.textContent = open || "";
  if (!ws.exception_context.length) {
    nodes.docExceptions.replaceChildren(emptyState("shield", "No exceptions for this document."));
    return;
  }
  nodes.docExceptions.replaceChildren(...ws.exception_context.map((exc) => el("li", { class: `card ${exc.status === "open" ? "danger" : ""}` },
    el("strong", {}, humanize(exc.exception_code), el("span", { class: `pill ${exc.status === "open" ? "danger" : "neutral"}`, text: exc.status })),
    el("span", { class: "item-meta", text: [exc.severity, relativeTime(exc.opened_at)].filter(Boolean).join(" · ") }),
    el("p", { text: exc.message }),
    exc.status === "open" ? el("button", {
      type: "button",
      class: "small",
      onclick: () => askReason("Resolve exception", "Describe how the problem was handled.", async (comment) => {
        await api(`/api/v1/exceptions/${exc.exception_id}/resolve`, { method: "POST", body: { comment } });
        await reloadWorkspace();
      }, "Exception resolved."),
    }, icon("check", "xs"), "Mark resolved") : null,
  )));
}

function renderReferences(ws) {
  if (!ws.external_references.length) {
    nodes.docReferences.replaceChildren(emptyState("registry", "Not registered yet. Registration runs automatically after validation."));
    return;
  }
  nodes.docReferences.replaceChildren(...ws.external_references.map((ref) => el("li", { class: "card success" },
    el("strong", {}, el("span", { class: "ref", text: ref.reference_id }), el("span", { class: "pill success", text: ref.status })),
    el("span", { class: "item-meta", text: `${humanize(ref.reference_type)} · ${ref.system_name}` }),
    el("span", { class: "item-meta mono", text: formatDate(ref.synchronized_at) }),
  )));
}

const JOB_TONE = { completed: "success", succeeded: "success", failed: "danger", processing: "info", pending: "neutral", cancelled: "neutral" };

function renderJobs(ws) {
  if (!ws.processing.jobs.length) {
    nodes.docJobs.replaceChildren(emptyState("jobs", "No jobs."));
    return;
  }
  nodes.docJobs.replaceChildren(...ws.processing.jobs.map((job) => el("li", { class: `card${job.status === "failed" ? " danger" : ""}` },
    el("strong", {}, el("span", { class: "mono", text: job.job_type }), el("span", { class: `pill ${JOB_TONE[job.status] || "neutral"}${job.status === "processing" ? " live" : ""}`, text: job.status })),
    el("span", { class: "item-meta", text: `attempt ${job.attempts}/${job.max_attempts} · ${relativeTime(job.updated_at)}` }),
    job.last_error_message ? el("p", { class: "error-text", text: job.last_error_message }) : null,
  )));
}

function renderAudit(ws) {
  if (!ws.audit_timeline.length) {
    nodes.docAudit.replaceChildren(emptyState("audit", "No events recorded yet."));
    return;
  }
  nodes.docAudit.replaceChildren(...[...ws.audit_timeline].reverse().map((event) => {
    const human = event.actor_id && !String(event.actor_id).startsWith("system");
    return el("li", { class: event.outcome === "failure" ? "failure" : human ? "human" : null },
      el("strong", { text: event.event_type }),
      el("span", { class: "item-meta", title: formatDate(event.occurred_at), text: `${event.actor_id} · ${relativeTime(event.occurred_at)}` }),
      event.details_summary ? el("p", { title: event.details_summary, text: event.details_summary }) : null,
    );
  }));
}

// ---------------------------------------------------------------- inspector tabs

function setPanel(panel) {
  state.panel = panel;
  document.querySelectorAll("[data-panel]").forEach((tab) => {
    const selected = tab.dataset.panel === panel;
    tab.setAttribute("aria-selected", String(selected));
    $(`#panel-${tab.dataset.panel}`).hidden = !selected;
  });
}

// ---------------------------------------------------------------- assistant

const SUGGESTIONS = [
  "Why does this document need attention?",
  "Summarize this document",
  "Which fields were corrected?",
  "What is the registration status?",
  "Show the audit history",
];

function renderSuggestions(list = SUGGESTIONS) {
  nodes.assistantSuggestions.replaceChildren(...list.map((prompt) => el("button", {
    type: "button",
    class: "chip",
    text: prompt,
    disabled: !state.selectedId,
    onclick: () => { nodes.assistantPrompt.value = prompt; ask(prompt); },
  })));
}

async function ask(prompt) {
  if (!state.selectedId) return;
  const documentId = state.selectedId;
  nodes.assistantAnswer.hidden = false;
  nodes.assistantAnswer.replaceChildren(el("div", { class: "skeleton" }));
  const card = await run(() => api(`/api/v1/documents/${state.selectedId}/assistant`, { method: "POST", body: { prompt } }));
  if (state.selectedId !== documentId) return;
  if (!card) { nodes.assistantAnswer.hidden = true; return; }
  const tone = card.response_mode === "answer" ? "success" : card.response_mode === "handoff" ? "warn" : "neutral";
  nodes.assistantAnswer.replaceChildren(
    el("header", {}, el("h3", { text: card.title }), el("span", { class: `pill ${tone}`, text: card.response_mode })),
    el("p", { text: card.answer_text }),
    card.citations.length ? el("div", {},
      el("p", { class: "label", text: `Sources · ${card.citations.length}` }),
      el("ol", { class: "citations" }, ...card.citations.map((citation) => el("li", {},
        el("strong", { text: citation.source_label }),
        el("span", { class: "item-meta", text: ` ${citation.locator}` }),
        el("blockquote", { text: citation.evidence_excerpt }),
      ))),
    ) : null,
    card.limitations.length ? el("p", { class: "item-meta", text: card.limitations.join(" ") }) : null,
    el("p", { class: "boundary" }, icon("shield", "xs"), el("span", { text: card.decision_boundary })),
  );
  nodes.assistantPrompt.value = "";
  await reloadWorkspace().catch(() => {});
}

// ---------------------------------------------------------------- commands

async function afterMutation() {
  await reloadWorkspace();
  await refreshSide();
  schedulePoll();
}

async function refreshSide() {
  await Promise.all([refreshStats(), refreshList()]);
}

async function completeReview() {
  const ws = state.workspace;
  const pending = ws.field_panels.filter((field) => field.review_required);
  if (pending.length && !window.confirm(`${pending.length} field(s) are still flagged. Accept their current values and complete the review?`)) {
    return;
  }
  await run(async () => {
    state.workspace = await api(`/api/v1/documents/${ws.document_id}/review/complete`, { method: "POST", body: {} });
    renderWorkspace();
    await refreshSide();
    schedulePoll();
  }, "Review completed. The document is validated.");
}

let reasonHandler = null;
function askReason(title, text, handler, successMessage) {
  $("#reason-title").textContent = title;
  $("#reason-text").textContent = text;
  $("#reason-input").value = "";
  reasonHandler = { handler, successMessage };
  $("#reason-dialog").showModal();
}

$("#reason-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const reason = $("#reason-input").value.trim();
  if (!reason || !reasonHandler) return;
  const { handler, successMessage } = reasonHandler;
  $("#reason-dialog").close();
  await run(async () => {
    await handler(reason);
    renderWorkspace();
    await refreshSide();
    schedulePoll();
  }, successMessage);
});

$("#reprocess-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const scope = new FormData(event.target).get("scope");
  const comment = $("#reprocess-comment").value.trim();
  $("#reprocess-dialog").close();
  await run(async () => {
    await api(`/api/v1/documents/${state.selectedId}/reprocess`, { method: "POST", body: { scope, comment } });
    await afterMutation();
  }, "Reprocessing queued.");
});

// ---------------------------------------------------------------- upload

const uploadInput = $("#upload-files");

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(reader.error || new Error("Could not read the file."));
    reader.readAsDataURL(file);
  });
}

function fileRow(file, status, tone = "") {
  return el("li", { class: `file-row ${tone}`.trim() },
    fileGlyph(file.name, file.type),
    el("span", { class: "name", text: file.name }),
    el("span", { class: "meta", text: status }),
  );
}

function renderSelection() {
  const files = [...uploadInput.files];
  const limit = state.config?.max_upload_bytes;
  $("#upload-selection").replaceChildren(...files.map((file) => (limit && file.size > limit
    ? fileRow(file, `${formatBytes(file.size)} · too large`, "danger")
    : fileRow(file, formatBytes(file.size)))));
  $("#upload-submit").lastChild.textContent = files.length > 1 ? ` Upload ${files.length} files` : " Upload";
}

function openUpload(files) {
  const cfg = state.config;
  if (cfg) {
    $("#upload-institution").value = cfg.defaults.institution_id;
    $("#upload-institution").readOnly = true;
    if (cfg.offices?.length) {
      const current = $("#upload-office");
      const officeSelect = el("select", { id: "upload-office" });
      officeSelect.replaceChildren(...cfg.offices.filter((office) => office.enabled).map((office) =>
        el("option", { value: office.office_id, text: office.name })));
      officeSelect.value = [...officeSelect.options].some((option) => option.value === current.value)
        ? current.value : cfg.defaults.office_id;
      if (!officeSelect.value) officeSelect.selectedIndex = 0;
      current.replaceWith(officeSelect);
    }
    $("#upload-office").value ||= cfg.defaults.office_id;
    const types = cfg.allowed_mime_types.map((type) => type.split("/").pop().toUpperCase()).join(" · ");
    $("#upload-hint").textContent = `${types} — up to ${formatBytes(cfg.max_upload_bytes)} each`;
    uploadInput.accept = cfg.allowed_mime_types.join(",");
  }
  if (files?.length) uploadInput.files = files;
  $("#upload-progress").replaceChildren();
  renderSelection();
  const dialog = $("#upload-dialog");
  if (!dialog.open) dialog.showModal();
}

uploadInput.addEventListener("change", renderSelection);

const dropzone = $("#dropzone");
["dragenter", "dragover"].forEach((type) => dropzone.addEventListener(type, (event) => {
  event.preventDefault();
  dropzone.classList.add("over");
}));
["dragleave", "drop"].forEach((type) => dropzone.addEventListener(type, () => dropzone.classList.remove("over")));
dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  event.stopPropagation();
  if (event.dataTransfer?.files.length) { uploadInput.files = event.dataTransfer.files; renderSelection(); }
});

// Drop files anywhere on the console to start an upload.
let dragDepth = 0;
const hasFiles = (event) => [...(event.dataTransfer?.types || [])].includes("Files");
window.addEventListener("dragenter", (event) => {
  if (!hasFiles(event) || $("#upload-dialog").open) return;
  dragDepth += 1;
  nodes.dropOverlay.hidden = false;
});
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) nodes.dropOverlay.hidden = true;
});
window.addEventListener("dragover", (event) => { if (hasFiles(event)) event.preventDefault(); });
window.addEventListener("drop", (event) => {
  if (!hasFiles(event)) return;
  event.preventDefault();
  dragDepth = 0;
  nodes.dropOverlay.hidden = true;
  if (event.dataTransfer.files.length) openUpload(event.dataTransfer.files);
});

$("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = [...uploadInput.files];
  if (!files.length) return;
  const submit = $("#upload-submit");
  submit.disabled = true;
  const progress = $("#upload-progress");
  progress.replaceChildren();
  $("#upload-selection").replaceChildren();
  let lastId = null;
  let failures = 0;
  for (const file of files) {
    let row = fileRow(file, "uploading…");
    progress.append(row);
    try {
      if (state.config && file.size > state.config.max_upload_bytes) throw new Error("file is too large");
      const result = await api("/api/v1/documents", {
        method: "POST",
        body: {
          filename: file.name,
          mime_type: file.type || null,
          content_base64: await readAsBase64(file),
          document_family: $("#upload-family").value,
          institution_id: $("#upload-institution").value.trim() || null,
          office_id: $("#upload-office").value.trim() || null,
        },
      });
      lastId = result.document_id;
      const next = fileRow(file, "accepted", "success");
      row.replaceWith(next);
      row = next;
    } catch (error) {
      row.replaceWith(fileRow(file, error.message, "danger"));
      failures += 1;
    }
  }
  submit.disabled = false;
  uploadInput.value = "";
  await refreshSide().catch(() => {});
  if (!failures) $("#upload-dialog").close();
  if (lastId) {
    toast(`${files.length - failures} file(s) submitted for processing.`, "success");
    setList("documents");
    await selectDocument(lastId);
  }
});

// ---------------------------------------------------------------- settings

function openSettings(message) {
  $("#settings-operator").value = settings.operator;
  $("#settings-token").value = settings.token;
  const localeSelect = $("#settings-locale");
  if (localeSelect) {
    const supported = state.branding?.supported_locales?.length
      ? SUPPORTED_LOCALES.filter((l) => state.branding.supported_locales.includes(l.code))
      : SUPPORTED_LOCALES;
    localeSelect.replaceChildren(
      ...supported.map((loc) =>
        el("option", { value: loc.code, text: `${loc.flag} ${loc.name}` })
      )
    );
    localeSelect.value = currentLocale();
  }
  if (state.branding) {
    if (nodes.institutionName) nodes.institutionName.textContent = state.branding.institution_name || "xTRACT";
    if (nodes.institutionTagline) nodes.institutionTagline.textContent = state.branding.tagline || "";
  }
  const engines = state.config?.ocr_engines || [];
  const list = $("#settings-engines");
  if (message) {
    list.replaceChildren(el("p", { class: "pill warn", text: message }));
  } else {
    list.replaceChildren(...engines.map((engine) => el("div", { class: "engine" },
      el("span", { text: engine.engine_id }),
      engine.available
        ? el("span", { class: "pill success", text: "available" })
        : el("span", { class: "reason", text: engine.reason }),
    )));
  }
  if (nodes.userRoleDisplay) {
    const roles = state.user?.roles || ["operator"];
    const roleLabels = roles.map((r) => t(`role_${r}`) || r).join(", ");
    nodes.userRoleDisplay.textContent = `${roleLabels} (${state.user?.institution_id || state.config?.defaults?.institution_id || "default"})`;
  }
  const dialog = $("#settings-dialog");
  if (!dialog.open) dialog.showModal();
}

function renderOperator() {
  const name = state.user?.display_name || settings.operator;
  nodes.operatorInitials.textContent = initials(name);
  const primaryRole = (state.user?.roles?.[0] ? t(`role_${state.user.roles[0]}`) : "") || "";
  const tipText = primaryRole ? `${name} [${primaryRole}] · ${t("nav_settings")}` : `${name} · ${t("nav_settings")}`;
  $("#settings-button").dataset.tip = tipText;
}

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  settings.operator = $("#settings-operator").value.trim() || "operator";
  settings.token = $("#settings-token").value.trim();
  const selectedLocale = $("#settings-locale")?.value;
  if (selectedLocale && selectedLocale !== currentLocale()) {
    setLocale(selectedLocale);
  }
  renderOperator();
  $("#settings-dialog").close();
  await boot();
});

onLocaleChange(() => {
  applyI18n();
  renderOperator();
  if (state.config) {
    nodes.stageFilter.replaceChildren(
      el("option", { value: "", text: t("stage_filter_all") }),
      ...state.config.workflow_stages.map((stage) =>
        el("option", { value: stage, text: STAGE_LABELS[stage] || stage })
      )
    );
    nodes.stageFilter.value = state.stage;
    $("#upload-family").replaceChildren(
      el("option", { value: "auto", text: t("dialog_upload_auto") }),
      ...state.config.document_families.map((family) =>
        el("option", { value: family.family_code, text: family.display_name })
      )
    );
  }
  setList(state.list);
  renderSuggestions();
  if (state.workspace) {
    renderWorkspace();
  }
});

// ---------------------------------------------------------------- polling

function schedulePoll(delay = POLL_BUSY_MS) {
  window.clearTimeout(state.pollTimer);
  if (demoMode) return;
  state.pollTimer = window.setTimeout(poll, delay);
}

async function poll() {
  if (!state.config) { await boot(); return; }
  let busy = false;
  try {
    const stats = await refreshStats();
    const jobs = stats.jobs_by_status || {};
    busy = stats.processing > 0 || (jobs.pending || 0) + (jobs.processing || 0) > 0
      || Boolean(state.workspace?.processing.active);
    const editing = document.querySelector("dialog[open]") || document.activeElement?.matches("input, textarea, select");
    if (!editing) {
      await refreshList();
      if (busy || state.workspace?.processing.active) await reloadWorkspace();
    }
  } catch {
    /* keep polling; transient network errors are expected while the server restarts */
  }
  schedulePoll(busy ? POLL_BUSY_MS : POLL_IDLE_MS);
}

// ---------------------------------------------------------------- wiring

// Give each tab group the standard arrow-key, Home, and End navigation.
document.querySelectorAll('[role="tablist"]').forEach((group) => {
  const tabs = [...group.querySelectorAll('[role="tab"]')];
  const sync = () => tabs.forEach((tab) => { tab.tabIndex = tab.getAttribute("aria-selected") === "true" ? 0 : -1; });
  sync();
  group.addEventListener("click", () => queueMicrotask(sync));
  group.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const current = tabs.indexOf(document.activeElement);
    if (current < 0) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
      : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next].click();
    tabs[next].focus();
    sync();
  });
});

document.querySelectorAll("[data-list]").forEach((item) => item.addEventListener("click", () => setList(item.dataset.list)));
document.querySelectorAll("[data-list-jump]").forEach((item) => item.addEventListener("click", () => setList(item.dataset.listJump)));
document.querySelectorAll("[data-panel]").forEach((tab) => tab.addEventListener("click", () => setPanel(tab.dataset.panel)));
document.querySelectorAll("[data-view]").forEach((tab) => tab.addEventListener("click", () => {
  state.view = tab.dataset.view;
  if (state.workspace) renderViewer(state.workspace);
}));
document.querySelectorAll("dialog [data-close]").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
document.querySelectorAll("[data-open-upload]").forEach((button) => button.addEventListener("click", () => openUpload()));
$("#upload-button").addEventListener("click", () => openUpload());
$("#settings-button").addEventListener("click", () => openSettings());
$("#shortcuts-button").addEventListener("click", () => $("#shortcuts-dialog").showModal());
nodes.themeButton.addEventListener("click", cycleTheme);

nodes.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  state.query = nodes.searchText.value.trim();
  state.stage = nodes.stageFilter.value;
  setList("documents");
});
nodes.stageFilter.addEventListener("change", () => filterByStage(nodes.stageFilter.value));

nodes.assistantForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = nodes.assistantPrompt.value.trim();
  if (prompt) ask(prompt);
});

const exportButton = $("#export-button");
const exportMenu = $("#export-menu");
exportButton.addEventListener("click", () => {
  exportMenu.hidden = !exportMenu.hidden;
  exportButton.setAttribute("aria-expanded", String(!exportMenu.hidden));
});
exportMenu.addEventListener("click", async (event) => {
  const link = event.target.closest("[data-export]");
  if (!link) return;
  event.preventDefault();
  exportMenu.hidden = true;
  exportButton.setAttribute("aria-expanded", "false");
  try {
    await downloadAuthenticated(link.dataset.export);
  } catch (err) {
    toast(`Export failed: ${err.message}`, "danger");
  }
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".menu")) {
    exportMenu.hidden = true;
    exportButton.setAttribute("aria-expanded", "false");
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !exportMenu.hidden) {
    exportMenu.hidden = true;
    exportButton.setAttribute("aria-expanded", "false");
    exportButton.focus();
    return;
  }
  const typing = event.target.closest?.("input, textarea, select, [contenteditable]");
  if (typing || event.metaKey || event.ctrlKey || event.altKey || document.querySelector("dialog[open]")) {
    if (event.key === "Escape" && event.target === nodes.searchText) nodes.searchText.blur();
    return;
  }
  const key = event.key.toLowerCase();
  const actions = {
    "/": () => { nodes.searchText.focus(); nodes.searchText.select(); },
    u: () => openUpload(),
    j: () => moveSelection(1),
    k: () => moveSelection(-1),
    1: () => setList("queue"),
    2: () => setList("documents"),
    3: () => setList("exceptions"),
    t: cycleTheme,
    "?": () => $("#shortcuts-dialog").showModal(),
    o: () => {
      if (!state.workspace) return;
      state.view = state.view === "text" ? "original" : "text";
      renderViewer(state.workspace);
    },
    a: () => { if (state.workspace) { setPanel("assistant"); nodes.assistantPrompt.focus(); } },
  };
  if (actions[key]) {
    event.preventDefault();
    actions[key]();
  }
});

setAuthHandler(openSettings);

async function boot() {
  if (demoMode) {
    $("#settings-token").disabled = true;
    $("#settings-token").removeAttribute("data-i18n-placeholder");
    $("#settings-token").placeholder = "No API token needed in demo mode";
    const uploadSecurity = document.querySelector('[data-i18n="dialog_upload_security"], [data-demo-note="dialog_upload_security"]');
    uploadSecurity.dataset.demoNote = "dialog_upload_security";
    uploadSecurity.removeAttribute("data-i18n");
    uploadSecurity.textContent = "Browser memory only · UTF-8 text · manual field entry";
    const tokenNote = document.querySelector('[data-i18n="dialog_settings_token_meta"], [data-demo-note="dialog_settings_token_meta"]');
    tokenNote.dataset.demoNote = "dialog_settings_token_meta";
    tokenNote.removeAttribute("data-i18n");
    tokenNote.textContent = "No server or authentication service is connected in this demo.";
    for (const key of ["empty_desc", "drop_overlay_desc"]) {
      const note = document.querySelector(`[data-i18n="${key}"], [data-demo-note="${key}"]`);
      note.dataset.demoNote = key;
      note.removeAttribute("data-i18n");
      note.textContent = "Try the sample documents or add a UTF-8 .txt file. OCR, extraction, assistant, and registration are simulated. Changes reset when you reload.";
    }
  }
  initLocale(state.branding?.default_locale);
  applyI18n();
  renderOperator();
  applyTheme(currentTheme());
  try {
    state.user = await api("/api/v1/auth/me");
    if (state.user) {
      if (state.user.display_name && !window.sessionStorage.getItem("xtract.operator")) {
        settings.operator = state.user.display_name;
      }
      renderOperator();
    }
  } catch {
    state.user = null;
  }
  try {
    const branding = await api("/api/v1/branding");
    state.branding = branding;
    applyBranding(branding);
    if (branding?.default_locale && !window.localStorage.getItem("xtract.locale")) {
      setLocale(branding.default_locale, false);
    }
  } catch {
    /* fallback to static defaults */
  }
  try {
    state.config = await api("/api/v1/config");
    if (state.config?.institution && !state.branding) {
      state.branding = state.config.institution;
      applyBranding(state.config.institution);
      if (state.config.institution?.default_locale && !window.localStorage.getItem("xtract.locale")) {
        setLocale(state.config.institution.default_locale, false);
      }
    }
  } catch (error) {
    nodes.list.replaceChildren(emptyState("exception", `Cannot reach the API: ${error.message}`));
    schedulePoll(POLL_IDLE_MS);
    return;
  }
  nodes.stageFilter.replaceChildren(
    el("option", { value: "", text: t("stage_filter_all") }),
    ...state.config.workflow_stages.map((stage) => el("option", { value: stage, text: STAGE_LABELS[stage] || stage })),
  );
  nodes.stageFilter.value = state.stage;
  $("#upload-family").replaceChildren(
    el("option", { value: "auto", text: t("dialog_upload_auto") }),
    ...state.config.document_families.map((family) => el("option", { value: family.family_code, text: family.display_name })),
  );
  if (nodes.packNameDisplay && state.config) {
    const packs = state.config.available_packs || [];
    const active = packs.find((p) => p.is_active || p.pack_id === state.config.config_pack)
      || { name: state.config.config_pack || "General International", country_code: state.branding?.country_code || "XX" };
    nodes.packNameDisplay.textContent = `${active.name} [${active.country_code}]`;
  }
  renderEngineStatus();
  renderSuggestions();
  await refreshSide().catch((error) => toast(error.message, "danger"));
  const stats = await refreshStats().catch(() => null);
  const linked = readLocation();
  if (linked.list) setList(linked.list);
  else if (stats && !stats.pending_review && stats.documents_total) setList("documents");
  const documentId = state.selectedId || linked.doc || (demoMode ? state.listIds[0] : null);
  if (documentId) await selectDocument(documentId);
  schedulePoll();
}

nodes.list.replaceChildren(...Array.from({ length: 4 }, () => el("li", { class: "skeleton" })));
boot();
