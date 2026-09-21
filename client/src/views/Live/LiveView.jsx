import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, LayoutGrid, List, Rows3, Search } from "lucide-react";

import { api } from "../../api.js";
import { useCameras } from "../../context/CamerasContext.jsx";
import { useDepartments } from "../../context/DepartmentsContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import { useGsapReveal } from "../../hooks/useGsapReveal.js";
import { usePolling } from "../../hooks/usePolling.js";
import CameraTile from "./CameraTile.jsx";
import FocusedPlayer from "./FocusedPlayer.jsx";
import InferenceSidebar from "./InferenceSidebar.jsx";
import WorkspaceDock from "./WorkspaceDock.jsx";

// GOV-ING-012: every connected player is a separate stream copy on the
// gateway. Keep the operator choice bounded; this is a preview budget, not
// the separate, GPU-bound analytics-worker limit.
const STREAM_LIMITS = [1, 3, 6, 9, 12];
const DEFAULT_STREAM_LIMIT = 9;
const STREAM_LIMIT_STORAGE_KEY = "sentinel-live-stream-limit";
const VIEW_MODE_STORAGE_KEY = "sentinel-live-view-mode";
const VIEW_MODES = ["grid", "list", "compact"];

function initialStreamLimit() {
  const stored = Number(window.localStorage.getItem(STREAM_LIMIT_STORAGE_KEY));
  return STREAM_LIMITS.includes(stored) ? stored : DEFAULT_STREAM_LIMIT;
}

function initialViewMode() {
  const stored = window.localStorage.getItem(VIEW_MODE_STORAGE_KEY);
  return VIEW_MODES.includes(stored) ? stored : "grid";
}

