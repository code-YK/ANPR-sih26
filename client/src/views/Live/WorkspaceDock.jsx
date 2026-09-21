import { useMemo, useState } from "react";
import { Layers, Square, X } from "lucide-react";

import { api } from "../../api.js";
import { useCameras } from "../../context/CamerasContext.jsx";
import { usePolling } from "../../hooks/usePolling.js";
import { useToast } from "../../components/Toast.jsx";

const MODE_LABEL = {
  vehicle: "ANPR",
  vehicle_finetuned: "ANPR",
  person: "Person",
  suspicious: "Suspicious",
};

function isActive(row) {
  return row && ["running", "starting", "queued", "stopping"].includes(row.state);
}

export default function WorkspaceDock({ onOpenCamera }) {
  const { cameras } = useCameras();
  const showToast = useToast();
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState([]);
  const [busyId, setBusyId] = useState(null);

  usePolling(async () => {
    try {
      const data = await api("/analytics/status");
      setRows(Array.isArray(data) ? data : data?.workers ?? data?.items ?? []);
    } catch {
      // ignore
    }
  }, 4000);

  const groups = useMemo(() => {
    const map = new Map();
    for (const row of rows) {
      if (!isActive(row)) continue;
      const id = row.camera_id;
      if (!map.has(id)) map.set(id, []);
      map.get(id).push(row);
    }
    return [...map.entries()];
  }, [rows]);

  const activeCount = groups.reduce((n, [, list]) => n + list.length, 0);
  const cameraName = (id) => cameras.find((c) => c.camera_id === id)?.name ?? id;
  const cameraLoc = (id) => cameras.find((c) => c.camera_id === id)?.location_text ?? "";

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

      {open && (
        <aside id="workspace-panel" className="workspace-panel" aria-label="Workspace">
          <header className="workspace-panel-head">
            <div>
              <h3>Workspace</h3>
              <p>
                {activeCount} running · {groups.length} camera{groups.length === 1 ? "" : "s"}
              </p>
            </div>
            <button type="button" className="workspace-close" onClick={() => setOpen(false)} aria-label="Close">
              <X size={16} />
            </button>
          </header>

          {groups.length === 0 ? (
            <div className="workspace-empty">
              <p>No AI workers running.</p>
              <p className="hint">Start inference from a focused camera.</p>
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
                  {list.map((row) => (
                    <div key={`${row.camera_id}-${row.mode}`} className="workspace-worker">
                      <div>
                        <span
                          className={`workspace-dot state-${row.state || "idle"}`}
                          aria-hidden="true"
                        />
                        <strong>{MODE_LABEL[row.mode] || row.mode}</strong>
                        <em>{row.state || "—"}</em>
                        {row.uptime_s != null && (
                          <span className="mono">{Math.round(row.uptime_s)}s</span>
                        )}
                        {row.message && <p className="hint">{row.message}</p>}
                      </div>
                      <button
                        type="button"
                        className="secondary workspace-stop"
                        disabled={busyId === `${row.camera_id}:${row.mode}`}
                        onClick={() => stopWorker(row)}
                      >
                        <Square size={12} />
                        Stop
                      </button>
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </aside>
      )}
    </>
  );
}
