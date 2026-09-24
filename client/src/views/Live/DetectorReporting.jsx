import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Car, Check, ScanLine, ShieldAlert } from "lucide-react";

import { api, evidenceUrl } from "../../api.js";
import ImageLightbox from "../../components/ImageLightbox.jsx";
import PlateChip from "../../components/PlateChip.jsx";
import { usePolling } from "../../hooks/usePolling.js";
import { MODE_META, classRows } from "./detectorLegend.js";

const MAX_READINGS = 40;

function fmtClock(value) {
  if (value == null) return "—";
  return new Date(value).toLocaleTimeString([], { hour12: false });
}

/**
 * Time for a row that may be days old: a clock for today, otherwise the date
 * as well. The confirmed list shows a camera's most recent sightings however
 * old they are, and a bare "13:39:36" made a sighting from last week read as
 * one from this morning.
 */
function fmtWhen(value) {
  if (value == null) return "—";
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return fmtClock(value);
  return `${date.toLocaleDateString([], { day: "numeric", month: "short" })} ${date.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit" })}`;
}

function humanize(value) {
  return value ? String(value).replace(/_/g, " ") : "";
}

/**
 * What the model is making of this camera, beside the frames it drew.
 *
 * Three fixed sections, in the order the reasoning runs: what is in view, which
 * plates are being worked out, and what came out of it. Each section keeps its
 * own height and scrolls itself, so a busy junction fills a list instead of
 * pushing the next heading off the screen -- the rail's layout does not move
 * as the numbers do. Which sections appear follows the detector's own output: a
 * plate vote for ANPR, count windows for person, the alert queue for
 * suspicious-activity.
 */
export default function DetectorReporting({ mode, cameraId, cameraName, telemetry, live, sightings }) {
  const family = MODE_META[mode]?.family;
  const readings = useReadingLog(telemetry, live, `${cameraId}:${mode}`);
  const need = telemetry?.plate_min_votes ?? 3;

  return (
    <div className="rail" data-family={family}>
      <InView mode={mode} telemetry={telemetry} live={live} />
      {family === "vehicle" && (
        <>
          <NowReading readings={readings} live={live} telemetry={telemetry} need={need} />
          <Confirmed
            cameraId={cameraId}
            sightings={sightings}
            readings={readings}
            need={need}
            live={live}
            cameraName={cameraName}
          />
        </>
      )}
      {family === "person" && <PersonCounts cameraId={cameraId} live={live} />}
      {family === "suspicious" && <SuspiciousAlerts cameraId={cameraId} live={live} />}
    </div>
  );
}

/**
 * Accumulates the worker's per-vehicle plate progress into a log.
 *
 * The worker reports only the vehicles in the frame it just processed, so
 * rendering that snapshot directly made cards appear and vanish every half
 * second as traffic moved -- the instability operators saw. This keeps one
 * entry per track for the life of the worker run: it appears when the reader
 * first finds a plate on that vehicle, updates in place as the vote grows, and
 * stays (marked as having left the frame) once the vehicle has gone. A reading
 * never un-confirms. The log resets when the camera or mode changes, and when
 * the worker's uptime goes backwards -- a restarted worker reuses track ids.
 */
