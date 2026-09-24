import { useEffect, useRef, useState } from "react";
import { AlertOctagon, Check, Cpu, Loader2, Play, RotateCcw, ScanLine } from "lucide-react";

import { mjpegUrl } from "../../api.js";
import { MODE_META, legendFor } from "./detectorLegend.js";

/**
 * The detector's own annotated frames, and the reporting that has to be read
 * with them: what it is finding, whether to trust the rate it is finding it at,
 * and what the colours on the frame mean.
 *
 * The frames are one long-lived MJPEG connection, rendered natively by the
 * <img>. The `k` token exists only to force a brand-new connection when the
 * camera or mode changes (or after the stream ends), never to fetch a frame --
 * see the backend's analytics_stream docstring for why per-frame polling of
 * /analytics/snapshot could not be made to work at any interval on this origin.
 *
 * Deliberately a detector view, not an overlay on the live player: the worker
 * holds its own connection to the stream, so its frames and the player's are
 * seconds apart by construction, and drawing these boxes over the video would
 * misrepresent them as frame-accurate. The caption states the measured gap
 * rather than hiding it.
 *
 * Every number below comes straight from GET /analytics/telemetry -- nothing is
 * derived, averaged or smoothed, so a figure on screen is a figure the worker
 * published. A metric with no live worker renders an em-rule rather than a zero:
 * "nothing running" and "running and found nothing" are different facts and must
 * not look the same (DESIGN.md §3.1).
 */
