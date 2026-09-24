import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Columns2, Cpu, Maximize2, ScanLine, Square } from "lucide-react";

import { api } from "../../api.js";
import { AnprBadge } from "../../components/Badge.jsx";
import PlateChip from "../../components/PlateChip.jsx";
import StatusDot from "../../components/StatusDot.jsx";
import { useToast } from "../../components/Toast.jsx";
import { canAccessDepartment, isDepartmentAdmin, isSuperAdmin, useAuth } from "../../context/AuthContext.jsx";
import { usePolling } from "../../hooks/usePolling.js";
import { useCameras } from "../../context/CamerasContext.jsx";
import {
  refreshAnalyticsStatus,
  useAnalyticsCapacity,
  useAnalyticsStatus,
  useCameraAnalyticsStatus,
} from "../../lib/analyticsStatus.js";
import DetectorReporting from "./DetectorReporting.jsx";
import DetectorStage from "./DetectorStage.jsx";
import DetectorTabs from "./DetectorTabs.jsx";
import { ANPR_MODELS, DEFAULT_ANPR_MODE, MODE_META, TABS, modeForTab } from "./detectorLegend.js";

const ACTIVE_STATES = ["running", "starting", "queued"];

/**
 * The focused camera's detector, in the three states this view moves through.
 *
 *   plain   nothing running: the feed, and one button that starts inference
 *   sheet   the modal -- detector across the larger, left part of the screen,
 *           the model's own reporting down its right, page scrimmed behind
 *   docked  the sheet dismissed while the worker keeps running: feed and
 *           detector side by side, reporting under the detector
 *
 * Starting inference is therefore one decision ("show me what the model sees"),
 * and dismissing the sheet is another ("keep it beside the feed") -- not a
 * layout the operator has to assemble. Clicking the scrim, pressing Esc, and the
 * header's own Side-by-side button all dismiss, and none of them stops a worker:
 * a layout is a viewing choice, and changing how an operator looks at a camera
 * must never silently change what the GPU is doing.
 *
 * The raw player is a node handed in by LiveView and rendered at one fixed place
 * in this tree, so a state change only moves it with CSS -- the sheet floats
 * over the page rather than re-parenting anything. Re-parenting would remount
 * the <video> and re-attach hls.js, which costs the 6-15s of black re-buffering
 * that HLS segment duration makes unavoidable.
 *
 * This component owns every poll the focused view needs -- worker status,
 * telemetry, sightings -- and passes the results down. Each panel polling for
 * itself is how four components ended up asking for the same status four times.
 */
