import { useState } from "react";

import { api } from "../../api.js";
import StatusDot from "../../components/StatusDot.jsx";
import { useToast } from "../../components/Toast.jsx";
import { canAccessDepartment, useAuth } from "../../context/AuthContext.jsx";
import { usePolling } from "../../hooks/usePolling.js";

/**
 * Four rows -- ANPR, ANPR finetuned, Person and Suspicious activity -- each
 * a switch.
 *
 * ANPR and ANPR finetuned both toggle a persistent intent column
 * (`cameras.analytics_enabled` / `analytics_finetuned_enabled`) the
 * auto-start supervisor acts on (see backend/app/routers/analytics.py), not
 * a direct start/stop: several cameras may hold either at once, up to that
 * mode's own concurrency cap, and the supervisor decides running-vs-queued.
 * The two are mutually exclusive per camera -- enabling one clears the
 * other, enforced server-side in cameras.py's _apply_operator_update, not
 * just here -- because they're both a "vehicle" detector for the same
 * camera and this hardware's GPU (see finetune/decision.md D7) doesn't have
 * headroom for two yolo11x-class workers on one feed. Turning one on also
 * explicitly stops the other's worker immediately (see toggleVehicleMode
 * below) rather than waiting for the supervisor's next ~10s tick, so there
 * is never a window with both running.
 *
 * Person and Suspicious have no such persistent column (both are the manual
 * bonus path), so their switches are a direct start/stop against the
 * worker. Every row's running-state comes from the same 5s poll of
 * GET /analytics/status/:id.
 */