function useReadingLog(telemetry, live, resetKey) {
  const [log, setLog] = useState([]);
  const lastUptime = useRef(null);

  useEffect(() => {
    setLog([]);
    lastUptime.current = null;
  }, [resetKey]);

  useEffect(() => {
    if (!live || !Array.isArray(telemetry?.plates_live)) return;
    const rows = telemetry.plates_live;
    const uptime = telemetry.uptime_seconds;
    const restarted = lastUptime.current != null && uptime != null && uptime < lastUptime.current;
    lastUptime.current = uptime;

    setLog((prev) => {
      const byId = new Map((restarted ? [] : prev).map((entry) => [entry.track_id, entry]));
      const inFrame = new Set(rows.map((row) => row.track_id));
      let changed = restarted;
      for (const row of rows) {
        const old = byId.get(row.track_id);
        const confirmed = Boolean(old?.confirmed || row.confirmed);
        const next = {
          track_id: row.track_id,
          vehicle: row.vehicle ?? old?.vehicle ?? null,
          // A confirmed text is settled; a later tentative read of the same
          // vehicle must not overwrite it.
          text: old?.confirmed ? old.text : row.text,
          confirmed,
          votes: row.votes,
          bestVotes: Math.max(old?.bestVotes ?? 0, row.votes ?? 0),
          reads: row.reads,
          valid: old?.confirmed ? old.valid : row.valid,
          edits: old?.confirmed ? old.edits : row.edits,
          confidence: row.confidence,
          best_width: row.best_width,
          firstSeen: old?.firstSeen ?? Date.now(),
          confirmedAt: old?.confirmedAt ?? (confirmed ? Date.now() : null),
          inFrame: true,
        };
        if (!old || !sameReading(old, next)) {
          byId.set(row.track_id, next);
          changed = true;
        }
      }
      for (const [id, entry] of byId) {
        if (entry.inFrame && !inFrame.has(id)) {
          byId.set(id, { ...entry, inFrame: false });
          changed = true;
        }
      }
      if (!changed) return prev;
      return [...byId.values()].sort((a, b) => a.firstSeen - b.firstSeen).slice(-MAX_READINGS);
    });
  }, [telemetry, live]);

  return log;
}

const READING_FIELDS = ["text", "confirmed", "votes", "bestVotes", "reads", "valid", "edits", "confidence", "best_width", "inFrame", "vehicle"];

function sameReading(a, b) {
  return READING_FIELDS.every((field) => a[field] === b[field]);
}

/**
 * Keeps a list pinned to its newest item as items arrive -- but only while the
 * operator is already at the bottom. Once they scroll up to read something, the
 * list stops pulling them away from it; scrolling back down re-arms it.
 */