export default function DetectorWorkbench({
  camera,
  feed,
  filmstrip,
  stripCount = 0,
  playerLatency,
  onCameraUpdated,
}) {
  const { user } = useAuth();
  const showToast = useToast();
  const returnFocusRef = useRef(null);
  const headingRef = useRef(null);

  const [sheetOpen, setSheetOpen] = useState(false);
  // ?ai=person|suspicious|anpr opens the camera on that detector's tab -- how an
  // alert (and its notification) links to the view that raised it.
  const [searchParams] = useSearchParams();
  const aiParam = searchParams.get("ai");
  const requestedTab = TABS.some((entry) => entry.id === aiParam) ? aiParam : null;
  const [tab, setTab] = useState(requestedTab ?? "anpr");
  const [anprMode, setAnprMode] = useState(DEFAULT_ANPR_MODE);
  const [restartKey, setRestartKey] = useState(0);
  const { rows: statuses, loaded: statusesLoaded } = useCameraAnalyticsStatus(camera.camera_id);
  const [telemetry, setTelemetry] = useState(null);
  const [missing, setMissing] = useState(true);
  // "We have not asked yet" is not "nothing is running". Without this the
  // detector claimed the mode was idle -- with a Start button -- for the first
  // poll after every revisit to a camera whose worker was running the whole
  // time.
  const [telemetryLoaded, setTelemetryLoaded] = useState(false);
  const [sightings, setSightings] = useState([]);
  const [busy, setBusy] = useState(false);
  // A start request in flight, as distinct from a stop: the stage says
  // "launching" for one and nothing special for the other.
  const [launching, setLaunching] = useState(false);

  const cameraId = camera.camera_id;
  const mode = modeForTab(tab, anprMode);
  const meta = MODE_META[mode];
  const family = meta?.family;

  const canOperate = canAccessDepartment(user, camera.department, "operator");
  const canAdminCamera =
    isSuperAdmin(user) || (isDepartmentAdmin(user) && camera.department === user?.home_department);

  const startBlockedReason = !camera.analytics_stream_available
    ? "This camera has no HLS or RTSP source a worker can read."
    : !canOperate
      ? "Operator clearance for this camera's department is required."
      : null;

  // A different camera is a different worker: drop this one's readings rather
  // than showing the previous camera's numbers under the new camera's name.
  useEffect(() => {
    setSheetOpen(false);
    setTelemetry(null);
    setMissing(true);
    setTelemetryLoaded(false);
    setSightings([]);
  }, [cameraId]);

  useEffect(() => {
    if (requestedTab) setTab(requestedTab);
  }, [cameraId, requestedTab]);

  useEffect(() => {
    setTelemetry(null);
    setMissing(true);
    setTelemetryLoaded(false);
  }, [mode, restartKey]);

  const workerRow = statuses.find((entry) => entry.mode === mode);
  const state = workerRow?.state;

  // Twice a second while something is publishing -- the counters and the
  // per-vehicle vote are the point of this view, and at 1s they visibly lag the
  // frames beside them. When nothing is running the same poll is only a 404 per
  // tick, so it backs off to a heartbeat that still notices a worker starting
  // without spending the connection budget (or filling the log panel) on nothing.
  const telemetryInterval = missing && !ACTIVE_STATES.includes(state) ? 3000 : 500;

  usePolling(
    async (signal) => {
      try {
        const data = await api(`/analytics/telemetry/${encodeURIComponent(cameraId)}?mode=${mode}`, { signal });
        setTelemetry(data);
        setMissing(false);
      } catch {
        // A cancelled request belongs to a view that is already gone; only a
        // real reply -- 404 means no worker has published here yet -- counts.
        if (signal.aborted) return;
        setMissing(true);
      }
      if (!signal.aborted) setTelemetryLoaded(true);
    },
    telemetryInterval,
    Boolean(cameraId),
  );

  usePolling(
    async (signal) => {
      try {
        setSightings(await api(`/sightings?camera_id=${encodeURIComponent(cameraId)}&limit=20`, { signal }));
      } catch {
        // a failed or cancelled poll just tries again next tick
      }
    },
    8000,
    family === "vehicle",
  );

  const states = useMemo(() => {
    const map = {};
    for (const row of statuses) map[row.mode] = row.state;
    return map;
  }, [statuses]);

  const hasActiveWorker = statuses.some((row) => ACTIVE_STATES.includes(row.state));
  // Until the first status reply, the honest answer is "asking" -- not the
  // start card, which claims nothing is running, and not the docked detector,
  // which claims something is.
  const layout = sheetOpen ? "sheet" : hasActiveWorker ? "docked" : statusesLoaded ? "plain" : "loading";
  const live = !missing && Boolean(telemetry);
  // Queued means the mode's worker cap is full. Saying *which* cameras hold
  // the slots turns "waiting" into something an operator can act on -- stop
  // one of those in Workspace -- the way frontend-v5's queued state does.
  const { rows: allWorkers } = useAnalyticsStatus();
  const capacity = useAnalyticsCapacity();
  const { cameras: allCameras } = useCameras();
  const holders =
    state === "queued"
      ? allWorkers
          .filter((row) => row.mode === mode && row.state === "running" && row.camera_id !== cameraId)
          .map((row) => allCameras.find((c) => c.camera_id === row.camera_id)?.name ?? row.camera_id)
      : [];
  const queueNote =
    state === "queued"
      ? [
          workerRow.last_error
            ? `Enabled, waiting for a worker slot. Last failure (#${workerRow.failure_count}): ${workerRow.last_error}`
            : `Enabled, waiting for a worker slot (queue position ${workerRow.queue_position}).`,
          holders.length
            ? `${capacity?.[mode] ? `All ${capacity[mode]} ${meta?.label ?? mode} slots are` : "Slots are"} in use by ${holders.join(", ")}. It starts automatically when one is stopped in Workspace.`
            : null,
        ]
          .filter(Boolean)
          .join(" ")
      : null;

  // -- worker lifecycle ---------------------------------------------------
  //
  // The two vehicle-family modes carry a persistent intent column the auto-start
  // supervisor reconciles, but writing it is PUT /cameras/{id}, which needs
  // camera-administrator access (cameras.py's update_camera). Starting the
  // worker itself only needs operator (analytics.py's start_analytics). So the
  // column is written when the operator is allowed to write it and skipped when
  // they are not, instead of failing the whole start with a 403 the way this
  // view used to: an operator gets a running worker for this session, and is
  // told plainly that it will not come back by itself.
  const startMode = useCallback(
    async (target) => {
      if (startBlockedReason) {
        showToast(startBlockedReason);
        return;
      }
      const model = ANPR_MODELS.find((entry) => entry.mode === target);
      setBusy(true);
      setLaunching(true);
      try {
        if (model && canAdminCamera) {
          const updated = await api(`/cameras/${encodeURIComponent(cameraId)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ [model.column]: true }),
          });
          onCameraUpdated?.(updated);
        }
        if (model) {
          // One vehicle-family detector per camera. The server clears the other
          // mode's intent for us, but its process keeps running until told to
          // stop, and the next supervisor tick is up to 10s away.
          try {
            await api(`/analytics/stop?camera_id=${encodeURIComponent(cameraId)}&mode=${model.other}`, {
              method: "POST",
            });
          } catch {
            // 404: it was not running, which is the common case
          }
        }
        try {
          await api(`/analytics/start?camera_id=${encodeURIComponent(cameraId)}&mode=${target}`, {
            method: "POST",
          });
        } catch (error) {
          // 409 = already running. 429 = capacity full and legitimately queued.
          // Both mean the desired state is either the actual state or on its way.
          const message = String(error.message || error);
          if (!message.startsWith("409:") && !message.startsWith("429:")) throw error;
          if (message.startsWith("429:")) {
            showToast(
              model && canAdminCamera
                ? "All worker slots are busy — this camera is queued and starts when one frees."
                : "All worker slots are busy. Stop a worker in Workspace and try again.",
            );
          }
        }
        setRestartKey((key) => key + 1);
        await refreshAnalyticsStatus();
        if (model && !canAdminCamera) {
          showToast(`${MODE_META[target].label} started for this session — it will not auto-restart.`);
        }
      } catch (error) {
        showToast("Start failed: " + error.message);
      } finally {
        setBusy(false);
        setLaunching(false);
      }
    },
    [cameraId, canAdminCamera, onCameraUpdated, showToast, startBlockedReason],
  );

  // Stopping mirrors starting. For the vehicle family the persistent intent is
  // cleared first when the operator may write it -- otherwise the supervisor's
  // next tick starts the worker straight back up, which reads as "Stop doesn't
  // work". An operator who cannot write the column can still stop the process;
  // it simply stays stopped only until the supervisor reconciles.
  const stopMode = useCallback(
    async (target) => {
      const model = ANPR_MODELS.find((entry) => entry.mode === target);
      setBusy(true);
      try {
        if (model && canAdminCamera) {
          const updated = await api(`/cameras/${encodeURIComponent(cameraId)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ [model.column]: false }),
          });
          onCameraUpdated?.(updated);
        }
        try {
          await api(`/analytics/stop?camera_id=${encodeURIComponent(cameraId)}&mode=${target}`, {
            method: "POST",
          });
        } catch (error) {
          // 404 means it was already stopped: the desired state is the actual one.
          if (!String(error.message || error).startsWith("404:")) throw error;
        }
        await refreshAnalyticsStatus();
        showToast(
          model && !canAdminCamera
            ? `${MODE_META[target].label} stopped — it stays enabled on the camera, so the supervisor may restart it.`
            : `${MODE_META[target].label} stopped`,
        );
      } catch (error) {
        showToast("Stop failed: " + error.message);
      } finally {
        setBusy(false);
      }
    },
    [cameraId, canAdminCamera, onCameraUpdated, showToast],
  );

  // Selecting a tab is the request to run that mode: an operator clicking
  // "Person" wants person detection, not an empty panel with another button in
  // it. A mode already running just comes into view.
  // One exception: a mode whose last run *failed* -- exited inside the
  // backoff window, i.e. it is crash-looping -- is shown with its reason and a
  // Try again button rather than silently relaunched. Relaunching on a tab
  // click would hide the failure behind a fresh "starting" and hammer a worker
  // that cannot run; a mode that merely exited after a healthy run restarts.
  const selectTab = useCallback(
    (next) => {
      setTab(next);
      const target = modeForTab(next, anprMode);
      const current = states[target];
      if (!ACTIVE_STATES.includes(current) && current !== "failed") startMode(target);
    },
    [anprMode, startMode, states],
  );

  const selectModel = useCallback(
    (next) => {
      setAnprMode(next);
      setTab("anpr");
      if (ACTIVE_STATES.includes(states[next])) setRestartKey((key) => key + 1);
      else startMode(next);
    },
    [startMode, states],
  );

  // -- the sheet ----------------------------------------------------------
  const openSheet = useCallback((event) => {
    returnFocusRef.current = event?.currentTarget ?? document.activeElement;
    setSheetOpen(true);
  }, []);

  const closeSheet = useCallback(() => {
    setSheetOpen(false);
    requestAnimationFrame(() => {
      const target = returnFocusRef.current;
      if (target && document.contains(target)) target.focus();
    });
  }, []);

  // The card opens the sheet on ANPR, the model this problem statement is
  // about; person and suspicious-activity are one tab away inside it.
  const startInference = useCallback(
    (event) => {
      openSheet(event);
      setTab("anpr");
      if (!ACTIVE_STATES.includes(states[anprMode])) startMode(anprMode);
    },
    [anprMode, openSheet, startMode, states],
  );

  useEffect(() => {
    if (!sheetOpen) return undefined;
    const id = requestAnimationFrame(() => headingRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [sheetOpen]);

  useEffect(() => {
    function onKey(event) {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || /INPUT|TEXTAREA|SELECT/.test(target.tagName))
      ) {
        return;
      }
      if (document.querySelector("dialog[open]")) return;
      // The model menu handles its own Escape first and stops propagation, so
      // this only ever reaches a sheet with nothing open inside it.
      if (event.key === "Escape" && sheetOpen) closeSheet();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeSheet, sheetOpen]);

  const sheet = layout === "sheet";

  return (
    <section className="detector-workbench" data-layout={layout} aria-label="Camera detector">
      <div className="dw-feed">
        <div className="dw-feed-head">
          <h2>Camera feed</h2>
          <span className="dw-feed-meta mono">
            {camera.width && camera.height ? `${camera.width}×${camera.height}` : ""}
            {camera.fps ? ` · ${Math.round(camera.fps)} fps` : ""}
          </span>
        </div>
        <div className="dw-feed-stage">{feed}</div>
        <div className="dw-strip">
          <div className="dw-strip-head">
            <span>Other cameras</span>
            <span className="admin-count-pill">{stripCount}</span>
          </div>
          {filmstrip}
        </div>
      </div>

      <div
        className="dw-ai"
        data-sheet={sheet || undefined}
        role={sheet ? "dialog" : undefined}
        aria-modal={sheet ? "false" : undefined}
        aria-label={sheet ? `AI inference · ${camera.name}` : undefined}
      >
        {layout === "loading" ? (
          <section className="ai-card ai-card--loading" aria-busy="true">
            <span className="ai-card-skeleton" style={{ width: "42%", height: 20 }} />
            <span className="ai-card-skeleton" style={{ width: "100%", height: 52 }} />
            <span className="ai-card-skeleton" style={{ width: "100%", height: 34 }} />
            <p className="ai-card-foot">Checking what this camera is running…</p>
          </section>
        ) : layout === "plain" ? (
          <>
            <AiInferenceCard
              states={states}
              anprMode={anprMode}
              onStart={startInference}
              blockedReason={startBlockedReason}
              busy={busy}
            />
            <CameraFacts camera={camera} />
            <EarlierSightings sightings={sightings} />
          </>
        ) : (
          <>
            <header className="dw-head">
              {/* Tabs first, so the modes stay in the panel's top-left corner in
                  both states and the operator's eye lands in the same place
                  whether the detector is docked or filling the screen. */}
              <DetectorTabs
                activeTab={tab}
                anprMode={anprMode}
                states={states}
                onSelectTab={selectTab}
                onSelectModel={selectModel}
                modelDisabledReason={startBlockedReason}
              />
              {sheet && (
                <h2 className="dw-sheet-name" ref={headingRef} tabIndex={-1}>
                  <span className="eyebrow">AI inference</span>
                  {camera.name}
                </h2>
              )}
              {ACTIVE_STATES.includes(state) && (
                <button
                  type="button"
                  className="secondary dw-stop"
                  disabled={busy || !canOperate}
                  onClick={() => stopMode(mode)}
                  title={
                    canOperate
                      ? `Stop the ${meta?.label ?? mode} worker on this camera`
                      : "Operator clearance is required to stop a worker"
                  }
                >
                  <Square size={12} strokeWidth={2.5} aria-hidden="true" />
                  Stop {meta?.label ?? mode}
                </button>
              )}
              {sheet ? (
                <button
                  type="button"
                  className="dw-view-btn"
                  onClick={closeSheet}
                  title="Side by side — keep the detector running beside the feed (Esc)"
                >
                  <Columns2 size={15} strokeWidth={1.9} aria-hidden="true" />
                  <span>Side by side</span>
                </button>
              ) : (
                <button
                  type="button"
                  className="dw-view-btn"
                  onClick={openSheet}
                  title="Focused — the detector across the screen, with the model's reporting alongside"
                >
                  <Maximize2 size={15} strokeWidth={1.9} aria-hidden="true" />
                  <span>Focused</span>
                </button>
              )}
            </header>

            <div className="dw-body">
              <div className="dw-detector">
                <DetectorStage
                  cameraId={cameraId}
                  mode={mode}
                  restartKey={restartKey}
                  telemetry={telemetry}
                  missing={missing}
                  live={live}
                  running={state === "running"}
                  starting={state === "starting"}
                  queued={state === "queued"}
                  queueNote={queueNote}
                  loading={!telemetryLoaded}
                  startedAt={workerRow?.started_at}
                  launching={launching}
                  ended={state === "failed" || state === "exited" ? workerRow : null}
                  canStart={!startBlockedReason}
                  startBlockedReason={startBlockedReason}
                  onStart={() => startMode(mode)}
                  busy={busy}
                  playerLatency={playerLatency}
                  density={sheet ? "compact" : "full"}
                />
              </div>

              <aside className="dw-aux" aria-label="Model reporting">
                <DetectorReporting
                  mode={mode}
                  cameraId={cameraId}
                  cameraName={camera.name}
                  telemetry={telemetry}
                  live={live}
                  sightings={sightings}
                />
              </aside>
            </div>
          </>
        )}
      </div>

      {/* The scrim is the "click outside" surface: dismissing the sheet leaves
          the detector docked beside the feed, still running. */}
      {sheet && <div className="dw-scrim" onClick={closeSheet} aria-hidden="true" />}
    </section>
  );
}

