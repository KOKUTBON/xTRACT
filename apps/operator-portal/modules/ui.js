import {
  t,
  currentLocale,
  getStageLabel,
  getReasonLabel,
  getActionLabel,
  getLifecycleSteps,
} from "./i18n.js";

export const STAGE_LABELS = new Proxy({}, {
  get: (_, prop) => (typeof prop === "string" ? getStageLabel(prop) : undefined),
});

export const STAGE_TONE = {
  acquired: "info",
  ocr_executed: "info",
  to_be_verified: "warn",
  validated: "success",
  protocol_pending: "info",
  protocol_registered: "success",
  discarded: "neutral",
  failed: "danger",
};

export const REASON_LABELS = new Proxy({}, {
  get: (_, prop) => (typeof prop === "string" ? getReasonLabel(prop) : undefined),
});

export const ACTION_LABELS = new Proxy({}, {
  get: (_, prop) => (typeof prop === "string" ? getActionLabel(prop) : undefined),
});

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function percent(value) {
  return value === null || value === undefined ? "n/a" : `${Math.round(value * 100)}%`;
}

export function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(currentLocale() || undefined);
}

export function stagePill(stage) {
  const busy = ["acquired", "ocr_executed", "protocol_pending"].includes(stage);
  return el("span", { class: `pill ${STAGE_TONE[stage] || "neutral"}${busy ? " live" : ""}`, text: STAGE_LABELS[stage] || stage });
}

export const STAGE_ICONS = {
  acquired: "scan",
  ocr_executed: "bolt",
  to_be_verified: "review",
  validated: "check-circle",
  protocol_pending: "registry",
  protocol_registered: "shield",
  discarded: "trash",
  failed: "exception",
};

// The happy path a document walks; used for the lifecycle stepper.
export const LIFECYCLE = new Proxy([], {
  get: (_, prop) => {
    const steps = getLifecycleSteps();
    if (prop === "length") return steps.length;
    if (prop === Symbol.iterator) return () => steps[Symbol.iterator]();
    if (typeof prop === "string" && !Number.isNaN(Number(prop))) return steps[Number(prop)];
    return typeof steps[prop] === "function" ? steps[prop].bind(steps) : steps[prop];
  },
});

const SVG_NS = "http://www.w3.org/2000/svg";

export function icon(name, size = "sm") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", `icon ${size}`);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

export function fileKind(filename = "", mime = "") {
  const ext = (filename.split(".").pop() || "").toLowerCase();
  if (mime === "application/pdf" || ext === "pdf") return { kind: "pdf", label: "PDF" };
  if (mime.startsWith("image/") || ["png", "jpg", "jpeg", "tif", "tiff", "webp", "bmp", "gif"].includes(ext)) {
    return { kind: "img", label: (ext === "jpeg" ? "JPG" : ext || "IMG").toUpperCase().slice(0, 4) };
  }
  return { kind: "txt", label: (ext && ext.length <= 4 ? ext : "TXT").toUpperCase() };
}

export function fileGlyph(filename, mime, size = "") {
  const { kind, label } = fileKind(filename, mime);
  return el("span", { class: `file-glyph ${size}`.trim(), "data-kind": kind, "aria-hidden": "true", text: label });
}

// Ten-segment confidence meter echoing the pixel squares in the mark.
export function meter(value) {
  const known = value !== null && value !== undefined;
  const filled = known ? Math.round(Math.max(0, Math.min(1, value)) * 10) : 0;
  const node = el("span", { class: `meter${!known ? " none" : value < 0.7 ? " low" : ""}`, role: "img", "aria-label": known ? `Confidence ${percent(value)}` : "No confidence score" });
  for (let i = 0; i < 10; i += 1) node.append(el("i", { class: i < filled ? "on" : null }));
  return node;
}

export function initials(name = "") {
  const parts = name.trim().split(/[\s._-]+/).filter(Boolean);
  if (!parts.length) return "OP";
  return (parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[1][0]).toUpperCase();
}

export function relativeTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(currentLocale() || undefined, { numeric: "auto" });
  if (seconds < 45) return formatter.format(0, "second");
  const units = [["year", 31536000], ["month", 2592000], ["day", 86400], ["hour", 3600], ["minute", 60]];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return formatter.format(-Math.round(seconds / size), unit);
  }
  return formatter.format(0, "second");
}
