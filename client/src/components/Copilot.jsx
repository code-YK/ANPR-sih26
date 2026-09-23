import { Sparkles, ArrowUp, Eraser, X, Square, AlertTriangle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CircleMarker, MapContainer, Tooltip as MapTooltip } from "react-leaflet";

import { API, api } from "../api.js";
import { useAuth } from "../context/AuthContext.jsx";
import { createSseParser, navigationPath, TOOL_LABEL } from "../lib/copilot.js";
import DarkTileLayer from "./DarkTileLayer.jsx";
import { useToast } from "./Toast.jsx";

const SUGGESTIONS = [
  "Which cameras are offline?",
  "Trace a vehicle",
  "What analytics are running?",
  "Show open alerts",
];

// Backend worker modes whose on/off intent lives on the camera row rather
// than in the process table -- stopping one means clearing that column
// first, or the supervisor restarts it on its next tick.
const INTENT_COLUMN = {
  vehicle: "analytics_enabled",
  vehicle_finetuned: "analytics_finetuned_enabled",
};

// --------------------------------------------------------------------------
// Tool result cards
// --------------------------------------------------------------------------

/**
 * "List the running workers, with a stop button in place."
 *
 * Stop is a direct API call, not another model turn: clearing the intent
 * column before stopping the process is a sequence that must not be
 * re-derived, and a click is already an explicit operator action.
 */