/**
 * The plain state's one action. Not a mode picker: choosing between three
 * detectors before seeing any of them is a decision an operator has no basis
 * for yet, so this starts ANPR -- the model this problem statement is about --
 * and the tabs inside the panel are where person and suspicious-activity
 * detection get added. The list below is a status read-out, not a control.
 */
function AiInferenceCard({ states, anprMode, onStart, blockedReason, busy }) {
  const running = TABS.some((tab) => states?.[modeForTab(tab.id, anprMode)]);
  return (
    <section className="ai-card" aria-labelledby="ai-card-title">
      <span className="ai-card-icon" aria-hidden="true">
        <ScanLine size={20} strokeWidth={1.75} />
      </span>
      <h2 id="ai-card-title">AI inference</h2>
      <p className="ai-card-lead">
        Run the fine-tuned ANPR model on this feed, then add person and suspicious-activity
        detection from the tabs.
      </p>

      <ul className="ai-card-modes">
        {TABS.map((tab) => {
          const tabMode = modeForTab(tab.id, anprMode);
          const state = states?.[tabMode];
          return (
            <li key={tab.id}>
              <StatusDot state={state ?? "stopped"} title={state ?? "not running"} />
              <span className="ai-card-mode-name">{MODE_META[tabMode].label}</span>
              <span className="ai-card-mode-desc">{state ?? MODE_META[tabMode].title}</span>
            </li>
          );
        })}
      </ul>

      <button
        type="button"
        className="primary ai-card-action"
        onClick={onStart}
        disabled={Boolean(blockedReason) || busy}
        title={blockedReason ?? undefined}
      >
        <Cpu size={16} strokeWidth={2} aria-hidden="true" />
        {running ? "Open AI inference" : "Start AI inference"}
      </button>

      <p className="ai-card-foot">
        {blockedReason ?? "Workers keep running until you stop them here or in Workspace."}
      </p>
    </section>
  );
}