export default function AnalyticsToggle({ camera, onCameraUpdated, onAnprEnabled, onAnprFinetunedEnabled }) {
  const { user } = useAuth();
  const canOperate = canAccessDepartment(user, camera.department, "operator");
  const [statuses, setStatuses] = useState([]);
  const [busy, setBusy] = useState(null);
  const showToast = useToast();

  usePolling(async () => {
    try {
      setStatuses(await api(`/analytics/status/${camera.camera_id}`));
    } catch {
      // a failed poll just tries again next tick
    }
  }, 5000);

  const vehicleStatus = statuses.find((s) => s.mode === "vehicle");
  const vehicleFinetunedStatus = statuses.find((s) => s.mode === "vehicle_finetuned");
  const personStatus = statuses.find((s) => s.mode === "person");
  const suspiciousStatus = statuses.find((s) => s.mode === "suspicious");

  // ANPR and ANPR finetuned share this shape -- persistent-intent column,
  // immediate start/stop against the worker, mutual exclusion against the
  // other vehicle-family mode. `mode`/`column` distinguish
  // "vehicle"/analytics_enabled from "vehicle_finetuned"/
  // analytics_finetuned_enabled; `otherMode` is whichever of the two this
  // one isn't, since the server clears the other column for us but the
  // *worker process* for that other mode needs an explicit stop right now,
  // not at the next ~10s supervisor tick -- see the module docstring for
  // why that immediacy matters here specifically (GPU headroom).
  async function toggleVehicleMode(mode, column, otherMode, enabled, onEnabled, label) {
    setBusy(mode);
    try {
      const updated = await api(`/cameras/${camera.camera_id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [column]: enabled }),
      });

      // Act on the click immediately instead of leaving it to the next
      // supervisor tick. The column is the persistent intent and the
      // supervisor still reconciles it, but a tick is up to 10s away --
      // long enough that pressing the switch looked like it had done
      // nothing, which is exactly how "it only works sometimes" starts.
      // Conflicts are expected and benign: 409 = already running, 404 =
      // already stopped. Both mean the desired state is the actual state.
      // A 429 (concurrency cap full) is also expected here -- the camera
      // is still enabled and will start the moment a slot frees, so it is
      // not treated as a failure.
      if (enabled) {
        // Stop the other vehicle-family worker first, best-effort: the PUT
        // above already cleared its persistent intent, but the process
        // itself keeps running until told to stop. A 404 here just means it
        // wasn't running, which is the common case and not an error.
        try {
          await api(`/analytics/stop?camera_id=${camera.camera_id}&mode=${otherMode}`, { method: "POST" });
        } catch {
          // not running -- fine
        }
      }
      const path = enabled
        ? `/analytics/start?camera_id=${camera.camera_id}&mode=${mode}`
        : `/analytics/stop?camera_id=${camera.camera_id}&mode=${mode}`;
      try {
        await api(path, { method: "POST" });
      } catch (startError) {
        // 409 means the worker was already running. 429 is an honest queued
        // state: the persisted intent is retained and the supervisor starts
        // it when capacity frees. Other errors must surface; swallowing them
        // made a broken custom stream look as if ANPR had started.
        const message = String(startError.message || startError);
        const expectedConflict = enabled
          ? message.startsWith("409:") || message.startsWith("429:")
          : message.startsWith("404:");
        if (!expectedConflict) {
          // The intent update precedes the explicit launch so the supervisor
          // can reconcile it. If this immediate launch fails for a real
          // reason (for example no configured HLS/RTSP source), undo that
          // intent as well; otherwise it would keep retrying invisibly.
          if (enabled) {
            const reverted = await api(`/cameras/${camera.camera_id}`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ [column]: false }),
            });
            onCameraUpdated(reverted);
          }
          throw startError;
        }
      }

      onCameraUpdated(updated);
      setStatuses(await api(`/analytics/status/${camera.camera_id}`));
      if (enabled) onEnabled?.();
      showToast(enabled ? `${label} enabled for this camera` : `${label} stopped`);
    } catch (err) {
      showToast("Failed: " + err.message);
    } finally {
      setBusy(null);
    }
  }

  // Person and Suspicious share the same direct start/stop shape -- one
  // helper, parameterised by mode and the labels an operator sees.
  async function toggleManual(mode, start, labels) {
    setBusy(mode);
    try {
      const path = `/analytics/${start ? "start" : "stop"}?camera_id=${camera.camera_id}&mode=${mode}`;
      await api(path, { method: "POST" });
      showToast(start ? labels.started : labels.stopped);
      setStatuses(await api(`/analytics/status/${camera.camera_id}`));
    } catch (err) {
      // A blocked toggle (e.g. the concurrency cap's 429) surfaces here
      // directly rather than failing silently.
      showToast("Failed: " + err.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="analytics-toggle">
      <div className="analytics-row">
        <StatusDot state={vehicleStatus?.state} />
        <span>
          ANPR
          {/* "Enabled but waiting for a free worker slot" and "not running"
              used to render identically, which made a queued camera look
              broken. The supervisor reports queue position for exactly this
              -- and, if it's actually been failing to start rather than
              just waiting, why (last_error), so a stuck camera is
              distinguishable from one that's merely behind three others. */}
          {vehicleStatus?.state === "queued" && (
            <em
              className="analytics-note"
              title={
                vehicleStatus.last_error
                  ? `Enabled, waiting for a worker slot. Last failure (#${vehicleStatus.failure_count}): ${vehicleStatus.last_error}`
                  : "Enabled, waiting for a worker slot to free up"
              }
            >
              {" "}queued #{vehicleStatus.queue_position}
              {vehicleStatus.last_error ? " ⚠" : ""}
            </em>
          )}
        </span>
        <label className="switch">
          <input
            type="checkbox"
            checked={camera.analytics_enabled}
            disabled={!canOperate || !camera.analytics_stream_available || busy === "vehicle" || busy === "vehicle_finetuned"}
            onChange={(e) =>
              toggleVehicleMode("vehicle", "analytics_enabled", "vehicle_finetuned", e.target.checked, onAnprEnabled, "ANPR")
            }
          />
        </label>
      </div>

      <div className="analytics-row">
        <StatusDot state={vehicleFinetunedStatus?.state} />
        <span>
          ANPR finetuned
          {vehicleFinetunedStatus?.state === "queued" && (
            <em
              className="analytics-note"
              title={
                vehicleFinetunedStatus.last_error
                  ? `Enabled, waiting for a worker slot. Last failure (#${vehicleFinetunedStatus.failure_count}): ${vehicleFinetunedStatus.last_error}`
                  : "Enabled, waiting for a worker slot to free up"
              }
            >
              {" "}queued #{vehicleFinetunedStatus.queue_position}
              {vehicleFinetunedStatus.last_error ? " ⚠" : ""}
            </em>
          )}
        </span>
        <label className="switch">
          <input
            type="checkbox"
            checked={camera.analytics_finetuned_enabled}
            disabled={!canOperate || !camera.analytics_stream_available || busy === "vehicle" || busy === "vehicle_finetuned"}
            onChange={(e) =>
              toggleVehicleMode(
                "vehicle_finetuned", "analytics_finetuned_enabled", "vehicle",
                e.target.checked, onAnprFinetunedEnabled, "ANPR finetuned",
              )
            }
          />
        </label>
      </div>

      <div className="analytics-row">
        <StatusDot state={personStatus?.state} />
        <span>Person</span>
        <label className="switch">
          <input
            type="checkbox"
            checked={!!personStatus?.running}
            disabled={!canOperate || busy === "person"}
            onChange={(e) =>
              toggleManual("person", e.target.checked, {
                started: "Person counting started",
                stopped: "Person counting stopped",
              })
            }
          />
        </label>
      </div>

      <div className="analytics-row">
        <StatusDot state={suspiciousStatus?.state} />
        <span>Suspicious activity</span>
        <label className="switch">
          <input
            type="checkbox"
            checked={!!suspiciousStatus?.running}
            disabled={!canOperate || busy === "suspicious"}
            onChange={(e) =>
              toggleManual("suspicious", e.target.checked, {
                started: "Suspicious-activity detection started",
                stopped: "Suspicious-activity detection stopped",
              })
            }
          />
        </label>
      </div>

      {!camera.analytics_stream_available && (
        <span className="analytics-note">no HLS or RTSP source for analytics</span>
      )}
      {!canOperate && <span className="analytics-note">view only — operator clearance is required to change analytics</span>}
    </div>
  );
}
