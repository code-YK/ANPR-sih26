import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api.js";
import { MetadataBadge } from "../../components/Badge.jsx";
import { useCameras } from "../../context/CamerasContext.jsx";
import { useDepartments } from "../../context/DepartmentsContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import { usePolling } from "../../hooks/usePolling.js";
import AnalyticsToggle from "./AnalyticsToggle.jsx";
import CameraTile from "./CameraTile.jsx";
import DetectorView from "./DetectorView.jsx";
import FocusedPlayer from "./FocusedPlayer.jsx";

// GOV-ING-012: every connected player is a separate stream copy on the
// gateway. Keep the operator choice bounded; this is a preview budget, not
// the separate, GPU-bound analytics-worker limit.
const STREAM_LIMITS = [1, 3, 6, 9];
const DEFAULT_STREAM_LIMIT = 9;
const STREAM_LIMIT_STORAGE_KEY = "sentinel-live-stream-limit";

function initialStreamLimit() {
  const stored = Number(window.localStorage.getItem(STREAM_LIMIT_STORAGE_KEY));
  return STREAM_LIMITS.includes(stored) ? stored : DEFAULT_STREAM_LIMIT;
}

export default function LiveView() {
  usePageTitle("Live");
  const { cameras, refresh } = useCameras();
  const { names: departments } = useDepartments();
  const [dept, setDept] = useState("");
  const [anpr, setAnpr] = useState("");
  const [analyticsFilter, setAnalyticsFilter] = useState("");
  const [focusedId, setFocusedId] = useState(null);
  const [visibleIds, setVisibleIds] = useState(() => new Set());
  const [recentSightings, setRecentSightings] = useState([]);
  const [detectorMode, setDetectorMode] = useState("vehicle");
  const [detectorRestartKey, setDetectorRestartKey] = useState(0);
  const [streamLimit, setStreamLimit] = useState(initialStreamLimit);

  const filtered = useMemo(
    () =>
      cameras.filter((c) => {
        if (dept && c.department !== dept) return false;
        if (anpr === "true" && c.anpr_viable !== true) return false;
        if (anpr === "false" && c.anpr_viable !== false) return false;
        if (analyticsFilter === "true" && !c.analytics_enabled) return false;
        return true;
      }),
    [cameras, dept, anpr, analyticsFilter]
  );

  const focusedCamera = cameras.find((c) => c.camera_id === focusedId) ?? null;
  const focusedHasStream = Boolean(
    focusedCamera?.webrtc_preview_available || focusedCamera?.stream_available
  );
  // "Selecting a tile promotes it and demotes the rest to a strip" -- the
  // focused camera is shown once, large, not duplicated in the strip.
  const stripCameras = filtered.filter((c) => c.camera_id !== focusedId);

  // Several cameras may run ANPR at once now (up to
  // max_concurrent_vehicle_workers -- demo default 3, production-safe
  // default 1; see backend/app/config.py), so changing focus is purely a
  // viewing choice and must not touch analytics_enabled on the camera
  // being left. The toggle control still only lives on the focused
  // camera's side panel (see AnalyticsToggle below) -- an operator builds
  // up the enabled set by focusing each camera in turn and switching it
  // on, and turns one off the same way, rather than every tile carrying
  // its own control.
  const changeFocus = useCallback((nextId) => {
    setFocusedId(nextId);
  }, []);

  // Starting ANPR must put the newly-started vehicle detector in view. If
  // the operator previously inspected person/suspicious output, leaving that
  // mode selected made the ANPR panel look blank until they clicked Vehicle
  // themselves. The key also discards any stale "no output" state from the
  // previous attempt and immediately reconnects the detector view.
  const showVehicleDetector = useCallback(() => {
    setDetectorMode("vehicle");
    setDetectorRestartKey((key) => key + 1);
  }, []);
  // Same reasoning, for the fine-tuned checkpoint's own telemetry mode.
  const showVehicleFinetunedDetector = useCallback(() => {
    setDetectorMode("vehicle_finetuned");
    setDetectorRestartKey((key) => key + 1);
  }, []);

  const handleVisibilityChange = useCallback((cameraId, visible) => {
    setVisibleIds((prev) => {
      const already = prev.has(cameraId);
      if (visible === already) return prev;
      const next = new Set(prev);
      if (visible) next.add(cameraId);
      else next.delete(cameraId);
      return next;
    });
  }, []);

  const [activeIds, setActiveIds] = useState(() => new Set());
  const stripIdsKey = stripCameras.map((c) => c.camera_id).join(",");

  // One bulk poll drives both the toolbar's "N of M running" summary and
  // each tile's status dot -- polling GET /analytics/status/:camera_id per
  // visible tile instead would mean one request per camera every 5s.
  const [analyticsStatus, setAnalyticsStatus] = useState([]);
  const [vehicleCapacity, setVehicleCapacity] = useState(null);
  const [vehicleFinetunedCapacity, setVehicleFinetunedCapacity] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api("/analytics/capacity")
      .then((c) => {
        if (!cancelled) {
          setVehicleCapacity(c.vehicle);
          setVehicleFinetunedCapacity(c.vehicle_finetuned);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  usePolling(async () => {
    try {
      setAnalyticsStatus(await api("/analytics/status"));
    } catch {
      // a failed poll just tries again next tick
    }
  }, 5000);

  const vehicleStatusByCameraId = useMemo(() => {
    const map = new Map();
    for (const entry of analyticsStatus) {
      if (entry.mode === "vehicle") map.set(entry.camera_id, entry);
    }
    return map;
  }, [analyticsStatus]);
  const vehicleRunningCount = analyticsStatus.filter((e) => e.mode === "vehicle" && e.state === "running").length;
  const vehicleQueuedCount = analyticsStatus.filter((e) => e.mode === "vehicle" && e.state === "queued").length;
  const vehicleFinetunedRunningCount = analyticsStatus.filter(
    (e) => e.mode === "vehicle_finetuned" && e.state === "running").length;
  const vehicleFinetunedQueuedCount = analyticsStatus.filter(
    (e) => e.mode === "vehicle_finetuned" && e.state === "queued").length;

  useEffect(() => {
    window.localStorage.setItem(STREAM_LIMIT_STORAGE_KEY, String(streamLimit));
  }, [streamLimit]);

  // Which tiles hold a player is sticky, not recomputed from scratch each
  // time: a tile that is already playing keeps its slot for as long as it
  // stays visible, and only loses it when the cap forces an eviction. An
  // earlier version rebuilt the set purely from current visibility, so
  // scrolling away and back tore the player down and re-attached hls.js --
  // several seconds of black re-buffering on a feed that had been fine.
  useEffect(() => {
    setActiveIds((prev) => {
      const next = new Set();
      // A focused WHEP or HLS player consumes one preview slot; a camera with
      // no preview source must not consume the budget just because it is focused.
      let budget = streamLimit;
      if (focusedId && focusedHasStream) {
        next.add(focusedId);
        budget -= 1;
      }

      const streamableVisible = (id) => {
        const cam = stripCameras.find((c) => c.camera_id === id);
        return cam && cam.stream_available && visibleIds.has(id);
      };

      // 1. Incumbents that are still visible keep their slots.
      for (const id of prev) {
        if (budget <= 0) break;
        if (id === focusedId || next.has(id)) continue;
        if (!streamableVisible(id)) continue;
        next.add(id);
        budget -= 1;
      }

      // 2. Fill anything left over with newly-visible tiles, in list order.
      for (const c of stripCameras) {
        if (budget <= 0) break;
        if (next.has(c.camera_id)) continue;
        if (!c.stream_available || !visibleIds.has(c.camera_id)) continue;
        next.add(c.camera_id);
        budget -= 1;
      }

      if (prev.size === next.size && [...next].every((id) => prev.has(id))) return prev;
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleIds, focusedId, focusedHasStream, streamLimit, stripIdsKey]);

  const streamable = filtered.filter((c) => c.stream_available || c.webrtc_preview_available);
  const streamingCount = streamable.filter((c) => activeIds.has(c.camera_id)).length;
  const atCap = streamingCount >= streamLimit;

  useEffect(() => {
    if (!focusedCamera) {
      setRecentSightings([]);
      return undefined;
    }
    let cancelled = false;
    api(`/sightings?camera_id=${focusedCamera.camera_id}&limit=10`)
      .then((data) => {
        if (!cancelled) setRecentSightings(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [focusedCamera?.camera_id]);

  return (
    <>
      <div className="toolbar">
        <select value={dept} onChange={(e) => setDept(e.target.value)}>
          <option value="">All departments</option>
          {departments.map((d) => (
            <option key={d}>{d}</option>
          ))}
        </select>
        <select value={anpr} onChange={(e) => setAnpr(e.target.value)}>
          <option value="">Any ANPR status</option>
          <option value="true">ANPR viable</option>
          <option value="false">Not ANPR viable</option>
        </select>
        <select value={analyticsFilter} onChange={(e) => setAnalyticsFilter(e.target.value)}>
          <option value="">Any analytics status</option>
          <option value="true">Continuous monitoring on</option>
        </select>
        <label className="stream-limit-control" title="Maximum browser live-preview connections. Lower this if the sandbox gateway becomes unstable.">
          Preview limit
          <select value={streamLimit} onChange={(e) => setStreamLimit(Number(e.target.value))}>
            {STREAM_LIMITS.map((limit) => (
              <option key={limit} value={limit}>{limit}</option>
            ))}
          </select>
        </label>
        <div className="spacer" />
        {/* Says what this number actually is. As "N of M streaming" it read
            like a health metric -- as though only N cameras worked -- when
            it is really this console's own concurrency cap. All M are
            available; we just refuse to hold more than the selected limit
            gateway connections open at once (GOV-ING-012). */}
        <span
          className="hint"
          title={
            `${streamable.length} camera(s) here have a stream. This console plays at most ` +
            `${streamLimit} at once, because each open player is a separate stream copy ` +
            `on the gateway. Lower the Preview limit if the gateway becomes unstable.`
          }
        >
          playing {streamingCount} of {streamable.length} available
          {atCap && <strong> · at {streamLimit}-stream limit</strong>}
        </span>
        {/* The actual configured cap (demo vs production; see
            backend/app/config.py's max_concurrent_vehicle_workers), never
            assumed -- vehicleCapacity comes from GET /analytics/capacity,
            not a hardcoded "1". */}
        {vehicleCapacity != null && (
          <span
            className="hint"
            title="How many cameras are running ANPR right now against the configured concurrency cap. A queued camera is enabled and waiting for a free worker slot, not broken."
          >
            {" "}· ANPR {vehicleRunningCount} of {vehicleCapacity} running
            {vehicleQueuedCount > 0 && <strong> · {vehicleQueuedCount} queued</strong>}
          </span>
        )}
        {vehicleFinetunedCapacity != null && (
          <span
            className="hint"
            title="Same idea as ANPR above, for the fine-tuned checkpoint. Deliberately capped low (see backend/app/config.py) -- this is for evaluating the fine-tune, not scaled monitoring."
          >
            {" "}· ANPR finetuned {vehicleFinetunedRunningCount} of {vehicleFinetunedCapacity} running
            {vehicleFinetunedQueuedCount > 0 && <strong> · {vehicleFinetunedQueuedCount} queued</strong>}
          </span>
        )}
      </div>

      <div className="live-layout">
        <div className="live-main">
          {focusedCamera && (
            <div className="live-focused">
              <FocusedPlayer camera={focusedCamera} />
            </div>
          )}
          <div className={focusedCamera ? "live-strip" : "live-grid"}>
            {stripCameras.map((c) => (
              <CameraTile
                key={c.camera_id}
                camera={c}
                active={activeIds.has(c.camera_id)}
                paused={!!focusedId && focusedHasStream && streamLimit === 1}
                analyticsState={vehicleStatusByCameraId.get(c.camera_id)?.state}
                onFocus={changeFocus}
                onVisibilityChange={handleVisibilityChange}
              />
            ))}
          </div>
        </div>

        {focusedCamera && (
          <div className="live-panel">
            <h3>{focusedCamera.name}</h3>
            <p className="hint">{focusedCamera.location_text}</p>
            <p>
              {focusedCamera.department ?? "—"} <MetadataBadge camera={focusedCamera} />
              <br />
              {focusedCamera.camera_type ?? "unknown type"} · {focusedCamera.transport_ok ?? "no transport"}
            </p>
            <AnalyticsToggle
              camera={focusedCamera}
              onCameraUpdated={refresh}
              onAnprEnabled={showVehicleDetector}
              onAnprFinetunedEnabled={showVehicleFinetunedDetector}
            />

            <h4>
              Detector view
              <span
                className="hint detector-mode-note"
                title="The worker holds its own connection to this stream, so these frames are seconds apart from the live player above. Shown as a separate detector view rather than an overlay for that reason."
              >
                {" "}(worker's own frames)
              </span>
            </h4>
            <div className="detector-mode-switch">
              {[
                ["vehicle", "vehicle"],
                ["vehicle_finetuned", "vehicle finetuned"],
                ["person", "person"],
                ["suspicious", "suspicious"],
              ].map(([m, label]) => (
                <button
                  key={m}
                  className={detectorMode === m ? "link-btn active" : "link-btn"}
                  onClick={() => setDetectorMode(m)}
                >
                  {label}
                </button>
              ))}
            </div>
            <DetectorView
              cameraId={focusedCamera.camera_id}
              mode={detectorMode}
              restartKey={detectorRestartKey}
            />

            <h4>Recent sightings</h4>
            {recentSightings.length === 0 ? (
              <p className="hint">None yet.</p>
            ) : (
              <ul className="recent-sightings">
                {recentSightings.map((s) => (
                  <li key={s.id}>
                    <Link to={`/journey/${s.plate}`}>{s.plate}</Link> — {new Date(s.seen_at).toLocaleTimeString()}
                  </li>
                ))}
              </ul>
            )}
            <button className="secondary live-back" onClick={() => changeFocus(null)}>
              Back to grid
            </button>
          </div>
        )}
      </div>
    </>
  );
}
