import { useState } from "react";
import { Cpu, ScanLine } from "lucide-react";

import { api } from "../../api.js";
import { AnprBadge } from "../../components/Badge.jsx";
import { useToast } from "../../components/Toast.jsx";
import { canAccessDepartment, useAuth } from "../../context/AuthContext.jsx";
import { usePolling } from "../../hooks/usePolling.js";
import AnalyticsToggle from "./AnalyticsToggle.jsx";
import DetectorView from "./DetectorView.jsx";

const MODES = [
  { id: "vehicle_finetuned", label: "ANPR", desc: "Number plate recognition", column: "analytics_finetuned_enabled", other: "vehicle" },
  { id: "person", label: "Person", desc: "Person detection and counting", manual: true },
  { id: "suspicious", label: "Suspicious", desc: "Suspicious-activity detection", manual: true },
];

export default function InferenceSidebar({
  camera,
  onCameraUpdated,
  onAnprEnabled,
  onAnprFinetunedEnabled,
  detectorMode,
  setDetectorMode,
  detectorRestartKey,
  setDetectorRestartKey,
}) {
  const { user } = useAuth();
  const canOperate = canAccessDepartment(user, camera.department, "operator");
  const showToast = useToast();
  const [selected, setSelected] = useState("vehicle_finetuned");
  const [busy, setBusy] = useState(false);
  const [statuses, setStatuses] = useState([]);
  const [expanded, setExpanded] = useState(false);

  usePolling(async () => {
    try {
      setStatuses(await api(`/analytics/status/${camera.camera_id}`));
    } catch {
      /* ignore */
    }
  }, 4000);

  const activeModes = statuses.filter((s) =>
    ["running", "starting", "queued"].includes(s.state),
  );
  const anyActive = activeModes.length > 0;

  async function startSelected() {
    if (!canOperate) {
      showToast("Operator clearance required");
      return;
    }
    setBusy(true);
    try {
      const mode = selected;
      if (mode === "vehicle_finetuned" || mode === "vehicle") {
        const column =
          mode === "vehicle_finetuned" ? "analytics_finetuned_enabled" : "analytics_enabled";
        const other = mode === "vehicle_finetuned" ? "vehicle" : "vehicle_finetuned";
        const updated = await api(`/cameras/${camera.camera_id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [column]: true }),
        });
        onCameraUpdated?.(updated);
        try {
          await api(`/analytics/stop?camera_id=${camera.camera_id}&mode=${other}`, { method: "POST" });
        } catch {
          /* not running */
        }
        try {
          await api(`/analytics/start?camera_id=${camera.camera_id}&mode=${mode}`, { method: "POST" });
        } catch (err) {
          const msg = String(err.message || err);
          if (!msg.startsWith("409:") && !msg.startsWith("429:")) throw err;
        }
        if (mode === "vehicle") onAnprEnabled?.();
        else onAnprFinetunedEnabled?.();
        setDetectorMode(mode === "vehicle_finetuned" ? "vehicle_finetuned" : "vehicle");
      } else {
        await api(`/analytics/start?camera_id=${camera.camera_id}&mode=${mode}`, { method: "POST" });
        setDetectorMode(mode);
      }
      setDetectorRestartKey((k) => k + 1);
      setExpanded(true);
      showToast("AI inference started");
    } catch (err) {
      showToast("Start failed: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="inference-sidebar">
      <div className="inference-card">
        <div className="inference-card-icon">
          <ScanLine size={18} strokeWidth={1.75} />
        </div>
        <h3>AI Inference</h3>
        <p>
          Run the fine-tuned ANPR model on this feed, then add person and suspicious-activity
          detection from the tabs.
        </p>

        <div className="inference-mode-list" role="radiogroup" aria-label="Inference mode">
          {MODES.map((m) => (
            <label key={m.id} className={`inference-mode-row${selected === m.id ? " is-selected" : ""}`}>
              <input
                type="radio"
                name="inference-mode"
                value={m.id}
                checked={selected === m.id}
                onChange={() => setSelected(m.id)}
              />
              <span className="inference-mode-label">{m.label}</span>
              <span className="inference-mode-desc">{m.desc}</span>
            </label>
          ))}
        </div>

        <button
          type="button"
          className="primary inference-start-btn"
          disabled={busy || !canOperate || !camera.analytics_stream_available}
          onClick={startSelected}
        >
          <Cpu size={16} strokeWidth={2} />
          Start AI Inference
        </button>
        <p className="inference-footnote">Workers keep running until you stop them in Workspace.</p>
      </div>

      <div className="camera-facts-card">
        <dl>
          <div>
            <dt>Department</dt>
            <dd>{camera.department ?? "—"}</dd>
          </div>
          <div>
            <dt>Resolution</dt>
            <dd>
              {camera.width && camera.height ? `${camera.width} × ${camera.height}` : "—"}
            </dd>
          </div>
          <div>
            <dt>Frame rate</dt>
            <dd>{camera.fps ? `${Math.round(camera.fps)} fps` : "—"}</dd>
          </div>
          <div>
            <dt>Codec</dt>
            <dd>{camera.codec ?? "—"}</dd>
          </div>
          <div>
            <dt>Type</dt>
            <dd>{camera.camera_type ?? "—"}</dd>
          </div>
        </dl>
        <div className="camera-facts-badge">
          <AnprBadge value={camera.anpr_viable} />
        </div>
      </div>

      {(anyActive || expanded) && (
        <div className="inference-running">
          <div className="inference-running-tabs">
            {[
              ["vehicle_finetuned", "ANPR"],
              ["vehicle", "ANPR"],
              ["person", "Person"],
              ["suspicious", "Suspicious"],
            ]
              .filter(([m], i, arr) => arr.findIndex((x) => x[0] === m) === i)
              .map(([m, label]) => {
                const st = statuses.find((s) => s.mode === m);
                const on = st && ["running", "starting", "queued"].includes(st.state);
                return (
                  <button
                    key={m}
                    type="button"
                    className={`inference-tab${detectorMode === m ? " is-on" : ""}${on ? " is-live" : ""}`}
                    onClick={() => setDetectorMode(m)}
                  >
                    {label}
                    {on && <span className="inference-tab-dot" />}
                  </button>
                );
              })}
          </div>
          <DetectorView cameraId={camera.camera_id} mode={detectorMode} restartKey={detectorRestartKey} />
          <details className="inference-advanced">
            <summary>Advanced switches</summary>
            <AnalyticsToggle
              camera={camera}
              onCameraUpdated={onCameraUpdated}
              onAnprEnabled={onAnprEnabled}
              onAnprFinetunedEnabled={onAnprFinetunedEnabled}
            />
          </details>
        </div>
      )}
    </div>
  );
}
