export const API = "/api";

/**
 * An HTTP failure with the backend's own `detail` made readable. `status` is
 * kept so callers can treat expected conflicts (409 already running, 404
 * already stopped, 429 at capacity) as outcomes rather than errors.
 */
export class ApiError extends Error {
  constructor(status, detail, path) {
    super(detail || `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.path = path;
  }
}

// ---------------------------------------------------------------------------
// Client-side API call log for the Logs dock's "API calls" tab. A bounded
// ring buffer at the single choke point every request passes through --
// nothing is sent anywhere.
// ---------------------------------------------------------------------------
const CALL_LOG_MAX = 400;
const callLog = [];
const callLogSubscribers = new Set();
let callSeq = 0;

function recordCall(entry) {
  const row = { seq: ++callSeq, ts: Date.now() / 1000, ...entry };
  callLog.push(row);
  if (callLog.length > CALL_LOG_MAX) callLog.shift();
  for (const cb of callLogSubscribers) {
    try {
      cb(row);
    } catch {
      // a broken subscriber must not break request logging
    }
  }
}

export function getCallLog() {
  return callLog.slice();
}

export function subscribeCallLog(cb) {
  callLogSubscribers.add(cb);
  return () => callLogSubscribers.delete(cb);
}

function readableDetail(body, fallback) {
  const detail = body?.detail ?? body;
  if (detail == null) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "string" ? item : item?.msg ? `${(item.loc || []).slice(1).join(".")} ${item.msg}`.trim() : JSON.stringify(item)))
      .join("; ");
  }
  return JSON.stringify(detail);
}

/**
 * fetch() wrapper for the backend. `json` sends a JSON body; `body` is passed
 * through untouched (FormData, SDP text). Returns parsed JSON, text, or null
 * for 204.
 */
export async function api(path, { method = "GET", json, body, headers, signal } = {}) {
  const started = performance.now();
  const init = { method, credentials: "same-origin", signal, headers: { ...headers } };
  if (json !== undefined) {
    init.body = JSON.stringify(json);
    init.headers["Content-Type"] = "application/json";
  } else if (body !== undefined) {
    init.body = body;
  }

  let resp;
  try {
    resp = await fetch(API + path, init);
  } catch (err) {
    if (err?.name !== "AbortError") {
      recordCall({ method, path, status: 0, ms: Math.round(performance.now() - started), error: String(err) });
    }
    throw err;
  }

  const ms = Math.round(performance.now() - started);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = readableDetail(await resp.json(), resp.statusText);
    } catch {
      // not JSON
    }
    recordCall({ method, path, status: resp.status, ms, error: detail });
    if (resp.status === 401 && path !== "/auth/login" && path !== "/auth/me") {
      window.dispatchEvent(new CustomEvent("sentinel:unauthorised"));
    }
    throw new ApiError(resp.status, detail, path);
  }

  recordCall({ method, path, status: resp.status, ms });
  if (resp.status === 204) return null;
  const contentType = resp.headers.get("content-type") || "";
  return contentType.includes("application/json") ? resp.json() : resp.text();
}

/** True when an error is an ApiError with one of the given statuses. */
export function isStatus(error, ...statuses) {
  return error instanceof ApiError && statuses.includes(error.status);
}
