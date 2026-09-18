import { ArrowUpRight, Layers, Plus, RotateCcw, Square, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { memo, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useShallow } from "zustand/react/shallow";

import { Badge, Button, EmptyState, IconButton, Meter, StatusDot, Tooltip } from "../../components/ui.jsx";
import { fmtDuration } from "../../lib/format.js";
import { useCapacity, useCameras } from "../../lib/queries.js";
import { useUiStore } from "../../lib/uiStore.js";
import { adoptWorker, dismissWorker, startWorker, stopBackendWorker, stopWorker } from "../workers/lifecycle.js";
import { BACKEND_LABEL, BACKEND_TO_MODE, MODE_KEYS, MODES, rowWorkerId } from "../workers/modes.js";
import { useStatusRows, useWorkerView } from "../workers/useWorkers.js";
import { deriveWorkerView } from "../workers/workerState.js";
import { useWorkerStore } from "../workers/workerStore.js";
import styles from "./Workspace.module.css";

const MODE_RANK = { anpr: 0, person: 1, suspicious: 2 };

function shortLabel(cameraId) {
  const match = String(cameraId).match(/(\d+[a-z]*)$/i);
  if (String(cameraId).startsWith("manual-")) return `M${match ? match[1] : ""}`;
  return (match ? match[1] : String(cameraId).slice(0, 3)).toUpperCase().slice(0, 4);
}

/** Workspace entries grouped by camera, cameras in the order they were added. */
function useGroups() {
  const entries = useWorkerStore(useShallow((state) => Object.values(state.entries)));
  return useMemo(() => {
    const groups = new Map();
    for (const entry of [...entries].sort((a, b) => a.addedAt - b.addedAt)) {
      if (!groups.has(entry.cameraId)) groups.set(entry.cameraId, []);
      groups.get(entry.cameraId).push(entry);
    }
    for (const list of groups.values()) list.sort((a, b) => MODE_RANK[a.mode] - MODE_RANK[b.mode]);
    return [...groups.entries()];
  }, [entries]);
}

// ---------------------------------------------------------------------------
// Rail
// ---------------------------------------------------------------------------
function RailPip({ entry, rowsById }) {
  const view = deriveWorkerView(entry, rowsById.get(entry.id) ?? null, undefined, Date.now());
  return <span className={styles.pip} data-tone={view.tone} title={`${MODES[entry.mode]?.label}: ${view.label}`} />;
}

export function WorkspaceRail() {
  const groups = useGroups();
  const { rowsById } = useStatusRows();
  const cameras = useCameras();
  const open = useUiStore((state) => state.workspaceOpen);
  const setOpen = useUiStore((state) => state.setWorkspaceOpen);
  const recentlyAdded = useUiStore((state) => state.recentlyAdded);
  const [callout, setCallout] = useState(null);

  const names = useMemo(() => new Map((cameras.data ?? []).map((camera) => [camera.camera_id, camera.name])), [cameras.data]);
  const activeCount = groups.reduce(
    (sum, [, list]) => sum + list.filter((entry) => ["starting", "running", "queued", "stopping"].includes(entry.phase)).length,
    0,
  );

  useEffect(() => {
    if (!recentlyAdded || Date.now() - recentlyAdded.at > 2_000) return undefined;
    const [cameraId, mode] = recentlyAdded.id.split("::");
    setCallout({ key: recentlyAdded.at, cameraName: names.get(cameraId) ?? cameraId, mode: MODES[mode]?.label ?? mode });
    const id = setTimeout(() => setCallout(null), 3_200);
    return () => clearTimeout(id);
    // names intentionally omitted: a camera list refresh must not replay the callout
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recentlyAdded]);

  return (
    <nav className={styles.rail} aria-label="Workspace">
      <Tooltip content={open ? "Close Workspace" : "Workspace — running AI workers"} side="left">
        <button
          type="button"
          className={styles.railToggle}
          aria-expanded={open}
          aria-controls="workspace-panel"
          onClick={() => setOpen(!open)}
        >
          <Layers aria-hidden="true" />
          <span className="visually-hidden">Workspace</span>
          {activeCount > 0 && (
            <motion.span key={activeCount} className={styles.railCount} initial={{ scale: 0.6 }} animate={{ scale: 1 }} transition={{ type: "spring", duration: 0.35, bounce: 0.3 }}>
              {activeCount}
            </motion.span>
          )}
        </button>
      </Tooltip>

      <div className={styles.railList}>
        <AnimatePresence initial={false}>
          {groups.map(([cameraId, list]) => (
            <motion.div
              key={cameraId}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              transition={{ type: "spring", duration: 0.35, bounce: 0 }}
            >
              <Tooltip
                side="left"
                content={
                  <>
                    <strong>{names.get(cameraId) ?? cameraId}</strong>
                    <br />
                    {list.map((entry) => MODES[entry.mode]?.label).join(" · ")}
                  </>
                }
              >
                <button type="button" className={styles.railCamera} onClick={() => setOpen(true)} aria-label={`${names.get(cameraId) ?? cameraId} in Workspace`}>
                  <span className={styles.railCameraLabel}>{shortLabel(cameraId)}</span>
                  <span className={styles.pips}>
                    {list.map((entry) => (
                      <RailPip key={entry.id} entry={entry} rowsById={rowsById} />
                    ))}
                  </span>
                </button>
              </Tooltip>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      <AnimatePresence>
        {callout && !open && (
          <motion.div
            key={callout.key}
            className={styles.callout}
            role="status"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 8 }}
            transition={{ type: "spring", duration: 0.4, bounce: 0 }}
          >
            <span className={styles.calloutMode}>{callout.mode}</span> added to Workspace
            <span className={styles.calloutCamera}>{callout.cameraName}</span>
          </motion.div>
        )}
      </AnimatePresence>
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------
const WorkerRow = memo(function WorkerRow({ entry, camera }) {
  const { view, mode } = useWorkerView(entry.cameraId, entry.mode, { watchTelemetry: true, telemetryInterval: 3_000 });
  const busy = view.state === "stopping";
  const failed = view.state === "failed" || view.state === "ended";
  return (
    <motion.li
      className={styles.worker}
      data-tone={view.tone}
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, transition: { duration: 0.15 } }}
    >
      <div className={styles.workerMain}>
        <div className={styles.workerTitle}>
          <StatusDot tone={view.tone} pulse={view.state === "live"} />
          <span className={styles.workerMode}>{mode.label}</span>
          <span className={styles.workerState} data-tone={view.tone}>
            {view.label}
          </span>
        </div>
        <div className={styles.workerMeta}>
          {view.fps != null && <span className="tabular">{Math.round(view.fps)} fps</span>}
          {view.uptime != null && <span className="tabular">{fmtDuration(view.uptime)}</span>}
          {view.detail && view.state !== "live" && <span className={styles.workerDetail}>{view.detail}</span>}
          {!view.detail && view.uptime == null && <span>{mode.model}</span>}
        </div>
      </div>
      <div className={styles.workerActions}>
        {failed ? (
          <>
            <Tooltip content="Try again">
              <IconButton label="Try again" size="sm" tooltip={false} onClick={() => camera && startWorker(camera, entry.mode)} disabled={!camera}>
                <RotateCcw />
              </IconButton>
            </Tooltip>
            <IconButton label="Dismiss" size="sm" onClick={() => dismissWorker(entry.cameraId, entry.mode)}>
              <X />
            </IconButton>
          </>
        ) : (
          <Button size="sm" variant="danger" icon={<Square />} loading={busy} onClick={() => stopWorker(entry.cameraId, entry.mode)}>
            {busy ? "Stopping" : "Stop"}
          </Button>
        )}
      </div>
    </motion.li>
  );
});

function CapacityMeters({ rows }) {
  const capacity = useCapacity();
  if (!capacity.data) return null;
  return (
    <div className={styles.capacity}>
      {MODE_KEYS.map((modeKey) => {
        const backendMode = MODES[modeKey].backendMode;
        const max = capacity.data[backendMode] ?? 0;
        const used = rows.filter((row) => row.mode === backendMode && row.state === "running").length;
        return (
          <div key={modeKey} className={styles.capacityItem}>
            <div className={styles.capacityLabel}>
              <span>{MODES[modeKey].label}</span>
              <span className="tabular faint">
                {used}/{max}
              </span>
            </div>
            <Meter value={used} max={max} />
          </div>
        );
      })}
    </div>
  );
}

function ElsewhereRows({ rows, sessionIds, cameraById }) {
  const [expanded, setExpanded] = useState(false);
  const elsewhere = rows.filter((row) => !sessionIds.has(rowWorkerId(row)));
  if (elsewhere.length === 0) return null;
  return (
    <section className={styles.elsewhere}>
      <button type="button" className={styles.elsewhereToggle} aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        <span>Running elsewhere</span>
        <Badge>{elsewhere.length}</Badge>
      </button>
      {expanded && (
        <>
          <p className={styles.elsewhereHint}>Started in another tab, by another operator, or before this session.</p>
          <ul className={styles.elsewhereList}>
            {elsewhere.map((row) => {
              const camera = cameraById.get(row.camera_id);
              const modeKey = BACKEND_TO_MODE[row.mode];
              const adoptable = MODE_KEYS.includes(modeKey);
              return (
                <li key={`${row.camera_id}-${row.mode}`}>
                  <StatusDot tone={row.state === "queued" ? "pending" : "live"} />
                  <span className={styles.elsewhereText}>
                    <strong>{BACKEND_LABEL[row.mode] ?? row.mode}</strong>
                    <span className="faint">{camera?.name ?? row.camera_id}</span>
                  </span>
                  {adoptable && (
                    <IconButton label="Add to this Workspace" size="sm" onClick={() => adoptWorker(row.camera_id, modeKey, row)}>
                      <Plus />
                    </IconButton>
                  )}
                  <IconButton label="Stop" size="sm" onClick={() => stopBackendWorker(row)}>
                    <Square />
                  </IconButton>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

export function WorkspacePanel() {
  const open = useUiStore((state) => state.workspaceOpen);
  const setOpen = useUiStore((state) => state.setWorkspaceOpen);
  const groups = useGroups();
  const { rows } = useStatusRows();
  const cameras = useCameras();
  const cameraById = useMemo(() => new Map((cameras.data ?? []).map((camera) => [camera.camera_id, camera])), [cameras.data]);
  const sessionIds = useMemo(() => new Set(groups.flatMap(([, list]) => list.map((entry) => entry.id))), [groups]);
  const running = groups.reduce((sum, [, list]) => sum + list.filter((entry) => entry.phase === "running").length, 0);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]") && !useUiStore.getState().sheetCameraId) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          id="workspace-panel"
          key="workspace"
          className={styles.panel}
          aria-label="Workspace"
          initial={{ x: 24, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 16, opacity: 0, transition: { duration: 0.18, ease: [0.7, 0, 0.84, 0] } }}
          transition={{ type: "spring", duration: 0.4, bounce: 0 }}
        >
          <header className={styles.panelHeader}>
            <div>
              <h2>Workspace</h2>
              <p className="faint">
                {groups.length === 0
                  ? "AI workers you start appear here"
                  : `${running} running · ${groups.length} camera${groups.length === 1 ? "" : "s"}`}
              </p>
            </div>
            <IconButton label="Close Workspace (Esc)" onClick={() => setOpen(false)}>
              <X />
            </IconButton>
          </header>

          <div className={styles.panelBody}>
            <CapacityMeters rows={rows} />

            {groups.length === 0 ? (
              <EmptyState compact icon={<Layers />} title="No AI workers in this session">
                Open a camera and choose AI Inference. Workers keep running until you stop them here.
              </EmptyState>
            ) : (
              <ul className={styles.groups}>
                <AnimatePresence initial={false}>
                  {groups.map(([cameraId, list]) => {
                    const camera = cameraById.get(cameraId);
                    return (
                      <motion.li key={cameraId} className={styles.group} exit={{ opacity: 0 }}>
                        <div className={styles.groupHeader}>
                          <div className={styles.groupTitle}>
                            <span className={styles.groupName}>{camera?.name ?? cameraId}</span>
                            <span className="faint">{camera?.location_text ?? cameraId}</span>
                          </div>
                          <Link to={`/live/${encodeURIComponent(cameraId)}`} className="ui-btn ui-btn--ghost ui-btn--sm" onClick={() => setOpen(false)}>
                            Open
                            <ArrowUpRight aria-hidden="true" />
                          </Link>
                        </div>
                        <ul className={styles.workers}>
                          <AnimatePresence initial={false}>
                            {list.map((entry) => (
                              <WorkerRow key={entry.id} entry={entry} camera={camera} />
                            ))}
                          </AnimatePresence>
                        </ul>
                      </motion.li>
                    );
                  })}
                </AnimatePresence>
              </ul>
            )}

            <ElsewhereRows rows={rows} sessionIds={sessionIds} cameraById={cameraById} />
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