function useFollowNewest(length) {
  const ref = useRef(null);
  const pinned = useRef(true);
  useEffect(() => {
    const el = ref.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [length]);
  const onScroll = () => {
    const el = ref.current;
    if (el) pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  };
  return [ref, onScroll];
}

function Section({ title, count, className = "", children, foot, bodyRef, onScroll, label }) {
  return (
    <section className={`rail-section ${className}`} aria-label={label ?? title}>
      <header className="rail-head">
        <h3>{title}</h3>
        {count != null && <span className="detector-count mono">{count}</span>}
      </header>
      <div className="rail-body" ref={bodyRef} onScroll={onScroll}>
        {children}
      </div>
      {foot && <p className="rail-foot">{foot}</p>}
    </section>
  );
}

/**
 * What the detector is looking at, by class: how many of each are in the frame
 * it just processed, and how many distinct ones it has tracked since it started.
 *
 * "Now" rises and falls with traffic; "tracked" only grows and is the closer
 * thing to a count of what passed -- but neither is a traffic volume. A vehicle
 * the tracker loses and re-acquires is two tracks, and one it never resolves is
 * none. Colours are the ones the worker drew on the frame (see detectorLegend),
 * so a row here and a box there are the same thing. Rows only ever get added,
 * so this section does not reflow as the frame changes.
 */
function InView({ mode, telemetry, live }) {
  const inFrame = live ? telemetry?.in_frame_by_class : null;
  const unique = live ? telemetry?.unique_by_class : null;
  const rows = classRows(mode, unique);

  return (
    <Section
      title="In view"
      className="rail-inview"
      count={live && telemetry?.tracked_now != null ? `${telemetry.tracked_now} now` : null}
      label="What the detector is seeing"
      foot={
        rows.length > 0 ? (
          <>
            <span className="mono">now</span> in the last processed frame · <span className="mono">tracked</span>{" "}
            distinct since start — a floor, not a traffic count.
          </>
        ) : null
      }
    >
      {!live ? (
        <p className="hint">Start the detector to count what it sees.</p>
      ) : unique == null ? (
        <p className="hint">This worker is not reporting per-class counts. Restart it to pick up the current worker build.</p>
      ) : rows.length === 0 ? (
        <p className="hint">Nothing tracked on this camera yet.</p>
      ) : (
        <ul className="class-list">
          <li className="class-list-head" aria-hidden="true">
            <span />
            <span />
            <span>now</span>
            <span>tracked</span>
          </li>
          {rows.map((row) => (
            <li key={row.key}>
              <span
                className="detector-swatch"
                style={row.color ? { "--swatch": row.color } : undefined}
                data-unknown={row.color ? undefined : "true"}
                aria-hidden="true"
              />
              <span className="class-label">{row.label}</span>
              <span className="class-now mono" title="In the frame the detector just processed">
                {inFrame?.[row.key] ?? 0}
              </span>
              <span className="class-total mono" title="Distinct ones tracked since this worker started">
                {row.value}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

/**
 * The plate reader thinking out loud: one card per vehicle it has found a plate
 * on, showing how far that vehicle's vote has got.
 *
 * A plate is not read from a frame, it is *voted* on across frames -- every
 * character has to win a quality-weighted majority with support from at least
 * three independent reads before anything is recorded (multi-object-tracking/
 * plates.py). Every card is a belief: tentative reads keep the worker's own "?"
 * and the dashed plate treatment. Newest at the bottom; the list follows it.
 */
function NowReading({ readings, live, telemetry, need }) {
  const [bodyRef, onScroll] = useFollowNewest(readings.length);
  const reportsProgress = Array.isArray(telemetry?.plates_live);
  const reading = readings.filter((entry) => !entry.confirmed && entry.inFrame).length;

  return (
    <Section
      title="Now reading"
      className="rail-reading"
      count={readings.length ? `${reading} active · ${readings.length}` : null}
      bodyRef={bodyRef}
      onScroll={onScroll}
      label="Plates being read"
      foot="What the reader currently believes. Only a confirmed read is recorded as a sighting."
    >
      {!live ? (
        <p className="hint">Start ANPR to watch the reader work.</p>
      ) : !reportsProgress ? (
        <p className="hint">
          This worker is not reporting per-vehicle progress
          {telemetry?.plates_reading != null ? ` — ${telemetry.plates_reading} in flight` : ""}. Restart it to pick up the
          current worker build.
        </p>
      ) : readings.length === 0 ? (
        <p className="hint">
          No plate located on a tracked vehicle yet. Vehicles can be tracked for a while before a plate is large enough to
          read.
        </p>
      ) : (
        <ul className="reading-list">
          {readings.map((entry) => (
            <ReadingCard key={entry.track_id} entry={entry} need={need} />
          ))}
        </ul>
      )}
    </Section>
  );
}

function ReadingCard({ entry, need }) {
  const text = entry.text ? `${entry.text}${entry.confirmed ? "" : "?"}` : null;
  const votes = Math.min(entry.votes ?? 0, need);
  return (
    <li className="reading-card" data-confirmed={entry.confirmed || undefined} data-gone={!entry.inFrame || undefined}>
      <div className="reading-card-top">
        <span className="reading-track">
          {entry.vehicle ? humanize(entry.vehicle) : "vehicle"} <span className="mono">#{entry.track_id}</span>
        </span>
        {entry.confirmed ? (
          <span className="reading-state is-confirmed">
            <Check size={12} strokeWidth={3} aria-hidden="true" />
            confirmed
          </span>
        ) : entry.inFrame ? (
          <span className="reading-state">
            <ScanLine size={12} strokeWidth={2} aria-hidden="true" />
            reading
          </span>
        ) : (
          <span className="reading-state is-gone">left frame</span>
        )}
      </div>

      {text ? <PlateChip plate={text} /> : <span className="hint">plate located, nothing legible yet</span>}

      <div
        className="reading-votes"
        title={`${entry.votes} independent read${entry.votes === 1 ? "" : "s"} agreeing; ${need} are required before a plate is recorded.`}
      >
        <span className="reading-votes-bar" aria-hidden="true">
          {Array.from({ length: need }, (_, index) => (
            <span key={index} data-filled={index < votes || undefined} />
          ))}
        </span>
        <span className="mono">
          {entry.votes} of {need} agree
        </span>
        <span className="reading-meta mono">
          {entry.reads} read{entry.reads === 1 ? "" : "s"}
          {entry.confidence != null ? ` · ocr ${entry.confidence.toFixed(2)}` : ""}
          {entry.best_width ? ` · ${entry.best_width}px` : ""}
        </span>
      </div>

      {!entry.valid && entry.text && (
        <span className="reading-grammar">
          {entry.edits != null && entry.edits < 99 ? (
            <span className="certainty certainty-inferred">
              <span className="certainty-value mono">{entry.edits}</span>
              <span className="certainty-label">repaired · cannot confirm</span>
            </span>
          ) : (
            <span className="certainty certainty-unknown">
              <span className="certainty-value" aria-hidden="true">
                —
              </span>
              <span className="certainty-label">not a valid plate</span>
            </span>
          )}
        </span>
      )}
    </li>
  );
}

/**
 * What came out of the vote, in three honestly-labelled kinds:
 *
 *   recorded  a sighting in the observation store -- journeys and exports use it
 *   confirmed the vote settled this session but the sighting is not recorded
 *             yet (the stream may not be time-anchored, or the list has not
 *             refreshed); it will be
 *   likely    one agreeing read short of the vote, valid as read. Shown so a
 *             plate the operator watched being read is not simply absent from
 *             this list -- but it is not a sighting and is never recorded.
 *
 * The "likely" bar is the recording threshold minus one read, and applies to
 * this list only: what enters the observation store is unchanged.
 */
function Confirmed({ cameraId, sightings, readings, need, live, cameraName }) {
  const [shown, setShown] = useState(null);
  const alertsBySighting = useWatchlistAlerts(cameraId);

  const items = useMemo(() => {
    const recorded = (sightings ?? []).map((sighting) => ({
      kind: "recorded",
      key: `s${sighting.id}`,
      plate: sighting.plate,
      at: Date.parse(sighting.seen_at),
      sighting,
    }));
    const recordedPlates = new Set(recorded.map((item) => item.plate));
    const session = [];
    for (const entry of readings) {
      if (!entry.text || recordedPlates.has(entry.text)) continue;
      if (entry.confirmed) {
        session.push({ kind: "confirmed", key: `t${entry.track_id}`, plate: entry.text, at: entry.confirmedAt ?? entry.firstSeen, entry });
      } else if (entry.valid && entry.edits === 0 && entry.bestVotes >= Math.max(2, need - 1)) {
        session.push({ kind: "likely", key: `t${entry.track_id}`, plate: `${entry.text}?`, at: entry.firstSeen, entry });
      }
    }
    // Oldest first, newest at the bottom, like the reading log above it.
    return [...recorded, ...session].sort((a, b) => a.at - b.at);
  }, [sightings, readings, need]);

  const [bodyRef, onScroll] = useFollowNewest(items.length);
  const recordedCount = items.filter((item) => item.kind === "recorded").length;

  return (
    <Section
      title="Confirmed"
      className="rail-confirmed"
      count={items.length ? `${recordedCount} recorded · ${items.length}` : null}
      bodyRef={bodyRef}
      onScroll={onScroll}
      label="Confirmed and likely plates"
      foot={
        <>
          <b>recorded</b> sightings are stored · <b>likely</b> is one read short of the {need}-read vote and is never
          recorded{cameraName ? ` · ${cameraName}` : ""}
        </>
      }
    >
      {items.length === 0 ? (
        <p className="hint">
          {live
            ? "Nothing has reached the vote on this camera yet. Plates still being read stay in the list above."
            : "Nothing recorded from this camera in the recent window."}
        </p>
      ) : (
        <ul className="sighting-list">
          {items.map((item) => {
            const alert = item.sighting ? alertsBySighting.get(item.sighting.id) : null;
            const sighting = item.sighting;
            return (
              <li key={item.key} className="sighting-row" data-kind={item.kind} data-alert={alert ? "true" : undefined}>
                {sighting ? (
                  <EvidenceThumb sighting={sighting} onOpen={() => setShown(sighting)} />
                ) : (
                  <span className="sighting-thumb sighting-thumb-empty" aria-hidden="true">
                    <ScanLine size={15} strokeWidth={1.75} />
                  </span>
                )}
                <div className="sighting-body">
                  <PlateChip plate={item.plate} />
                  <span className="sighting-meta">
                    <span className={`sighting-kind is-${item.kind}`}>{item.kind}</span>
                    {sighting ? (
                      <>
                        {sighting.vehicle_type ? ` · ${humanize(sighting.vehicle_type)}` : ""}
                        {sighting.confidence != null && (
                          <>
                            {" · "}
                            <span className="mono">{Number(sighting.confidence).toFixed(2)}</span>
                          </>
                        )}
                        {sighting.raw_ocr_text && sighting.raw_ocr_text !== sighting.plate && (
                          <>
                            {" · "}
                            <span className="certainty certainty-inferred" title="What OCR read before the plate grammar repaired it">
                              <span className="certainty-value mono">{sighting.raw_ocr_text}</span>
                              <span className="certainty-label">raw</span>
                            </span>
                          </>
                        )}
                      </>
                    ) : (
                      <>
                        {item.entry.vehicle ? ` · ${humanize(item.entry.vehicle)}` : ""}
                        {` · ${Math.min(item.entry.bestVotes, need)} of ${need}`}
                      </>
                    )}
                  </span>
                  {alert && (
                    <span className="sighting-alert">
                      <ShieldAlert size={12} strokeWidth={2.25} aria-hidden="true" />
                      Watchlist match{alert.status !== "open" ? ` · ${alert.status}` : ""}
                    </span>
                  )}
                </div>
                <time className="sighting-time mono" title={sighting ? `Source time ${sighting.seen_at}` : "Seen in this session"}>
                  {fmtWhen(item.at)}
                </time>
              </li>
            );
          })}
        </ul>
      )}

      <ImageLightbox
        open={Boolean(shown)}
        src={shown ? evidenceUrl(shown.id) : null}
        filename={shown ? `${shown.plate ?? "plate"}-${shown.id}.jpg` : "evidence.jpg"}
        onClose={() => setShown(null)}
      />
    </Section>
  );
}

/**
 * A sighting's evidence crop, honest about whether it still exists.
 *
 * `has_evidence` only says a crop was recorded. Crops are deleted after the
 * retention window (72h by default, EVIDENCE_RETENTION_HOURS), and the
 * database is shared across machines while each crop lives on the disk of the
 * machine whose worker saved it -- so the flag can be true for a file this
 * backend cannot serve. It answers 404 ("Evidence image has expired and is no
 * longer on disk"), and the thumbnail used to stay a clickable button that
 * opened an empty dialog. Now a crop that fails to load says so and cannot be
 * opened, the same way frontend-v5's Evidence component falls back.
 */
function EvidenceThumb({ sighting, onOpen }) {
  const [failed, setFailed] = useState(false);
  const available = sighting.has_evidence && !failed;
  return (
    <button
      type="button"
      className="sighting-thumb"
      data-expired={sighting.has_evidence && failed ? "true" : undefined}
      disabled={!available}
      title={
        available
          ? "Open the evidence crop"
          : sighting.has_evidence
            ? "Evidence crop has expired (retention window) or is on another machine's disk"
            : "No evidence image recorded"
      }
      onClick={() => available && onOpen()}
    >
      {available ? (
        <img src={evidenceUrl(sighting.id)} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
      ) : (
        <Car size={16} strokeWidth={1.75} aria-hidden="true" />
      )}
    </button>
  );
}

/** Watchlist alerts raised on this camera, keyed by the sighting that raised them. */
function useWatchlistAlerts(cameraId) {
  const [bySighting, setBySighting] = useState(() => new Map());
  usePolling(
    async (signal) => {
      try {
        const rows = await api(`/alerts?camera_id=${encodeURIComponent(cameraId)}&limit=50`, { signal });
        const map = new Map();
        for (const alert of rows ?? []) {
          if (alert.alert_type === "watchlist" && alert.sighting_id != null) map.set(alert.sighting_id, alert);
        }
        setBySighting((prev) =>
          prev.size === map.size && [...map].every(([id, alert]) => prev.get(id)?.status === alert.status) ? prev : map,
        );
      } catch {
        // a failed or cancelled poll just tries again next tick
      }
    },
    15000,
    Boolean(cameraId),
  );
  return bySighting;
}

/**
 * Person output is a 30-second count window, not an event stream, so it is drawn
 * as a window bar chart -- the shape over the last few minutes is the
 * information. A window with nobody in it is a real measurement and is plotted,
 * not skipped.
 */
function PersonCounts({ cameraId, live }) {
  const [windows, setWindows] = useState([]);

  usePolling(
    async (signal) => {
      try {
        const rows = await api(`/analytics/counts?camera_id=${encodeURIComponent(cameraId)}&limit=40`, { signal });
        setWindows(Array.isArray(rows) ? rows.filter((row) => row.mode === "person") : []);
      } catch {
        // a failed poll just tries again next tick
      }
    },
    15000,
    Boolean(cameraId),
  );

  const recent = windows.slice(0, 24).reverse();
  const peak = Math.max(1, ...recent.map((row) => row.unique_tracks ?? 0));

  return (
    <Section
      title="Count windows"
      className="rail-events"
      count={windows.length || null}
      label="Person count windows"
      foot="Distinct tracked people per 30s window — a floor, not a footfall total."
    >
      {recent.length === 0 ? (
        <p className="hint">
          {live
            ? "The person worker records how many distinct people it tracked every 30 seconds. The first window posts within half a minute."
            : "No count windows recorded for this camera."}
        </p>
      ) : (
        <>
          <div className="count-bars" role="img" aria-label={`People per 30-second window, last ${recent.length} windows, peak ${peak}`}>
            {recent.map((row) => (
              <span
                key={row.id}
                className="count-bar"
                style={{ height: `${Math.max(4, ((row.unique_tracks ?? 0) / peak) * 100)}%` }}
                title={`${fmtClock(row.window_start)} · ${row.unique_tracks} ${row.unique_tracks === 1 ? "person" : "people"}`}
              />
            ))}
          </div>
          <ul className="count-list">
            {windows.slice(0, 12).map((row) => (
              <li key={row.id}>
                <span className="mono count-list-value">{row.unique_tracks}</span>
                <span>{row.unique_tracks === 1 ? "person" : "people"}</span>
                <time className="mono" dateTime={row.window_start}>
                  {fmtClock(row.window_start)}
                </time>
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  );
}

/**
 * Suspicious output is an alert, which lives in the alert queue like any other,
 * so this links there rather than reimplementing acknowledge and resolve. A
 * suspicious alert has no plate and no reason code; what it says is in `label`.
 */
function SuspiciousAlerts({ cameraId, live }) {
  const [alerts, setAlerts] = useState([]);

  usePolling(
    async (signal) => {
      try {
        const rows = await api(`/alerts?camera_id=${encodeURIComponent(cameraId)}&limit=30`, { signal });
        setAlerts(Array.isArray(rows) ? rows.filter((row) => row.alert_type === "suspicious").reverse() : []);
      } catch {
        // a failed poll just tries again next tick
      }
    },
    10000,
    Boolean(cameraId),
  );
  const [bodyRef, onScroll] = useFollowNewest(alerts.length);

  return (
    <Section
      title="Alerts raised"
      className="rail-events"
      count={alerts.length || null}
      bodyRef={bodyRef}
      onScroll={onScroll}
      label="Suspicious-activity alerts"
      foot={
        <>
          Raised after three consecutive frames agree · acknowledge or resolve in <Link to="/alerts">Alerts</Link>
        </>
      }
    >
      {alerts.length === 0 ? (
        <p className="hint">
          {live
            ? "Nothing flagged. A person must be classified potentially dangerous in three consecutive frames before an alert is raised."
            : "No suspicious-activity alerts from this camera."}
        </p>
      ) : (
        <ul className="susp-list">
          {alerts.map((alert) => (
            <li key={alert.id}>
              <span className="susp-icon" aria-hidden="true">
                <ShieldAlert size={14} strokeWidth={2} />
              </span>
              <span className="susp-body">
                <span className={`badge badge-${alert.status === "open" ? "bad" : "ok"}`}>{alert.status}</span>
                <span className="susp-reason">{alert.label ?? "Potentially dangerous person"}</span>
                {alert.match_confidence != null && (
                  <span className="mono susp-conf">{Number(alert.match_confidence).toFixed(2)}</span>
                )}
              </span>
              <time className="mono" dateTime={alert.event_time}>
                {fmtClock(alert.event_time)}
              </time>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