export default function DetectorStage({
  cameraId,
  mode,
  restartKey = 0,
  telemetry,
  missing,
  live,
  running,
  starting,
  queued,
  queueNote,
  canStart,
  startBlockedReason,
  onStart,
  busy,
  loading,
  ended,
  startedAt,
  launching,
  playerLatency,
  density = "full",
}) {
  const [k, setK] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const retry = useRef(null);
  const meta = MODE_META[mode];

  useEffect(() => {
    setK((n) => n + 1);
    setLoaded(false);
    return () => clearTimeout(retry.current);
  }, [cameraId, mode, restartKey]);

  // Telemetry only counts as "publishing" if it is fresh and belongs to the
  // run that is going on now. A worker that was killed never removes its
  // status file, so the API keeps serving the previous run's last reading
  // (flagged stale); treating that as live made a camera claim "the worker is
  // publishing" half a second after Start, before the new process had loaded
  // anything.
  const startedMs = startedAt ? Date.parse(startedAt) : null;
  const fromThisRun =
    telemetry?.updated_at != null && (startedMs == null || telemetry.updated_at * 1000 >= startedMs - 1000);
  const hasFrames = Boolean(telemetry) && !missing && !telemetry.stale && fromThisRun;
  // Open the stream as soon as either source says a worker is publishing: the
  // worker's own telemetry, or the status row. On a revisit the shared status
  // snapshot already knows the worker is running, so waiting for a telemetry
  // reply first put a whole extra round-trip in front of the first frame --
  // frontend-v5 opens it straight from the running state, and so does this now.
  const streaming = hasFrames || running;
  const stale = Boolean(telemetry?.stale);
  const fps = telemetry?.fps;
  const lag = telemetry?.stream_lag_seconds;

  return (
    <>
      <div
        className="detector-stage"
        data-state={stale ? "stale" : streaming ? "live" : starting || queued ? "pending" : "idle"}
        data-loaded={loaded || undefined}
      >
        {streaming && (
          <MjpegFrame
            key={`${mode}-${k}`}
            src={mjpegUrl(cameraId, mode, k)}
            alt={`${meta?.label ?? mode} detections on camera ${cameraId}`}
            onLoad={() => setLoaded(true)}
            // The stream ends itself when the worker stops publishing; come back
            // on its own once a worker is running again, backing off so a camera
            // with no worker is not a reconnect loop.
            onError={() => {
              setLoaded(false);
              clearTimeout(retry.current);
              retry.current = setTimeout(() => setK((n) => n + 1), 2000);
            }}
          />
        )}

        {streaming && !loaded && (
          <div className="detector-stage-empty detector-stage-connecting">
            {hasFrames ? (
              <>
                <Loader2 className="detector-spin" size={22} strokeWidth={1.75} aria-hidden="true" />
                <h3>Connecting to the detector stream</h3>
                <p>The worker is publishing; its next annotated frame is on the way.</p>
              </>
            ) : (
              // Running but not yet publishing: the model is loading. Measured on
              // the fine-tuned checkpoint this is ~15-18s, and it used to read as
              // "connecting" the whole time, which is not what was happening.
              <StartupSteps label={meta?.label ?? mode} startedAt={startedAt} />
            )}
          </div>
        )}

        {!streaming && (
          <div className="detector-stage-empty">
            {launching ? (
              <StartupSteps label={meta?.label ?? mode} phase="launching" />
            ) : loading ? (
              <>
                <Loader2 className="detector-spin" size={22} strokeWidth={1.75} aria-hidden="true" />
                <h3>Checking this camera</h3>
                <p>Asking the worker what it is doing.</p>
              </>
            ) : ended ? (
              <>
                <AlertOctagon size={24} strokeWidth={1.75} aria-hidden="true" />
                <h3>
                  {meta?.label ?? mode} {ended.state === "failed" ? "stopped unexpectedly" : "has finished"}
                </h3>
                {/* Why it went away, in the view that started it. Before the
                    backend reported exits for every mode, a worker that died
                    simply vanished and the button looked like it had done
                    nothing. */}
                <p>
                  {ended.last_error ??
                    (ended.ran_for_seconds != null
                      ? `It ran for ${Math.round(ended.ran_for_seconds)}s and exited.`
                      : "It is no longer running.")}
                </p>
                <button
                  type="button"
                  className="primary"
                  onClick={onStart}
                  disabled={!canStart || busy}
                  title={canStart ? undefined : startBlockedReason}
                >
                  {busy ? <Loader2 className="detector-spin" size={15} /> : <RotateCcw size={15} strokeWidth={2} />}
                  Try again
                </button>
              </>
            ) : starting || queued ? (
              <>
                <Loader2 className="detector-spin" size={22} strokeWidth={1.75} aria-hidden="true" />
                <h3>{queued ? "Waiting for a free worker slot" : `Starting ${meta?.label ?? mode}`}</h3>
                <p>
                  {queued
                    ? (queueNote ?? "Enabled — it starts automatically when a slot frees.")
                    : "Loading the model and opening the stream. The first annotated frame follows."}
                </p>
              </>
            ) : (
              <>
                <ScanLine size={24} strokeWidth={1.5} aria-hidden="true" />
                <h3>{meta?.label ?? mode} is not running on this camera</h3>
                <p>
                  {meta?.title}
                  {meta?.model ? ` · ${meta.model}` : ""}
                </p>
                <button
                  type="button"
                  className="primary"
                  onClick={onStart}
                  disabled={!canStart || busy}
                  title={canStart ? undefined : startBlockedReason}
                >
                  {busy ? <Loader2 className="detector-spin" size={15} /> : <Play size={15} strokeWidth={2} />}
                  Start {meta?.label ?? mode}
                </button>
                {!canStart && startBlockedReason && <p className="detector-blocked">{startBlockedReason}</p>}
              </>
            )}
          </div>
        )}

        {streaming && loaded && (
          <>
            <div className="detector-stage-top">
              <span className="detector-live-chip" data-tone={stale ? "warn" : "ok"}>
                <span className="detector-live-dot" aria-hidden="true" />
                {meta?.label ?? mode} · {stale ? "stalled" : "live"}
                {fps != null && !stale && <span className="mono"> · {Math.round(fps)} fps</span>}
              </span>
            </div>
            <div className="detector-stage-bottom">
              <span
                className="detector-caption"
                title="The worker holds its own connection to the stream, so its frames trail the browser's player. Shown side by side rather than as an overlay for that reason."
              >
                Model frames
                {lag != null && <span className="mono"> · {Number(lag).toFixed(1)}s behind live</span>}
              </span>
              {running === false && !stale && (
                <span
                  className="detector-caption"
                  title="No worker is registered for this mode; these frames are the last the worker published."
                >
                  worker not registered
                </span>
              )}
            </div>
          </>
        )}

        {stale && (
          <p className="detector-banner is-warn">
            <Cpu size={14} strokeWidth={2} aria-hidden="true" />
            Detector output is {telemetry.age_seconds}s old — the worker may have stopped.
          </p>
        )}
        {telemetry?.time_anchored === false && (
          <p className="detector-banner is-warn">
            Stream not yet time-anchored — a confirmed plate is held back rather than recorded with
            an invented timestamp.
          </p>
        )}
      </div>

      <DetectorReadout
        mode={mode}
        telemetry={telemetry}
        live={live}
        playerLatency={playerLatency}
        density={density}
      />
    </>
  );
}

