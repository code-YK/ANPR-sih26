import { Eraser, TerminalSquare, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { IconButton, Segmented } from "../../components/ui.jsx";
import { API, getCallLog, subscribeCallLog } from "../../lib/api/client.js";
import { useUiStore } from "../../lib/uiStore.js";
import styles from "./Logs.module.css";

const MAX_LINES = 200;

const TABS = [
  { value: "be", label: "Backend" },
  { value: "ai", label: "AI workers" },
  { value: "fe", label: "API calls" },
];

const OK_RE = /(200 ok|\bconnected\b|confirmed|\bsuccess|\bstarted\b|\brunning\b|\bready\b|resolved|\bok\b)/i;
const ERR_RE = /(error|exception|traceback|\bfail|refused|timed out|\btimeout\b|stall|unavailable|denied|unauthoris|forbidden|not found|bad gateway|internal server error|\bcrash|rejected)/i;

function fmtTs(ts) {
  const d = new Date(ts * 1000);
  return `${d.toLocaleTimeString([], { hour12: false })}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

function toneFor(row, tab) {
  if (tab === "fe") {
    if (row.status === 0 || row.status >= 500) return "critical";
    if (row.status >= 400) return "pending";
    return "live";
  }
  const level = String(row.level || "").toUpperCase();
  if (level === "ERROR" || level === "CRITICAL") return "critical";
  if (level === "WARNING") return "pending";
  if (ERR_RE.test(row.msg || "")) return "critical";
  if (OK_RE.test(row.msg || "")) return "live";
  return null;
}

/**
 * Live logs: this backend's own log output, the AI worker logs, and this
 * browser's API calls. The server streams (SSE) only while the panel is open,
 * and only one at a time, so the panel costs a single connection.
 */
export default function LogsDock() {
  const open = useUiStore((state) => state.logsOpen);
  const setOpen = useUiStore((state) => state.setLogsOpen);
  const tab = useUiStore((state) => state.logsTab);
  const setTab = useUiStore((state) => state.setLogsTab);
  const [lines, setLines] = useState({ be: [], ai: [], fe: [] });
  const [connected, setConnected] = useState(false);
  const scrollRef = useRef(null);
  const pinned = useRef(true);

  const append = useCallback((key, rows) => {
    setLines((previous) => {
      const next = previous[key].concat(rows);
      if (next.length > MAX_LINES) next.splice(0, next.length - MAX_LINES);
      return { ...previous, [key]: next };
    });
  }, []);

  // The call log is buffered by the API client, so the dock only needs to
  // follow it while open -- a closed dock no longer re-renders per request.
  useEffect(() => {
    if (!open) return undefined;
    setLines((previous) => ({ ...previous, fe: getCallLog().slice(-MAX_LINES) }));
    return subscribeCallLog((row) => append("fe", [row]));
  }, [append, open]);

  useEffect(() => {
    if (!open || tab === "fe") {
      setConnected(false);
      return undefined;
    }
    const streamTab = tab;
    let closed = false;
    const source = new EventSource(`${API}/logs/${tab === "be" ? "backend" : "workers"}`, { withCredentials: true });
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (event) => {
      if (closed) return;
      try {
        append(streamTab, [JSON.parse(event.data)]);
      } catch {
        // skip a malformed frame
      }
    };
    return () => {
      closed = true;
      source.close();
    };
  }, [open, tab, append]);

  useEffect(() => {
    pinned.current = true;
  }, [tab, open]);

  useEffect(() => {
    const element = scrollRef.current;
    if (element && pinned.current) element.scrollTop = element.scrollHeight;
  }, [lines, tab, open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  const rows = lines[tab];

  return (
    <div className={styles.dock}>
      <AnimatePresence>
        {open && (
          <motion.section
            key="logs"
            className={styles.panel}
            aria-label="Live logs"
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, transition: { duration: 0.15 } }}
            transition={{ type: "spring", duration: 0.35, bounce: 0 }}
          >
            <header className={styles.header}>
              <Segmented size="sm" label="Log source" value={tab} onChange={setTab} options={TABS} />
              <span className={styles.status} data-on={tab === "fe" || connected || undefined}>
                {tab === "fe" ? "this browser" : connected ? "streaming" : "connecting"}
              </span>
              <IconButton label="Clear" size="sm" onClick={() => setLines((previous) => ({ ...previous, [tab]: [] }))}>
                <Eraser />
              </IconButton>
              <IconButton label="Close logs" size="sm" onClick={() => setOpen(false)}>
                <X />
              </IconButton>
            </header>
            <div
              className={styles.body}
              ref={scrollRef}
              onScroll={() => {
                const element = scrollRef.current;
                if (element) pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 40;
              }}
            >
              {rows.length === 0 ? (
                <p className={styles.empty}>No {tab === "fe" ? "API calls" : "log lines"} yet.</p>
              ) : (
                rows.map((row, index) => {
                  const tone = toneFor(row, tab);
                  return (
                    <div key={row.seq ?? `${row.ts}-${index}`} className={styles.line} data-tone={tone}>
                      <span className={styles.ts}>{fmtTs(row.ts)}</span>
                      {tab === "fe" ? (
                        <>
                          <span className={styles.tag}>{row.status || "ERR"}</span>
                          <span className={styles.tag}>{row.method}</span>
                          <span className={styles.msg}>
                            {row.path}
                            <span className={styles.dim}> · {row.ms} ms</span>
                            {row.error && <span className={styles.err}> · {row.error}</span>}
                          </span>
                        </>
                      ) : tab === "be" ? (
                        <>
                          <span className={styles.tag}>{row.level}</span>
                          <span className={styles.msg}>
                            <span className={styles.dim}>{row.logger} </span>
                            {row.msg}
                          </span>
                        </>
                      ) : (
                        <>
                          <span className={styles.tag}>{row.source}</span>
                          <span className={styles.msg}>{row.msg}</span>
                        </>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </motion.section>
        )}
      </AnimatePresence>
      <button type="button" className={styles.fab} aria-expanded={open} onClick={() => setOpen(!open)}>
        <TerminalSquare aria-hidden="true" />
        Logs
      </button>
    </div>
  );
}