function WorkerListCard({ data }) {
  const toast = useToast();
  const [stopping, setStopping] = useState(() => new Set());
  const [stopped, setStopped] = useState(() => new Set());
  const workers = data?.workers ?? [];

  if (workers.length === 0) {
    return <p className="copilot-card-empty">No analytics workers are running.</p>;
  }

  async function stop(worker) {
    const key = `${worker.camera_id}::${worker.backend_mode}`;
    setStopping((previous) => new Set(previous).add(key));
    try {
      const column = INTENT_COLUMN[worker.backend_mode];
      if (column) {
        await api(`/cameras/${worker.camera_id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [column]: false }),
        });
      }
      try {
        await api(
          `/analytics/stop?camera_id=${encodeURIComponent(worker.camera_id)}&mode=${worker.backend_mode}`,
          { method: "POST" },
        );
      } catch (error) {
        // 404 means it was already stopped, which is the desired state.
        if (!String(error.message || error).startsWith("404:")) throw error;
      }
      setStopped((previous) => new Set(previous).add(key));
      toast(`${worker.mode} stopped on ${worker.camera_id}`);
    } catch (error) {
      toast(`Couldn't stop ${worker.mode}: ${error.message || error}`);
    } finally {
      setStopping((previous) => {
        const next = new Set(previous);
        next.delete(key);
        return next;
      });
    }
  }

  return (
    <ul className="copilot-workers">
      {workers.map((worker) => {
        const key = `${worker.camera_id}::${worker.backend_mode}`;
        const isStopping = stopping.has(key);
        const isStopped = stopped.has(key);
        return (
          <li key={key} className="copilot-worker">
            <span
              className={`copilot-dot ${
                isStopped ? "" : worker.running ? "on" : worker.state === "queued" ? "queued" : ""
              }`}
              aria-hidden="true"
            />
            <span className="copilot-worker-meta">
              <span className="copilot-worker-cam">{worker.camera_id}</span>
              <span className="copilot-worker-mode">
                {worker.mode}
                {worker.state === "queued" && worker.queue_position
                  ? ` · queued #${worker.queue_position}`
                  : ""}
              </span>
            </span>
            <button
              type="button"
              className="copilot-stop"
              disabled={isStopping || isStopped}
              onClick={() => stop(worker)}
            >
              {isStopped ? "Stopped" : isStopping ? "Stopping…" : <><Square size={12} /> Stop</>}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Candidate cameras for a place the operator named instead of an id.
 * Tapping a pin answers the assistant's question for them, which beats
 * looking an id up by hand. Cameras without coordinates still appear.
 */
function CameraPickerCard({ data, onPick, disabled }) {
  const cameras = data?.cameras ?? [];
  const placed = cameras.filter((c) => c.latitude != null && c.longitude != null);

  if (cameras.length === 0) {
    return <p className="copilot-card-empty">No cameras matched “{data?.query}”.</p>;
  }

  return (
    <div className="copilot-picker">
      {placed.length > 0 && (
        <MapContainer
          center={[placed[0].latitude, placed[0].longitude]}
          zoom={placed.length === 1 ? 14 : 11}
          className="copilot-map"
        >
          <DarkTileLayer />
          {placed.map((camera) => (
            <CircleMarker
              key={camera.camera_id}
              center={[camera.latitude, camera.longitude]}
              radius={7}
              pathOptions={{ color: "var(--entity)", fillColor: "var(--entity)", fillOpacity: 0.7, weight: 2 }}
              eventHandlers={{ click: () => !disabled && onPick?.(camera) }}
            >
              <MapTooltip>
                {camera.camera_id} · {camera.name}
              </MapTooltip>
            </CircleMarker>
          ))}
        </MapContainer>
      )}
      <ul className="copilot-picks">
        {cameras.map((camera) => (
          <li key={camera.camera_id}>
            <button type="button" disabled={disabled} onClick={() => onPick?.(camera)}>
              <span className="copilot-pick-id">{camera.camera_id}</span>
              <span className="copilot-pick-name">{camera.location || camera.name}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ToolCard({ event, onPick, disabled }) {
  if (!event.result?.ok) return null;
  if (event.render === "worker_list") return <WorkerListCard data={event.result.data} />;
  if (event.render === "camera_picker") {
    return <CameraPickerCard data={event.result.data} onPick={onPick} disabled={disabled} />;
  }
  return null;
}

// --------------------------------------------------------------------------
// Panel
// --------------------------------------------------------------------------

export default function Copilot() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [available, setAvailable] = useState(false);
  const [open, setOpen] = useState(false);
  // The conversation lives here and nowhere else: no localStorage, no server
  // session, so it genuinely ends with the page load.
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeTool, setActiveTool] = useState(null);

  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);

  // Re-checked whenever the signed-in user changes: the first attempt can
  // land before the session cookie exists, and a cached failure would hide
  // the launcher for the rest of the page's life.
  useEffect(() => {
    if (!user) return undefined;
    let cancelled = false;
    api("/copilot/status")
      .then((status) => !cancelled && setAvailable(Boolean(status?.available)))
      .catch(() => !cancelled && setAvailable(false));
    return () => {
      cancelled = true;
    };
  }, [user]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [turns, activeTool]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => event.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const patchLast = useCallback((patch) => {
    setTurns((previous) => {
      if (previous.length === 0) return previous;
      const next = previous.slice();
      next[next.length - 1] = { ...next[next.length - 1], ...patch };
      return next;
    });
  }, []);

  const send = useCallback(
    async (message) => {
      const text = String(message || "").trim();
      if (!text || busy) return;

      const history = turns
        .filter((turn) => turn.content)
        .slice(-20)
        .map((turn) => ({ role: turn.role, content: turn.content }));

      setTurns((previous) => [
        ...previous,
        { role: "user", content: text },
        { role: "assistant", content: "", toolResults: [], pending: true },
      ]);
      setDraft("");
      setBusy(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const response = await fetch(`${API}/copilot/chat`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, transcript: history }),
          signal: controller.signal,
        });

        if (!response.ok) {
          let detail = `Request failed (${response.status})`;
          try {
            detail = (await response.json())?.detail ?? detail;
          } catch {
            // non-JSON error body
          }
          patchLast({ error: detail, pending: false });
          return;
        }

        const parser = createSseParser();
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let answer = "";
        const toolResults = [];

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          for (const event of parser.push(decoder.decode(value, { stream: true }))) {
            if (event.type === "token") {
              answer += event.text;
              patchLast({ content: answer });
            } else if (event.type === "tool_start") {
              setActiveTool(event.tool);
            } else if (event.type === "tool_result") {
              setActiveTool(null);
              toolResults.push(event);
              patchLast({ toolResults: [...toolResults] });
              // Applied as it arrives, so the page is already moving while
              // the model is still writing its sentence.
              if (event.tool === "navigate_to" && event.result?.ok) {
                const path = navigationPath(event.result);
                if (path) navigate(path);
              }
            } else if (event.type === "error") {
              patchLast({ error: event.message });
            }
          }
        }
        patchLast({ pending: false });
      } catch (error) {
        if (error?.name !== "AbortError") {
          patchLast({ error: "Lost connection to the assistant.", pending: false });
        }
      } finally {
        abortRef.current = null;
        setBusy(false);
        setActiveTool(null);
      }
    },
    [busy, navigate, patchLast, turns],
  );

  // A launcher that could only ever produce a 503 is worse than no launcher.
  if (!user || !available) return null;

  function submit(event) {
    event?.preventDefault();
    send(draft);
  }

  return (
    <>
      <button
        type="button"
        className={open ? "copilot-fab open" : "copilot-fab"}
        aria-label={open ? "Close Copilot" : "Open Copilot"}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Sparkles size={16} aria-hidden="true" />
        <span className="copilot-fab-label">Copilot</span>
      </button>

      {open && (
        <aside className="copilot-panel" aria-label="Sentinel Copilot">
          <header className="copilot-head">
            <span className="copilot-title">Copilot</span>
            <span className="copilot-spacer" />
            {turns.length > 0 && (
              <button
                type="button"
                className="copilot-icon"
                title="Clear conversation"
                onClick={() => setTurns([])}
              >
                <Eraser size={14} />
              </button>
            )}
            <button
              type="button"
              className="copilot-icon"
              title="Close"
              onClick={() => setOpen(false)}
            >
              <X size={14} />
            </button>
          </header>

          <div className="copilot-body" ref={scrollRef}>
            {turns.length === 0 ? (
              <div className="copilot-intro">
                <p>Ask about vehicles, cameras, alerts or live analytics.</p>
                <ul className="copilot-suggestions">
                  {SUGGESTIONS.map((suggestion) => (
                    <li key={suggestion}>
                      <button type="button" onClick={() => send(suggestion)}>
                        {suggestion}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              turns.map((turn, index) =>
                turn.role === "user" ? (
                  <div key={index} className="copilot-user">
                    {turn.content}
                  </div>
                ) : (
                  <div key={index} className="copilot-reply">
                    {turn.content && <p className="copilot-answer">{turn.content}</p>}
                    {(turn.toolResults ?? []).map((event, i) => (
                      <ToolCard
                        key={`${event.tool}-${i}`}
                        event={event}
                        disabled={busy}
                        onPick={(camera) => send(`Camera ${camera.camera_id}`)}
                      />
                    ))}
                    {turn.error && (
                      <p className="copilot-error">
                        <AlertTriangle size={13} aria-hidden="true" />
                        {turn.error}
                      </p>
                    )}
                  </div>
                ),
              )
            )}
            {activeTool && (
              <p className="copilot-activity">{TOOL_LABEL[activeTool] ?? "Working"}…</p>
            )}
          </div>

          <form className="copilot-composer" onSubmit={submit}>
            <textarea
              ref={inputRef}
              rows={1}
              value={draft}
              placeholder="Ask Copilot…"
              aria-label="Message Copilot"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                // Enter sends; Shift+Enter is a newline, as in every chat.
                if (event.key === "Enter" && !event.shiftKey) submit(event);
              }}
            />
            <button type="submit" className="copilot-send" disabled={busy || !draft.trim()}>
              <ArrowUp size={15} />
            </button>
          </form>
        </aside>
      )}
    </>
  );
}
