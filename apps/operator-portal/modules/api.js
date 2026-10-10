/**
 * API client and session authentication for xTRACT Operator Portal.
 * Enforces Authorization: Bearer headers and avoids URL token leakage.
 */

export const demoMode = typeof document !== "undefined" && document.querySelector('meta[name="xtract-mode"]')?.content === "demo";

async function demoAdapter() {
  const { getDemoAdapter } = await import("./demo.js");
  return getDemoAdapter(() => settings.operator);
}

export async function fetchDownload(path) {
  if (demoMode) return (await demoAdapter()).download(path);
  const headers = { "X-Operator-Id": settings.operator };
  if (settings.token) headers.Authorization = `Bearer ${settings.token}`;
  return fetch(path, { headers });
}

function readLocalStorage(key) {
  try { return window.localStorage.getItem(key); } catch { return null; }
}

function writeLocalStorage(key, value) {
  try { window.localStorage.setItem(key, value); } catch { /* unavailable */ }
}

function readSessionStorage(key) {
  try { return window.sessionStorage.getItem(key); } catch { return null; }
}

function writeSessionStorage(key, value) {
  try {
    if (value) window.sessionStorage.setItem(key, value);
    else window.sessionStorage.removeItem(key);
  } catch { /* unavailable */ }
}

export const settings = {
  get operator() { return readLocalStorage(demoMode ? "xtract.demo.operator" : "xtract.operator") || "operator"; },
  set operator(value) { writeLocalStorage(demoMode ? "xtract.demo.operator" : "xtract.operator", value); },
  // Bearer tokens are kept in session storage to avoid persistent credential leaks
  get token() { if (demoMode) return ""; return readSessionStorage("xtract.token") || ""; },
  set token(value) { if (demoMode) return; writeSessionStorage("xtract.token", value); },
};

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `Request failed (${status})`);
    this.status = status;
    this.body = body;
  }
}

let onAuthRequired = null;

export function setAuthHandler(handler) {
  onAuthRequired = handler;
}

export async function api(path, { method = "GET", body } = {}) {
  if (demoMode) return (await demoAdapter()).request(path, { method, body });
  const headers = { "X-Operator-Id": settings.operator };
  if (settings.token) headers.Authorization = `Bearer ${settings.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { message: text };
  }

  if (!response.ok) {
    if (response.status === 401 && onAuthRequired) {
      onAuthRequired("Enter the API token configured on the server.");
    }
    throw new ApiError(response.status, data);
  }
  return data;
}

export async function fetchSourceBlob(documentId) {
  const response = await fetchDownload(`/api/v1/documents/${documentId}/source`);
  if (!response.ok) {
    if (response.status === 401 && onAuthRequired) {
      onAuthRequired("Enter the API token configured on the server.");
    }
    throw new ApiError(response.status, await response.json().catch(() => ({})));
  }
  return await response.blob();
}

export class BlobUrlManager {
  constructor() {
    this.activeUrl = null;
  }

  create(blob) {
    this.revoke();
    this.activeUrl = URL.createObjectURL(blob);
    return this.activeUrl;
  }

  revoke() {
    if (this.activeUrl) {
      URL.revokeObjectURL(this.activeUrl);
      this.activeUrl = null;
    }
  }
}

export const sourceBlobManager = new BlobUrlManager();
