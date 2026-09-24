import { useEffect, useMemo, useState } from "react";
import { Layers, Square, X } from "lucide-react";

import { api } from "../../api.js";
import { useCameras } from "../../context/CamerasContext.jsx";
import { refreshAnalyticsStatus, useAnalyticsStatus } from "../../lib/analyticsStatus.js";
import { useToast } from "../../components/Toast.jsx";

const MODE_LABEL = {
  vehicle: "ANPR (baseline)",
  vehicle_finetuned: "ANPR",
  person: "Person",
  suspicious: "Suspicious",
};

// A worker that died is shown, not hidden. Dropping every row that is not
// currently running is why a person worker that started and exited a second
// later looked to an operator as though the button had done nothing at all --
// the dock listed nothing, and no other surface reported it either.
function isListed(row) {
  return row && ["running", "starting", "queued", "stopping", "failed", "exited"].includes(row.state);
}

function isActive(row) {
  return row && ["running", "starting", "queued", "stopping"].includes(row.state);
}

export default function WorkspaceDock({ onOpenCamera }) {
  const { cameras } = useCameras();
  const showToast = useToast();
  const [open, setOpen] = useState(false);
  const { rows } = useAnalyticsStatus();
  const [busyId, setBusyId] = useState(null);

  // Esc closes the panel and only the panel: handled in the capture phase and
  // stopped there, so it never also reaches the detector sheet's own Esc.
  useEffect(() => {
    if (!open) return undefined;
    function onKey(event) {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      setOpen(false);
    }
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open]);

  const groups = useMemo(() => {
    const map = new Map();
    for (const row of rows) {
      if (!isListed(row)) continue;
      const id = row.camera_id;
      if (!map.has(id)) map.set(id, []);
      map.get(id).push(row);
    }
    return [...map.entries()];
  }, [rows]);

  const activeCount = rows.filter(isActive).length;
  const endedCount = groups.reduce((n, [, list]) => n + list.filter((row) => !isActive(row)).length, 0);
  const cameraName = (id) => cameras.find((c) => c.camera_id === id)?.name ?? id;
  const cameraLoc = (id) => cameras.find((c) => c.camera_id === id)?.location_text ?? "";

  // A worker that has already ended has nothing to stop; the backend's stop
  // endpoint clears its recorded exit instead, which is what makes the row go.
  async function dismissWorker(row) {
    setBusyId(`${row.camera_id}:${row.mode}`);
    try {
      await api(`/analytics/stop?camera_id=${row.camera_id}&mode=${row.mode}`, { method: "POST" });
    } catch {
      // 404: already cleared elsewhere -- the refresh below settles it either way
    } finally {
      await refreshAnalyticsStatus();
      setBusyId(null);
    }
  }

  async function stopWorker(row) {
    setBusyId(`${row.camera_id}:${row.mode}`);
    try {
      await api(`/analytics/stop?camera_id=${row.camera_id}&mode=${row.mode}`, { method: "POST" });
      if (row.mode === "vehicle" || row.mode === "vehicle_finetuned") {
        const column = row.mode === "vehicle" ? "analytics_enabled" : "analytics_finetuned_enabled";
        await api(`/cameras/${row.camera_id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [column]: false }),
        });
      }
      await refreshAnalyticsStatus();
      showToast("Worker stopped");
    } catch (err) {
      showToast("Stop failed: " + err.message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <button
        type="button"
        className={`workspace-rail-toggle${open ? " is-open" : ""}`}
        aria-expanded={open}
        aria-controls="workspace-panel"
        title="Workspace — running AI workers"
        onClick={() => setOpen((v) => !v)}
      >
        <Layers size={18} strokeWidth={1.75} />
        {activeCount > 0 && <span className="workspace-rail-badge">{activeCount}</span>}
      </button>

      {open && <div className="workspace-backdrop" onClick={() => setOpen(false)} aria-hidden="true" />}
      {open && (
        <aside id="workspace-panel" className="workspace-panel" aria-label="Workspace">
          <header className="workspace-panel-head">
            <div>
              <h3>Workspace</h3>
              <p>
                {activeCount} running · {groups.length} camera{groups.length === 1 ? "" : "s"}
                {endedCount > 0 ? ` · ${endedCount} stopped on its own` : ""}
              </p>
            </div>
            <button type="button" className="workspace-close" onClick={() => setOpen(false)} aria-label="Close">
              <X size={16} />
            </button>
          </header>

          {groups.length === 0 ? (
            <div className="workspace-empty">
              <p>No AI workers running.</p>
              <p className="hint">Open a camera on the Live wall and start inference there.</p>
            </div>
          ) : (
            <ul className="workspace-list">
              {groups.map(([cameraId, list]) => (
                <li key={cameraId} className="workspace-card">
                  <div className="workspace-card-head">
                    <div>
                      <strong>{cameraName(cameraId)}</strong>
                      {cameraLoc(cameraId) && <span>{cameraLoc(cameraId)}</span>}
                    </div>
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => {
                        onOpenCamera?.(cameraId);
                        setOpen(false);
                      }}
                    >
                      Open ↗
                    </button>
                  </div>
                  {list.map((row) => {
                    const active = isActive(row);
                    return (
                      <div key={`${row.camera_id}-${row.mode}`} className="workspace-worker">
                        <div>
                          <span
                            className={`workspace-dot state-${row.state || "idle"}`}
                            aria-hidden="true"
                          />
                          <strong>{MODE_LABEL[row.mode] || row.mode}</strong>
                          <em>{row.state || "—"}</em>
                          {row.queue_position != null && (
                            <span className="mono">#{row.queue_position}</span>
                          )}
                          {row.ran_for_seconds != null && (
                            <span className="mono">ran {Math.round(row.ran_for_seconds)}s</span>
                          )}
                          {/* The reason a worker went away, where the operator
                              is already looking for it -- the alternative is
                              the log panel, which assumes they knew to look. */}
                          {!active && row.last_error && <p className="hint">{row.last_error}</p>}
                          {row.message && <p className="hint">{row.message}</p>}
                        </div>
                        {active ? (
                          <button
                            type="button"
                            className="secondary workspace-stop"
                            disabled={busyId === `${row.camera_id}:${row.mode}`}
                            onClick={() => stopWorker(row)}
                          >
                            <Square size={12} />
                            Stop
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="secondary workspace-stop"
                            disabled={busyId === `${row.camera_id}:${row.mode}`}
                            onClick={() => dismissWorker(row)}
                            title="Clear this ended worker from the list"
                          >
                            Dismiss
                          </button>
                        )}
                      </div>
                    );
                  })}
                </li>
              ))}
            </ul>
          )}
        </aside>
      )}
    </>
  );
}
