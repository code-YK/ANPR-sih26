import { AlertOctagon, Check, Clock3, Expand, FileText, Play, RotateCcw, ScanLine, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { forwardRef, memo, useEffect, useRef, useState } from "react";

import { Button, IconButton, Spinner, StatusDot, Tooltip } from "../../components/ui.jsx";
import { mjpegUrl } from "../../lib/api/media.js";
import { fmtDuration } from "../../lib/format.js";
import { useCapacity, useCameras } from "../../lib/queries.js";
import { useUiStore } from "../../lib/uiStore.js";
import { MODE_KEYS, MODES } from "../workers/modes.js";
import { useStatusRows, useWorkerView } from "../workers/useWorkers.js";
import AnprSightings from "./events/AnprSightings.jsx";
import PersonCounts from "./events/PersonCounts.jsx";
import SuspiciousAlerts from "./events/SuspiciousAlerts.jsx";
import styles from "./Inference.module.css";

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
const InferenceTab = memo(function InferenceTab({ camera, modeKey, selected, onSelect, layoutGroup }) {
  const { view } = useWorkerView(camera.camera_id, modeKey);
  const mode = MODES[modeKey];
  const showDot = view.state !== "idle";
  return (
    <button
      type="button"
      role="tab"
      id={`tab-${camera.camera_id}-${modeKey}-${layoutGroup}`}
      aria-selected={selected}
      aria-controls={`panel-${camera.camera_id}-${layoutGroup}`}
      className={styles.tab}
      onClick={() => onSelect(modeKey)}
      title={view.state === "idle" ? `Start ${mode.title.toLowerCase()}` : `${mode.label}: ${view.label}`}
    >
      <span className={styles.tabLabel}>
        {mode.label}
        {showDot ? (
          <StatusDot tone={view.tone} pulse={view.state === "live"} label={view.label} />
        ) : (
          <span className={styles.tabIdle} aria-hidden="true">
            <Play />
          </span>
        )}
      </span>
    </button>
  );
});

export const InferenceTabs = memo(function InferenceTabs({ camera, activeMode, onSelect, layoutGroup }) {
  const ref = useRef(null);
  const onKeyDown = (event) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const index = MODE_KEYS.indexOf(activeMode);
    const next = MODE_KEYS[(index + (event.key === "ArrowRight" ? 1 : MODE_KEYS.length - 1)) % MODE_KEYS.length];
    event.preventDefault();
    onSelect(next);
    requestAnimationFrame(() => ref.current?.querySelector('[aria-selected="true"]')?.focus());
  };
  return (
    <div ref={ref} className={styles.tabs} role="tablist" aria-label="AI inference modes" onKeyDown={onKeyDown}>
      {MODE_KEYS.map((modeKey) => (
        <InferenceTab
          key={modeKey}
          camera={camera}
          modeKey={modeKey}
          selected={modeKey === activeMode}
          onSelect={onSelect}
          layoutGroup={layoutGroup}
        />
      ))}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Viewport
// ---------------------------------------------------------------------------
const MjpegStream = memo(function MjpegStream({ cameraId, backendMode, runKey, label }) {
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const retryTimer = useRef(null);

  useEffect(() => {
    setAttempt(0);
    setLoaded(false);
    return () => clearTimeout(retryTimer.current);
  }, [cameraId, backendMode, runKey]);

  return (
    <img
      key={`${runKey}-${attempt}`}
      className={styles.stream}
      data-loaded={loaded}
      src={mjpegUrl(cameraId, backendMode, `${runKey}-${attempt}`)}
      alt={label}
      draggable={false}
      onLoad={() => setLoaded(true)}
      onError={() => {
        setLoaded(false);
        clearTimeout(retryTimer.current);
        retryTimer.current = setTimeout(() => setAttempt((value) => value + 1), Math.min(10_000, 1_000 * 2 ** attempt));
      }}
    />
  );
});

function Steps({ steps }) {
  return (
    <ol className={styles.steps}>
      {steps.map((step) => (
        <li key={step.label} data-state={step.state}>
          <span className={styles.stepIcon} aria-hidden="true">
            {step.state === "done" ? <Check /> : step.state === "active" ? <Spinner /> : <span className={styles.stepDot} />}
          </span>
          {step.label}
        </li>
      ))}
    </ol>
  );
}

function ViewportState({ icon, tone, title, children, actions }) {
  return (
    <motion.div
      className={styles.state}
      data-tone={tone}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
    >
      {icon && <div className={styles.stateIcon}>{icon}</div>}
      <h3>{title}</h3>
      {children}
      {actions && <div className={styles.stateActions}>{actions}</div>}
    </motion.div>
  );
}

function QueuedDetail({ backendMode, cameraId }) {
  const { rows } = useStatusRows();
  const cameras = useCameras();
  const capacity = useCapacity();
  const names = new Map((cameras.data ?? []).map((camera) => [camera.camera_id, camera.name]));
  const holders = rows.filter((row) => row.mode === backendMode && row.state === "running" && row.camera_id !== cameraId);
  const cap = capacity.data?.[backendMode];
  if (!holders.length) return null;
  return (
    <p className={styles.stateDetail}>
      {cap ? `All ${cap} slots are in use` : "Slots in use"}: {holders.map((row) => names.get(row.camera_id) ?? row.camera_id).join(", ")}.
      It starts automatically when one is stopped in Workspace.
    </p>
  );
}

export function InferenceViewport({ camera, workerView, onStart, onRetry, onDismiss, canStart, startBlockedReason }) {
  const { mode, view, row, entry } = workerView;
  const openLogs = useUiStore((state) => state.openLogs);
  const runKey = row?.started_at ?? "none";
  const showStream = view.state === "live" || view.state === "stalled";

  let content = null;
  if (view.state === "idle") {
    content = (
      <ViewportState
        key="idle"
        icon={<ScanLine />}
        title={`${mode.label} isn't running on this camera`}
        actions={
          <Tooltip content={canStart ? null : startBlockedReason}>
            <span>
              <Button variant="primary" icon={<Play />} onClick={onStart} disabled={!canStart}>
                Start {mode.label}
              </Button>
            </span>
          </Tooltip>
        }
      >
        <p className={styles.stateDetail}>{mode.title} · {mode.model}</p>
      </ViewportState>
    );
  } else if (view.state === "starting" || view.state === "warming") {
    const requested = view.state === "warming";
    content = (
      <ViewportState key="starting" tone="pending" title={`Starting ${mode.label}`}>
        <Steps
          steps={[
            { label: "Worker launched", state: requested ? "done" : "active" },
            { label: "Loading model and opening the stream", state: requested ? "active" : "pending" },
            { label: "First annotated frame", state: "pending" },
          ]}
        />
        {view.detail && requested && <p className={styles.stateDetail}>{view.detail}</p>}
      </ViewportState>
    );
  } else if (view.state === "queued") {
    content = (
      <ViewportState key="queued" tone="pending" icon={<Clock3 />} title={`${view.label}: waiting for a free ${mode.label} slot`}>
        <p className={styles.stateDetail}>{view.detail}</p>
        <QueuedDetail backendMode={mode.backendMode} cameraId={camera.camera_id} />
      </ViewportState>
    );
  } else if (view.state === "failed" || view.state === "ended") {
    content = (
      <ViewportState
        key="failed"
        tone="critical"
        icon={<AlertOctagon />}
        title={view.state === "failed" ? `${mode.label} couldn't start` : `${mode.label} stopped`}
        actions={
          <>
            <Button variant="primary" icon={<RotateCcw />} onClick={onRetry} disabled={!canStart}>
              Try again
            </Button>
            <Button variant="ghost" icon={<FileText />} onClick={() => openLogs("ai")}>
              Worker log
            </Button>
            {entry && (
              <Button variant="ghost" onClick={onDismiss}>
                Dismiss
              </Button>
            )}
          </>
        }
      >
        <p className={styles.stateDetail}>{view.detail}</p>
      </ViewportState>
    );
  } else if (view.state === "stopping") {
    content = (
      <ViewportState key="stopping" tone="pending" title={`Stopping ${mode.label}`}>
        <Spinner />
      </ViewportState>
    );
  }

  // Between "live" and "stalled" (15s) there is a gap where frames have simply
  // not arrived yet -- common for sources delivered in long segments. Saying so
  // keeps a paused frame from reading as a frozen interface.
  const telemetryAge = view.telemetry?.updated_at ? Date.now() / 1000 - view.telemetry.updated_at : null;
  const waitingSeconds = view.state === "live" && telemetryAge != null && telemetryAge >= 3 ? Math.round(telemetryAge) : null;

  return (
    <div className={styles.viewport} data-state={view.state} data-waiting={waitingSeconds != null || undefined}>
      {showStream && (
        <MjpegStream
          cameraId={camera.camera_id}
          backendMode={mode.backendMode}
          runKey={runKey}
          label={`${mode.label} detections on ${camera.name}`}
        />
      )}
      {(view.state === "starting" || view.state === "warming") && <div className={styles.progress} aria-hidden="true" />}
      <AnimatePresence mode="wait" initial={false}>
        {content}
      </AnimatePresence>
      {showStream && (
        <>
          <div className={styles.viewportTop}>
            {waitingSeconds != null && (
              <Tooltip content="The worker reads this camera's stream in segments, so frames can arrive in bursts. Clips with long keyframe intervals pause for several seconds between segments.">
                <span className={styles.waitingChip}>
                  <Spinner />
                  Waiting for frames · <span className="tabular">{waitingSeconds}s</span>
                </span>
              </Tooltip>
            )}
            <span className={styles.liveChip} data-tone={view.tone}>
              <StatusDot tone={view.tone} pulse={view.state === "live"} />
              {mode.label} · {view.state === "live" ? "Live" : "Stalled"}
              {view.fps != null && view.state === "live" && <span className="tabular"> · {Math.round(view.fps)} fps</span>}
            </span>
          </div>
          <div className={styles.viewportBottom}>
            <Tooltip content="The worker holds its own connection to the stream, so its frames trail the raw feed. Shown side by side rather than as an overlay for that reason.">
              <span className={styles.caption}>
                Model frames{view.lag != null && view.lag >= 0 ? <span className="tabular"> · {view.lag.toFixed(1)} s behind live</span> : null}
              </span>
            </Tooltip>
          </div>
          {view.state === "stalled" && (
            <div className={styles.stalled}>
              <Clock3 aria-hidden="true" />
              {view.detail}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Telemetry
// ---------------------------------------------------------------------------
function Metric({ label, value, tone, hint }) {
  const body = (
    <div className={styles.metric} data-tone={tone}>
      <span className={styles.metricValue}>{value ?? "—"}</span>
      <span className={styles.metricLabel}>{label}</span>
    </div>
  );
  return hint ? <Tooltip content={hint}>{body}</Tooltip> : body;
}

export function TelemetryStrip({ modeKey, workerView }) {
  const { view, mode } = workerView;
  const t = view.telemetry;
  const live = view.state === "live" || view.state === "stalled";
  const n = (value) => (live && value != null ? value : null);

  let metrics;
  if (modeKey === "anpr") {
    metrics = [
      { label: "In frame", value: n(t?.tracked_now) },
      { label: "Vehicles tracked", value: n(t?.unique_tracks) },
      { label: "Plates confirmed", value: n(t?.plates_reported), hint: "Plates that passed the confirmation vote and were recorded as sightings." },
      { label: "Watchlist hits", value: n(t?.alerts_raised), tone: t?.alerts_raised ? "critical" : undefined },
    ];
  } else if (modeKey === "person") {
    metrics = [
      { label: "In frame", value: n(t?.tracked_now) },
      { label: "People tracked", value: n(t?.unique_tracks) },
      { label: "Peak at once", value: n(t?.peak_tracked) },
      { label: "Windows posted", value: n(t?.windows_posted), hint: "30-second count windows recorded." },
    ];
  } else {
    metrics = [
      { label: "In frame", value: n(t?.tracked_now) },
      { label: "Flagged now", value: n(t?.dangerous_now), tone: t?.dangerous_now ? "critical" : undefined },
      { label: "Alerts raised", value: n(t?.alerts_raised), tone: t?.alerts_raised ? "critical" : undefined },
      { label: "People tracked", value: n(t?.unique_tracks) },
    ];
  }

  return (
    <div className={styles.telemetry}>
      <div className={styles.metrics}>
        {metrics.map((metric) => (
          <Metric key={metric.label} {...metric} />
        ))}
        <Metric label="Uptime" value={live || view.uptime != null ? fmtDuration(view.uptime) : null} />
      </div>
      <ul className={styles.legend} aria-label="Detection colours">
        {mode.legend.map((item) => (
          <li key={item.label}>
            <span className={styles.swatch} style={{ background: item.color }} aria-hidden="true" />
            {item.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------
export const InferencePanel = forwardRef(function InferencePanel(
  { camera, variant, activeMode, onSelectMode, onStart, onRetry, onDismiss, onClose, onExpand, canStartMode },
  headingRef,
) {
  const layoutGroup = variant;
  const workerView = useWorkerView(camera.camera_id, activeMode, { watchTelemetry: true });
  const permission = canStartMode(activeMode);

  return (
    <div className={styles.panel} data-variant={variant}>
      {variant === "sheet" && (
        <header className={styles.sheetHeader}>
          <div>
            <p className="overline">AI inference</p>
            <h2 ref={headingRef} tabIndex={-1}>
              {camera.name}
            </h2>
          </div>
          <IconButton label="Close and keep running (Esc)" onClick={onClose}>
            <X />
          </IconButton>
        </header>
      )}

      <div className={styles.tabsRow}>
        <InferenceTabs camera={camera} activeMode={activeMode} onSelect={onSelectMode} layoutGroup={layoutGroup} />
        {variant === "docked" && (
          <IconButton label="Expand AI inference" onClick={onExpand}>
            <Expand />
          </IconButton>
        )}
      </div>

      <div id={`panel-${camera.camera_id}-${layoutGroup}`} role="tabpanel" aria-labelledby={`tab-${camera.camera_id}-${activeMode}-${layoutGroup}`} className={styles.body}>
        <InferenceViewport
          camera={camera}
          workerView={workerView}
          onStart={() => onStart(activeMode)}
          onRetry={() => onRetry(activeMode)}
          onDismiss={() => onDismiss(activeMode)}
          canStart={permission.allowed}
          startBlockedReason={permission.reason}
        />
        <TelemetryStrip modeKey={activeMode} workerView={workerView} />
        <section className={styles.events} aria-label={`${MODES[activeMode].label} events`}>
          {activeMode === "anpr" && <AnprSightings camera={camera} variant={variant} />}
          {activeMode === "person" && <PersonCounts camera={camera} variant={variant} />}
          {activeMode === "suspicious" && <SuspiciousAlerts camera={camera} variant={variant} />}
        </section>
      </div>
    </div>
  );
});
