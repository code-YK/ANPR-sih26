import { useCallback, useEffect, useRef, useState } from "react";

import { API, getFeLogs, subscribeFeLogs } from "../api.js";

// Keep only the most recent lines per tab: this is a live tail, not a
// scrollback archive. In-memory only, and dropped entirely when the panel's
// component unmounts (sign-out / reload) -- nothing is persisted.
const MAX_LINES = 50;

const TABS = [
  { id: "be", label: "BE", title: "Backend / server logs" },
  { id: "ai", label: "AI inference", title: "ANPR / person worker logs" },
  { id: "fe", label: "FE", title: "Frontend API calls" },
];

function fmtTime(ts) {
  // ts is epoch seconds (float). Show HH:MM:SS.mmm, local.
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

function levelClass(level) {
  const l = (level || "").toUpperCase();
  if (l === "ERROR" || l === "CRITICAL") return "log-error";
  if (l === "WARNING") return "log-warn";
  if (l === "DEBUG") return "log-muted";
  return "";
}

function statusClass(status) {
  if (status === 0) return "log-error"; // network failure
  if (status >= 500) return "log-error";
  if (status >= 400) return "log-warn";
  if (status >= 200 && status < 300) return "log-ok";
  return "";
}

// Green for a line that reports success, red for one that reports a failure,
// by the words in the message itself. Deliberately keyed on text, not on
// numbers, so a worker's "500 frames" is never mistaken for HTTP 500.
const OK_RE = /(200 ok|\bconnected\b|confirmed|\bsuccess|\bstarted\b|\brunning\b|\bready\b|resolved|\bok\b)/i;
const ERR_RE = /(error|exception|traceback|\bfail|refused|timed out|\btimeout\b|stall|unavailable|denied|unauthoris|forbidden|not found|bad gateway|internal server error|\bcrash|rejected)/i;

function contentClass(text) {
  if (!text) return "";
  if (ERR_RE.test(text)) return "log-error"; // failure wins over success
  if (OK_RE.test(text)) return "log-ok";
  return "";
}

export default function LogsPanel() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("be");
  // One line array per tab so switching tabs doesn't lose the others.
  const [lines, setLines] = useState({ be: [], ai: [], fe: [] });
  const [connected, setConnected] = useState(false);

  const rootRef = useRef(null);
  const scrollRef = useRef(null);
  const stickToBottom = useRef(true);

  const append = useCallback((tabId, rows) => {
    setLines((prev) => {
      const next = prev[tabId].concat(rows);
      if (next.length > MAX_LINES) next.splice(0, next.length - MAX_LINES);
      return { ...prev, [tabId]: next };
    });
  }, []);

  // Collapse when clicking anywhere outside the panel (icon included -- the
  // icon has its own toggle handler that runs first and wins).
  useEffect(() => {
    if (!open) return undefined;
    function onDown(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // FE tab: fed from the client-side api() ring buffer, not the network.
  // Seed once with the existing buffer, then subscribe to new calls -- this
  // runs regardless of which tab is visible so the FE history is complete
  // whenever the operator switches to it.
  useEffect(() => {
    setLines((prev) => ({ ...prev, fe: getFeLogs().slice(-MAX_LINES) }));
    const unsub = subscribeFeLogs((row) => append("fe", [row]));
    return unsub;
  }, [append]);

  // BE / AI tabs: a single EventSource for whichever of the two is active,
  // opened only while the panel is open. Only one streams at a time so the
  // panel never spends more than one of the browser's ~6 per-origin
  // connections (the same budget the video grid competes for).
  useEffect(() => {
    if (!open || tab === "fe") {
      setConnected(false);
      return undefined;
    }
    const url = tab === "be" ? `${API}/logs/backend` : `${API}/logs/workers`;
    // Bind the tab this stream belongs to, and ignore any frame that arrives
    // after teardown -- so a message still in flight when the operator
    // switches tabs can never land in the wrong tab's buffer.
    const streamTab = tab;
    let closed = false;
    const es = new EventSource(url, { withCredentials: true });
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false); // browser auto-reconnects
    es.onmessage = (evt) => {
      if (closed) return;
      try {
        append(streamTab, [JSON.parse(evt.data)]);
      } catch {
        // ignore a malformed frame rather than dropping the stream
      }
    };
    return () => {
      closed = true;
      es.close();
    };
  }, [open, tab, append]);

  // A fresh view always starts pinned to the newest line: opening the panel,
  // or switching tabs, re-arms auto-scroll even if the operator had scrolled
  // up in the tab they were just looking at.
  useEffect(() => {
    stickToBottom.current = true;
  }, [tab, open]);

  // Follow the newest line as it arrives, but only while pinned to the
  // bottom -- once the operator scrolls up to read history, stop yanking
  // them back down. Scrolling back to the bottom re-arms it (see onScroll).
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [lines, tab]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  const current = lines[tab];

  return (
    <div className="logs-root" ref={rootRef}>
      {open && (
        <div className="logs-panel" role="dialog" aria-label="Live logs">
          <div className="logs-tabs">
            {TABS.map((t) => (
              <button
                key={t.id}
                title={t.title}
                className={t.id === tab ? "logs-tab active" : "logs-tab"}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
            <span className="logs-spacer" />
            {tab !== "fe" && (
              <span className={connected ? "logs-conn on" : "logs-conn"} title={connected ? "streaming" : "connecting…"}>
                ●
              </span>
            )}
            <button className="logs-clear" title="Clear this tab" onClick={() => setLines((p) => ({ ...p, [tab]: [] }))}>
              clear
            </button>
          </div>

          <div className="logs-body" ref={scrollRef} onScroll={onScroll}>
            {current.length === 0 ? (
              <div className="logs-empty">No {tab === "fe" ? "API calls" : "log lines"} yet.</div>
            ) : (
              current.map((row) =>
                tab === "fe" ? (
                  <div key={row.seq} className="logs-line">
                    <span className="logs-ts">{fmtTime(row.ts)}</span>
                    <span className={`logs-status ${statusClass(row.status)}`}>{row.status || "ERR"}</span>
                    <span className="logs-method">{row.method}</span>
                    <span className="logs-msg">
                      {row.path}
                      <span className="logs-dim"> · {row.ms}ms</span>
                      {row.error ? <span className="log-error"> · {row.error}</span> : null}
                    </span>
                  </div>
                ) : tab === "be" ? (
                  // An ERROR/WARNING level colours the whole line; otherwise
                  // fall back to what the message says (green ok / red failure).
                  <div key={row.seq} className={`logs-line ${levelClass(row.level) || contentClass(row.msg)}`}>
                    <span className="logs-ts">{fmtTime(row.ts)}</span>
                    <span className="logs-level">{row.level}</span>
                    <span className="logs-msg">
                      <span className="logs-dim">{row.logger} </span>
                      {row.msg}
                    </span>
                  </div>
                ) : (
                  <div key={`${row.ts}-${row.msg}`} className={`logs-line ${contentClass(row.msg)}`}>
                    <span className="logs-ts">{fmtTime(row.ts)}</span>
                    <span className="logs-source">{row.source}</span>
                    <span className="logs-msg">{row.msg}</span>
                  </div>
                )
              )
            )}
          </div>
        </div>
      )}

      <button
        className={open ? "logs-fab open" : "logs-fab"}
        title="Live logs"
        aria-label="Toggle live logs"
        onClick={() => setOpen((v) => !v)}
      >
        {/* terminal glyph */}
        <span aria-hidden>{"⌘_"}</span>
        <span className="logs-fab-label">Logs</span>
      </button>
    </div>
  );
}