export default function LiveView() {
  usePageTitle("Live");
  const { cameras, refresh } = useCameras();
  const { names: departments } = useDepartments();
  const [query, setQuery] = useState("");
  const [dept, setDept] = useState("");
  const [quickFilter, setQuickFilter] = useState("all"); // all | ai | plate
  const [focusedId, setFocusedId] = useState(null);
  const [visibleIds, setVisibleIds] = useState(() => new Set());
  const [recentSightings, setRecentSightings] = useState([]);
  const [detectorMode, setDetectorMode] = useState("vehicle");
  const [detectorRestartKey, setDetectorRestartKey] = useState(0);
  const [streamLimit, setStreamLimit] = useState(initialStreamLimit);
  const [viewMode, setViewMode] = useState(initialViewMode);
  const [demoModeOn, setDemoModeOn] = useState(false);
  const [governmentModeOn, setGovernmentModeOn] = useState(false);
  const [governmentCameraIds, setGovernmentCameraIds] = useState(() => new Set());

  usePolling(async () => {
    try {
      const [demoStatus, governmentStatus] = await Promise.all([
        api("/admin/demo-mode"),
        api("/admin/government-mode"),
      ]);
      setDemoModeOn(!!demoStatus.enabled);
      setGovernmentModeOn(!!governmentStatus.enabled);
      setGovernmentCameraIds(new Set(governmentStatus.camera_ids ?? []));
    } catch {
      // mode status is a nice-to-have here; a failed poll just leaves the grid as-is
    }
  }, 15000);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const result = cameras.filter((c) => {
      if (needle) {
        const hay = [c.camera_id, c.name, c.location_text, c.department]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      if (dept && c.department !== dept) return false;
      if (quickFilter === "plate" && c.anpr_viable !== true) return false;
      if (quickFilter === "ai" && !c.analytics_enabled) return false;
      // Only this view's own grid, not the shared CamerasContext -- the
      // registry, GIS map, gap analysis, and the rail's own "N cameras
      // live" count all read the unfiltered context and must keep
      // showing the real full registry even while demo mode curates what
      // the wall looks like. A catalogue/government-provided camera
      // never gets a manual-N id (see cameras.py's _next_manual_camera_id
      // comment), so this hides exactly the currently-unreachable real
      // cameras without touching demo mode's own or any operator-added one.
      if (demoModeOn && !c.camera_id.startsWith("manual-")) return false;
      // Government mode is the mirror image: only real catalogue-
      // provided cameras (see government_mode.py), so a manual/demo one
      // is hidden here instead.
      if (governmentModeOn && c.camera_id.startsWith("manual-")) return false;
      return true;
    });
    // Control-room wall effect: while government mode is on, the handful of
    // cameras it actually pointed at a working relay (see
    // GovernmentModeStatus.camera_ids) sort first, so the grid opens on a
    // wall of live feeds instead of interleaving them among the rest of the
    // (currently-unreachable) catalogue in registry order.
    if (governmentModeOn && governmentCameraIds.size > 0) {
      return [...result].sort((a, b) => {
        const aLive = governmentCameraIds.has(a.camera_id) ? 0 : 1;
        const bLive = governmentCameraIds.has(b.camera_id) ? 0 : 1;
        return aLive - bLive;
      });
    }
    return result;
  }, [cameras, query, dept, quickFilter, demoModeOn, governmentModeOn, governmentCameraIds]);

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

  useEffect(() => {
    window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, viewMode);
  }, [viewMode]);

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
  const aiRunningCount = vehicleRunningCount + vehicleFinetunedRunningCount;

  const gridRef = useGsapReveal(
    ".camera-tile",
    { stagger: 0.035, duration: 0.45, y: 24, scale: true },
    [filtered.length, focusedId, viewMode]
  );

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

  const wallClass = focusedCamera
    ? "live-strip"
    : viewMode === "list"
      ? "live-list"
      : viewMode === "compact"
        ? "live-grid live-grid-compact"
        : "live-grid";

  return (
    <div className={`live-page${focusedCamera ? " is-focused" : ""}`}>
      <WorkspaceDock onOpenCamera={(id) => changeFocus(id)} />

      {!focusedCamera && (
        <>
          <header className="live-page-header">
            <div className="live-page-title">
              <p className="eyebrow">LIVE</p>
              <h2>Cameras</h2>
              <p className="live-page-sub">
                {filtered.length} cameras
                {" · "}
                {streamingCount} of {streamable.length} previewing
                {" · "}
                {aiRunningCount} with AI running
                {atCap ? " · preview cap reached" : ""}
              </p>
            </div>
            {governmentModeOn && (
              <button type="button" className="live-gov-badge" title="Showing catalogue cameras from government relay">
                Recorded government footage
              </button>
            )}
          </header>

          <div className="live-filters">
            <div className="live-filters-row">
              <label className="live-search">
                <Search size={16} strokeWidth={1.75} aria-hidden="true" />
                <input
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search name, location or ID"
                  aria-label="Search cameras"
                />
              </label>

              <div className="live-filter-pills" role="group" aria-label="Quick filters">
                <button
                  type="button"
                  className={quickFilter === "all" ? "live-pill is-active" : "live-pill"}
                  onClick={() => setQuickFilter("all")}
                >
                  All
                </button>
                <button
                  type="button"
                  className={quickFilter === "ai" ? "live-pill is-active" : "live-pill"}
                  onClick={() => setQuickFilter("ai")}
                >
                  AI running
                </button>
                <button
                  type="button"
                  className={quickFilter === "plate" ? "live-pill is-active" : "live-pill"}
                  onClick={() => setQuickFilter("plate")}
                >
                  Plate-readable
                </button>
              </div>

              <label className="live-filter live-filter-dept">
                <select value={dept} onChange={(e) => setDept(e.target.value)} aria-label="Department">
                  <option value="">All departments</option>
                  {departments.map((d) => (
                    <option key={d}>{d}</option>
                  ))}
                </select>
              </label>

              <div className="live-filters-spacer" />

              <label
                className="live-filter live-filter-limit"
                title="Maximum browser live-preview connections. Lower this if the sandbox gateway becomes unstable."
              >
                <span>Live previews</span>
                <select value={streamLimit} onChange={(e) => setStreamLimit(Number(e.target.value))}>
                  {STREAM_LIMITS.map((limit) => (
                    <option key={limit} value={limit}>{limit}</option>
                  ))}
                </select>
              </label>

              <div className="live-view-toggles" role="group" aria-label="View layout">
                <button
                  type="button"
                  className={viewMode === "list" ? "live-view-btn is-active" : "live-view-btn"}
                  onClick={() => setViewMode("list")}
                  title="List view"
                  aria-label="List view"
                >
                  <List size={16} strokeWidth={1.75} />
                </button>
                <button
                  type="button"
                  className={viewMode === "grid" ? "live-view-btn is-active" : "live-view-btn"}
                  onClick={() => setViewMode("grid")}
                  title="Grid view"
                  aria-label="Grid view"
                >
                  <LayoutGrid size={16} strokeWidth={1.75} />
                </button>
                <button
                  type="button"
                  className={viewMode === "compact" ? "live-view-btn is-active" : "live-view-btn"}
                  onClick={() => setViewMode("compact")}
                  title="Compact view"
                  aria-label="Compact view"
                >
                  <Rows3 size={16} strokeWidth={1.75} />
                </button>
              </div>
            </div>
          </div>

          <div className="live-layout">
            <div className="live-main">
              <div ref={gridRef} className={wallClass}>
                {stripCameras.map((c) => (
                  <CameraTile
                    key={c.camera_id}
                    camera={c}
                    active={activeIds.has(c.camera_id)}
                    paused={false}
                    analyticsState={vehicleStatusByCameraId.get(c.camera_id)?.state}
                    onFocus={changeFocus}
                    onVisibilityChange={handleVisibilityChange}
                    compact={viewMode === "compact" || viewMode === "list"}
                    listMode={viewMode === "list"}
                  />
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      {focusedCamera && (
        <div className="focused-shell">
          <header className="focused-header">
            <button type="button" className="focused-back" onClick={() => changeFocus(null)} aria-label="Back to grid">
              <ArrowLeft size={18} strokeWidth={2} />
            </button>
            <div className="focused-header-copy">
              <p className="focused-eyebrow">
                {focusedCamera.camera_id}
                {focusedCamera.department ? ` · ${focusedCamera.department}` : ""}
              </p>
              <h1>{focusedCamera.name}</h1>
              <p className="focused-loc">{focusedCamera.location_text || "Location unknown"}</p>
            </div>
            <div className="focused-header-actions">
              {governmentModeOn && (
                <span className="live-gov-badge">Recorded government footage</span>
              )}
              <button
                type="button"
                className="focused-nav-btn"
                disabled={filtered.findIndex((c) => c.camera_id === focusedId) <= 0}
                onClick={() => {
                  const i = filtered.findIndex((c) => c.camera_id === focusedId);
                  if (i > 0) changeFocus(filtered[i - 1].camera_id);
                }}
                aria-label="Previous camera"
              >
                <ChevronLeft size={18} />
              </button>
              <button
                type="button"
                className="focused-nav-btn"
                disabled={filtered.findIndex((c) => c.camera_id === focusedId) >= filtered.length - 1}
                onClick={() => {
                  const i = filtered.findIndex((c) => c.camera_id === focusedId);
                  if (i >= 0 && i < filtered.length - 1) changeFocus(filtered[i + 1].camera_id);
                }}
                aria-label="Next camera"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          </header>

          <div className="focused-body">
            <div className="focused-stage">
              <h2 className="focused-stage-label">Camera feed</h2>
              <div className="focused-player-wrap">
                <FocusedPlayer camera={focusedCamera} />
              </div>

              <div className="focused-filmstrip">
                <div className="focused-filmstrip-head">
                  <span>Other cameras</span>
                  <span className="admin-count-pill">{stripCameras.length}</span>
                </div>
                <div ref={gridRef} className="live-strip focused-strip">
                  {stripCameras.map((c) => (
                    <CameraTile
                      key={c.camera_id}
                      camera={c}
                      active={activeIds.has(c.camera_id)}
                      paused={focusedHasStream && streamLimit === 1}
                      analyticsState={vehicleStatusByCameraId.get(c.camera_id)?.state}
                      onFocus={changeFocus}
                      onVisibilityChange={handleVisibilityChange}
                      compact
                    />
                  ))}
                </div>
              </div>
            </div>

            <InferenceSidebar
              camera={focusedCamera}
              onCameraUpdated={refresh}
              onAnprEnabled={showVehicleDetector}
              onAnprFinetunedEnabled={showVehicleFinetunedDetector}
              detectorMode={detectorMode}
              setDetectorMode={setDetectorMode}
              detectorRestartKey={detectorRestartKey}
              setDetectorRestartKey={setDetectorRestartKey}
            />
          </div>
        </div>
      )}
    </div>
  );
}