/** The facts a detector's output has to be judged against. */
function CameraFacts({ camera }) {
  const facts = [
    ["Department", camera.department ?? "—"],
    ["Resolution", camera.width && camera.height ? `${camera.width} × ${camera.height}` : "—"],
    ["Frame rate", camera.fps ? `${Math.round(camera.fps)} fps` : "—"],
    ["Codec", camera.codec ?? "—"],
    ["Type", camera.camera_type ?? "—"],
  ];
  return (
    <section className="ai-facts" aria-label="Camera details">
      <dl>
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <div className="ai-facts-badge">
        <AnprBadge value={camera.anpr_viable} />
      </div>
    </section>
  );
}

/**
 * Plates recorded here earlier, so a camera that has never resolved one says so
 * before an operator spends a worker slot finding out.
 */
function EarlierSightings({ sightings }) {
  const rows = (sightings ?? []).slice(0, 6);
  if (!rows.length) return null;
  return (
    <section className="ai-earlier" aria-label="Recent sightings">
      <h3>Recent sightings</h3>
      <ul>
        {rows.map((sighting) => (
          <li key={sighting.id}>
            <PlateChip plate={sighting.plate} />
            <time className="mono" dateTime={sighting.seen_at}>
              {new Date(sighting.seen_at).toLocaleTimeString([], { hour12: false })}
            </time>
          </li>
        ))}
      </ul>
    </section>
  );
}