/**
 * What a starting worker is doing, step by step, with the time it has taken so
 * far -- the same three steps frontend-v5 shows. The elapsed time is from the
 * worker's own `started_at`, so a revisit mid-startup shows the real figure.
 */
function StartupSteps({ label, startedAt, phase = "loading" }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const started = startedAt ? Date.parse(startedAt) : null;
  const elapsed = started ? Math.max(0, Math.round((now - started) / 1000)) : null;
  return (
    <>
      <h3>Starting {label}</h3>
      <ol className="detector-steps">
        {phase === "launching" ? (
          <>
            <li data-state="active">
              <Loader2 className="detector-spin" size={13} strokeWidth={2.5} aria-hidden="true" />
              Launching the worker
            </li>
            <li data-state="pending">
              <span className="detector-step-dot" aria-hidden="true" />
              Loading the model and opening the stream
            </li>
          </>
        ) : (
          <>
            <li data-state="done">
              <Check size={13} strokeWidth={3} aria-hidden="true" />
              Worker launched
            </li>
            <li data-state="active">
              <Loader2 className="detector-spin" size={13} strokeWidth={2.5} aria-hidden="true" />
              Loading the model and opening the stream
              {elapsed != null && <span className="mono"> · {elapsed}s</span>}
            </li>
          </>
        )}
        <li data-state="pending">
          <span className="detector-step-dot" aria-hidden="true" />
          First annotated frame
        </li>
      </ol>
    </>
  );
}

/**
 * One MJPEG connection that is guaranteed to close when it leaves the page.
 *
 * Removing an <img> whose source is a multipart/x-mixed-replace stream does
 * not reliably abort the request in Chromium -- the connection can outlive the
 * element. Because this stream never ends while its worker runs, every remount
 * (a revisit, a mode change, a retry) could leave one behind, and the browser
 * only allows ~6 per origin. Pointing the element at an empty source before it
 * is detached cancels the request deterministically.
 */
function MjpegFrame({ src, alt, onLoad, onError }) {
  const ref = useRef(null);
  // The effect owns the source in both directions -- set on mount, cleared on
  // cleanup -- rather than passing it as a prop. With a `src` prop, React's
  // development double-invoke (mount, cleanup, mount) ran the cleanup against
  // the live element and blanked it, and React never re-applied a prop that
  // had not changed: the stage showed a broken image while the worker was
  // publishing normally.
  useEffect(() => {
    const img = ref.current;
    if (!img) return undefined;
    img.src = src;
    return () => {
      img.src = "";
    };
  }, [src]);
  return (
    <img
      ref={ref}
      className="detector-stage-frame"
      alt={alt}
      draggable={false}
      onLoad={onLoad}
      onError={(event) => {
        // The empty-source abort above fires an error of its own; that one is
        // ours, not the stream's, and must not schedule a reconnect.
        if (!event.currentTarget.getAttribute("src")) return;
        onError?.(event);
      }}
    />
  );
}

function Metric({ label, value, hint, tone }) {
  return (
    <div className="detector-metric" data-tone={tone}>
      <span className="detector-metric-value mono" title={hint}>
        {value ?? "—"}
      </span>
      <span className="detector-metric-label" title={hint}>
        {label}
      </span>
    </div>
  );
}

