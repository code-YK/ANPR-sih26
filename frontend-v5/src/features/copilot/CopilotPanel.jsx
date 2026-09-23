import { AlertTriangle, ArrowUp, Eraser, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { IconButton, Spinner } from "../../components/ui.jsx";
import { useUiStore } from "../../lib/uiStore.js";
import CameraPickerCard from "./cards/CameraPickerCard.jsx";
import WorkerListCard from "./cards/WorkerListCard.jsx";
import styles from "./Copilot.module.css";
import { useCopilotStream } from "./useCopilotStream.js";

const SUGGESTIONS = [
  "Which cameras are offline?",
  "Trace a vehicle",
  "What analytics are running?",
  "Show open alerts",
];

const TOOL_LABEL = {
  list_cameras: "Checking the registry",
  find_cameras_near: "Finding cameras",
  get_camera: "Looking up the camera",
  get_camera_health: "Reading health history",
  trace_vehicle: "Tracing the vehicle",
  search_plate: "Searching footage",
  list_sightings: "Fetching sightings",
  list_workers: "Checking workers",
  get_capacity: "Checking capacity",
  start_anpr: "Starting ANPR",
  stop_anpr: "Stopping ANPR",
  start_worker: "Starting the worker",
  stop_worker: "Stopping the worker",
  list_watchlist: "Reading the watchlist",
  add_to_watchlist: "Adding to the watchlist",
  list_alerts: "Fetching alerts",
  acknowledge_alert: "Acknowledging",
  resolve_alert: "Resolving",
  navigate_to: "Opening the page",
};

/** Tool results that carry their own component. */
function ToolCard({ event, onPick, disabled }) {
  if (!event.result?.ok) return null;
  const data = event.result.data;
  if (event.render === "worker_list") return <WorkerListCard data={data} />;
  if (event.render === "camera_picker") {
    return <CameraPickerCard data={data} onPick={onPick} disabled={disabled} />;
  }
  return null;
}

function Turn({ turn, onPick, busy }) {
  if (turn.role === "user") {
    return <div className={styles.userTurn}>{turn.content}</div>;
  }
  return (
    <div className={styles.assistantTurn}>
      {turn.content && <p className={styles.answer}>{turn.content}</p>}
      {(turn.toolResults ?? []).map((event, index) => (
        <ToolCard key={`${event.tool}-${index}`} event={event} onPick={onPick} disabled={busy} />
      ))}
      {turn.error && (
        <p className={styles.turnError}>
          <AlertTriangle size={14} aria-hidden="true" />
          {turn.error}
        </p>
      )}
      {turn.pending && !turn.content && !turn.error && <Spinner />}
    </div>
  );
}

export default function CopilotPanel() {
  const open = useUiStore((state) => state.copilotOpen);
  const setOpen = useUiStore((state) => state.setCopilotOpen);
  const clear = useUiStore((state) => state.clearCopilot);
  const { turns, send, busy, activeTool } = useCopilotStream();
  const [draft, setDraft] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Follow the answer as it streams, and after a tool card expands a turn.
  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [turns, activeTool]);

  useEffect(() => {
    if (!open) return undefined;
    function onKeyDown(event) {
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, setOpen]);

  function submit(event) {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    send(text);
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          className={styles.panel}
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 24 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          aria-label="Sentinel Copilot"
        >
          <header className={styles.header}>
            <span className={styles.title}>Copilot</span>
            <div className={styles.headerActions}>
              {turns.length > 0 && (
                <IconButton label="Clear conversation" size="sm" onClick={clear}>
                  <Eraser size={15} />
                </IconButton>
              )}
              <IconButton label="Close Copilot" size="sm" onClick={() => setOpen(false)}>
                <X size={15} />
              </IconButton>
            </div>
          </header>

          <div className={styles.scroll} ref={scrollRef}>
            {turns.length === 0 ? (
              <div className={styles.intro}>
                <p>Ask about vehicles, cameras, alerts or live analytics.</p>
                <ul className={styles.suggestions}>
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
              turns.map((turn, index) => (
                <Turn
                  key={index}
                  turn={turn}
                  busy={busy}
                  onPick={(camera) => send(`Camera ${camera.camera_id}`)}
                />
              ))
            )}
            {activeTool && (
              <p className={styles.activity}>
                <Spinner />
                {TOOL_LABEL[activeTool] ?? "Working"}…
              </p>
            )}
          </div>

          <form className={styles.composer} onSubmit={submit}>
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
            <IconButton label="Send" size="sm" type="submit" disabled={busy || !draft.trim()}>
              <ArrowUp size={15} />
            </IconButton>
          </form>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
