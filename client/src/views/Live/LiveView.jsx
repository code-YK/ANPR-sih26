import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, LayoutGrid, List, Rows3, Search } from "lucide-react";

import { api } from "../../api.js";
import { useCameras } from "../../context/CamerasContext.jsx";
import { useDepartments } from "../../context/DepartmentsContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import { useGsapReveal } from "../../hooks/useGsapReveal.js";
import { usePolling } from "../../hooks/usePolling.js";
import { useAnalyticsStatus } from "../../lib/analyticsStatus.js";
import CameraTile from "./CameraTile.jsx";
import DetectorWorkbench from "./DetectorWorkbench.jsx";
import FocusedPlayer from "./FocusedPlayer.jsx";
import WorkspaceDock from "./WorkspaceDock.jsx";

// GOV-ING-012: every connected player is a separate stream copy on the
// gateway, and each live tile is its own hls.js instance + MSE decoder, so
// this bounds both gateway and browser cost (tiles past the budget show a
// crisp captured still and play on hover/focus). A full 12-tile wall stays
// smooth now that the recorded-feed relay uses 4s HLS segments (see
// government_feed_relay.py) -- at 1s segments a wall of this size issued more
// requests than a browser's ~6-connection-per-origin limit could serve, and
// every player perpetually re-buffered. Infinity ("All") lifts the cap
// entirely; opt-in, since ~19 simultaneous decoders can still tax a weak GPU.
const STREAM_LIMITS = [1, 3, 6, 9, 12, Infinity];
const DEFAULT_STREAM_LIMIT = 12;
const STREAM_LIMIT_STORAGE_KEY = "sentinel-live-stream-limit";
const VIEW_MODE_STORAGE_KEY = "sentinel-live-view-mode";
const VIEW_MODES = ["grid", "list", "compact"];
// Other cameras playing live under a focused one: enough that the strip reads
// as live without hovering, few enough to leave the media origin room for the
// focused feed and the detector stream.
const STRIP_LIVE_MAX = 3;
const STRIP_HEAD_START_MS = 3000;

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
  const { cameras, loading: camerasLoading, refresh } = useCameras();
  const { names: departments } = useDepartments();
  const [query, setQuery] = useState("");
  const [dept, setDept] = useState("");
  const [quickFilter, setQuickFilter] = useState("all"); // all | ai | plate
  // Focus is a route, not component state: /live/cam11 is a link an operator
  // can send to a colleague, the browser's Back button leaves the camera
  // instead of the whole wall, and a reload comes back to the same feed. It
  // was state, and all three of those were broken.
  const { cameraId: focusedId = null } = useParams();
  const navigate = useNavigate();
  const [visibleIds, setVisibleIds] = useState(() => new Set());
  // The focused player's own distance from the live edge (hls.js `.latency`),
  // lifted out of the player so the detector's telemetry can be shown against
  // it: the worker and the browser read the same stream over two independent
  // connections, and which of the two is behind is a different problem each way.
  const [playerLatency, setPlayerLatency] = useState(null);
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

  // What the wall shows with no search or filters -- demo/government mode's
  // curation still applies. The empty state counts against this, not against
  // the whole registry: a camera government mode hides is not one the
  // operator's search hid, and "Clear filters" will not bring it back.
  const unfilteredCount = useMemo(
    () =>
      cameras.filter((c) => {
        if (demoModeOn && !c.camera_id.startsWith("manual-")) return false;
        if (governmentModeOn && c.camera_id.startsWith("manual-")) return false;
        return true;
      }).length,
    [cameras, demoModeOn, governmentModeOn],
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
  // being left. Starting and stopping a detector lives in the focused
  // camera's own detector workbench -- an operator builds up the running set
  // by focusing each camera in turn, rather than every tile in the wall
  // carrying its own control.
  const changeFocus = useCallback(
    (nextId) => {
      navigate(nextId ? `/live/${encodeURIComponent(nextId)}` : "/live");
    },
    [navigate],
  );

  // ← / → move between cameras while one is focused, in the wall's current
  // order -- the same keys frontend-v5 uses. Not while typing, not while a
  // dialog or the detector sheet is open (the sheet owns the keyboard: Esc
  // closes it), and not inside a tab list, where arrows move between tabs.
  useEffect(() => {
    if (!focusedId) return undefined;
    function onKey(event) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const target = event.target;
      if (target instanceof HTMLElement && (target.isContentEditable || /INPUT|TEXTAREA|SELECT/.test(target.tagName))) return;
      if (target instanceof HTMLElement && target.closest('[role="tablist"], [role="menu"]')) return;
      if (document.querySelector("dialog[open], .dw-ai[data-sheet]")) return;
      const index = filtered.findIndex((c) => c.camera_id === focusedId);
      const next = filtered[index + (event.key === "ArrowRight" ? 1 : -1)];
      if (index < 0 || !next) return;
      event.preventDefault();
      changeFocus(next.camera_id);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusedId, filtered, changeFocus]);

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
  // Head start for the focused camera before the strip goes live (see the
  // budget effect below). Reset whenever focus moves.
  const [stripWarm, setStripWarm] = useState(false);
  useEffect(() => {
    setStripWarm(false);
    if (!focusedId) return undefined;
    const id = setTimeout(() => setStripWarm(true), STRIP_HEAD_START_MS);
    return () => clearTimeout(id);
  }, [focusedId]);
  const stripIdsKey = stripCameras.map((c) => c.camera_id).join(",");

  // The wall, the tiles' dots, the dock, the top bar and the status strip all
  // read one shared poll of /analytics/status (see lib/analyticsStatus.js).
  // They each used to run their own timer against the same endpoint, which is
  // four redundant requests every few seconds on the origin the detector
  // stream and every other poll already contend for.
  const { rows: analyticsStatus } = useAnalyticsStatus();

  // A tile's dot shows whichever vehicle-family detector this camera is
  // running: the two are mutually exclusive per camera, so at most one matches.
  const vehicleStatusByCameraId = useMemo(() => {
    const map = new Map();
    for (const entry of analyticsStatus) {
      if (entry.mode === "vehicle" || entry.mode === "vehicle_finetuned") {
        const existing = map.get(entry.camera_id);
        if (!existing || existing.state !== "running") map.set(entry.camera_id, entry);
      }
    }
    return map;
  }, [analyticsStatus]);
  const aiRunningCount = analyticsStatus.filter((entry) => entry.state === "running").length;

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

      // While a camera is focused, the strip gets a small live budget, and only
      // after the focused feed and the detector stream have had a head start.
      // Measured: with four strip tiles connecting at the same moment as the
      // focused camera, the detector's MJPEG stream shared the media origin's
      // six connections with them and waited 2-4s behind their segments. Once
      // the MJPEG is connected it keeps its socket, so live strip tiles
      // afterwards cost it nothing. Tiles beyond the budget show their last
      // still and go live on hover.
      if (focusedId) {
        if (stripWarm) {
          let stripBudget = Math.min(STRIP_LIVE_MAX, Math.max(0, budget));
          for (const id of prev) {
            if (stripBudget <= 0) break;
            if (id === focusedId || next.has(id) || !streamableVisible(id)) continue;
            next.add(id);
            stripBudget -= 1;
          }
          for (const c of stripCameras) {
            if (stripBudget <= 0) break;
            if (next.has(c.camera_id) || !c.stream_available || !visibleIds.has(c.camera_id)) continue;
            next.add(c.camera_id);
            stripBudget -= 1;
          }
        }
        if (prev.size === next.size && [...next].every((id) => prev.has(id))) return prev;
        return next;
      }


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
  }, [visibleIds, focusedId, focusedHasStream, streamLimit, stripIdsKey, stripWarm]);

  const streamable = filtered.filter((c) => c.stream_available || c.webrtc_preview_available);
  const streamingCount = streamable.filter((c) => activeIds.has(c.camera_id)).length;
  const atCap = streamingCount >= streamLimit;

  // Deliberately not keyed on the focused camera. Focusing one tile used to
  // re-run the reveal over the whole wall -- every remaining tile faded from
  // zero opacity again, with live video inside it -- which read as the page
  // reloading and cost a repaint of every player. The wall animates when its
  // contents or its shape change, which is what the reveal is for.
  const gridRef = useGsapReveal(
    ".camera-tile",
    { stagger: 0.035, duration: 0.45, y: 24, scale: true },
    [filtered.length, viewMode],
  );

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
                {camerasLoading && cameras.length === 0 ? "Loading…" : `${filtered.length} cameras`}
                {" · "}
                {streamingCount} of {streamable.length} previewing
                {" · "}
                {aiRunningCount} with AI running
                {atCap ? " · preview cap reached" : ""}
              </p>
            </div>
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
                    <option key={limit} value={limit}>{Number.isFinite(limit) ? limit : "All"}</option>
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
              {/* "0 cameras" before the list has arrived, and a blank wall when a
                  filter matches nothing, both looked like a broken estate. */}
              {camerasLoading && cameras.length === 0 ? (
                <div className="live-state" aria-busy="true">
                  <h3>Loading cameras…</h3>
                  <p>Fetching the registry for your departments.</p>
                </div>
              ) : filtered.length === 0 ? (
                <div className="live-state">
                  <h3>{unfilteredCount === 0 ? "No cameras to show" : "No cameras match these filters"}</h3>
                  <p>
                    {cameras.length === 0
                      ? "Cameras appear here once they are onboarded in the Registry and granted to a department you can see."
                      : unfilteredCount === 0
                        ? `The current ${governmentModeOn ? "government" : "demo"} mode shows none of the ${cameras.length} cameras you can see.`
                        : `${unfilteredCount} camera${unfilteredCount === 1 ? " is" : "s are"} hidden by the current search or filters.`}
                  </p>
                  {unfilteredCount > 0 && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => {
                        setQuery("");
                        setDept("");
                        setQuickFilter("all");
                      }}
                    >
                      Clear filters
                    </button>
                  )}
                </div>
              ) : null}
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
                title="Previous camera (←)"
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
                title="Next camera (→)"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          </header>

          {/* The feed and the filmstrip are handed in as nodes rather than
              rendered by the workbench, so this view keeps sole ownership of
              the preview budget (activeIds / streamLimit above) -- the
              workbench decides where the player sits, never whether it may
              exist. */}
          <DetectorWorkbench
            camera={focusedCamera}
            onCameraUpdated={refresh}
            playerLatency={playerLatency}
            stripCount={stripCameras.length}
            feed={<FocusedPlayer camera={focusedCamera} onLatency={setPlayerLatency} />}
            filmstrip={
              <div className="live-strip focused-strip">
                {stripCameras.map((c) => (
                  <CameraTile
                    key={c.camera_id}
                    camera={c}
                    active={activeIds.has(c.camera_id)}
                    liveOnHover
                    analyticsState={vehicleStatusByCameraId.get(c.camera_id)?.state}
                    onFocus={changeFocus}
                    onVisibilityChange={handleVisibilityChange}
                    compact
                  />
                ))}
              </div>
            }
          />
        </div>
      )}
    </div>
  );
}