function DetectorReadout({ mode, telemetry, live, playerLatency, density }) {
  const meta = MODE_META[mode];
  const t = live ? telemetry : null;
  const n = (value) => (t && value != null ? value : null);
  const family = meta?.family;

  let metrics;
  if (family === "vehicle") {
    metrics = [
      { label: "in frame", value: n(t?.tracked_now) },
      { label: "vehicles tracked", value: n(t?.unique_tracks) },
      {
        label: "being read",
        value: n(t?.plates_reading),
        hint: "Vehicles whose plate is being read now but not yet confirmed. Drawn in amber with a “?” and never recorded as a sighting.",
      },
      {
        label: "plates confirmed",
        value: n(t?.plates_reported),
        hint: "Reads that passed the per-character vote over at least three frames and were recorded as sightings.",
      },
      {
        label: "watchlist hits",
        value: n(t?.alerts_raised),
        tone: t?.alerts_raised ? "critical" : undefined,
      },
    ];
  } else if (family === "person") {
    metrics = [
      { label: "in frame", value: n(t?.tracked_now) },
      { label: "people tracked", value: n(t?.unique_tracks) },
      { label: "peak at once", value: n(t?.peak_tracked) },
      { label: "windows posted", value: n(t?.windows_posted), hint: "30-second count windows recorded." },
    ];
  } else {
    metrics = [
      { label: "in frame", value: n(t?.tracked_now) },
      {
        label: "flagged now",
        value: n(t?.dangerous_now),
        tone: t?.dangerous_now ? "critical" : undefined,
        hint: "People classified as potentially dangerous in the frame just processed.",
      },
      {
        label: "alerts raised",
        value: n(t?.alerts_raised),
        tone: t?.alerts_raised ? "critical" : undefined,
        hint: "Each tracked person alerts once, after three consecutive frames agree. See the Alerts view.",
      },
      { label: "people tracked", value: n(t?.unique_tracks) },
    ];
  }

  metrics.push({ label: "fps", value: n(t?.fps != null ? Math.round(t.fps) : null) });

  const workerLag = t?.stream_lag_seconds;

  return (
    <div className="detector-telemetry" data-density={density}>
      <div className="detector-metrics">
        {metrics.map((metric) => (
          <Metric key={metric.label} {...metric} />
        ))}
      </div>

      <div className="detector-health">
        {t?.queue_capacity != null && (
          <span
            className="detector-health-item"
            title="Decoded frames waiting for inference. Rising means this worker is falling behind the live feed — normal briefly after a stream stall, a problem if it stays near capacity."
          >
            <span className="detector-health-label">backlog</span>
            <meter
              className="backlog-meter"
              min="0"
              max={t.queue_capacity}
              value={t.queue_depth}
              low={t.queue_capacity * 0.5}
              high={t.queue_capacity * 0.8}
              optimum={0}
            />
            <span className="mono">
              {t.queue_depth}/{t.queue_capacity}
            </span>
          </span>
        )}
        {workerLag != null && (
          <span
            className="detector-health-item"
            title="How far behind the live edge the frame the worker just processed is, measured from the stream's own EXT-X-PROGRAM-DATE-TIME anchor. Compare with the player's own lag: if the worker is further behind, its reader has drifted; if they match, the stream itself is late."
          >
            <span className="detector-health-label">worker behind live</span>
            <span className="mono">{Number(workerLag).toFixed(1)}s</span>
            {playerLatency != null && (
              <span className="detector-health-aside mono">player {Number(playerLatency).toFixed(0)}s</span>
            )}
          </span>
        )}
        {t?.source_transport && (
          <span
            className="detector-health-item"
            title="Transport the worker itself opened to the source — independent of the browser player's."
          >
            <span className="detector-health-label">worker transport</span>
            <span className="mono">{t.source_transport}</span>
          </span>
        )}
        {t?.resyncs > 0 && (
          <span
            className="detector-health-item"
            title="Times the worker reconnected specifically to get back to the live edge after decoding fell behind. Distinct from reconnects forced by the stream dropping."
          >
            <span className="detector-health-label">live re-syncs</span>
            <span className="mono">{t.resyncs}</span>
          </span>
        )}
        {t?.dropped_frames > 0 && (
          <span
            className="detector-health-item"
            title="Frames evicted because the backlog was already full when a new one arrived — never seen by the detector."
          >
            <span className="detector-health-label">dropped</span>
            <span className="mono">{t.dropped_frames}</span>
          </span>
        )}
        {t?.uptime_seconds != null && (
          <span className="detector-health-item">
            <span className="detector-health-label">uptime</span>
            <span className="mono">{fmtUptime(t.uptime_seconds)}</span>
          </span>
        )}
      </div>

      <div className="detector-legend">
        <span className="detector-legend-title">On the frame</span>
        <ul>
          {legendFor(mode).map((item) => (
            <li key={item.label}>
              <span
                className="detector-swatch"
                data-shape={item.shape}
                style={{ "--swatch": item.color }}
                aria-hidden="true"
              />
              {item.label}
            </li>
          ))}
        </ul>
        {meta?.model && <span className="detector-legend-model mono">{meta.model}</span>}
      </div>
    </div>
  );
}

function fmtUptime(seconds) {
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  const m = Math.floor(total / 60);
  if (m < 60) return `${m}m ${String(total % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}
