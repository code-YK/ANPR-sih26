import { useEffect, useState } from "react";

import { API, api } from "../../api.js";
import { usePolling } from "../../hooks/usePolling.js";

/**
 * What the detector is actually seeing on this camera: the latest annotated
 * frame (boxes, track ids, plate belief) plus rolling counts.
 *
 * This exists because a running worker was previously invisible unless it
 * confirmed a plate -- and most sandbox cameras were surveyed as unable to
 * resolve one at all, so a perfectly healthy detector could run for an hour
 * and show nothing. Vehicle/person detection was happening the whole time
 * and simply had nowhere to appear.
 *
 * Deliberately labelled a detector view, not an overlay: the worker holds
 * its own connection to the stream, independent of the browser's player, so
 * the two are seconds apart by construction and drawing these boxes on top
 * of the live video would misrepresent them as frame-accurate.
 */
export default function DetectorView({ cameraId, mode, restartKey = 0 }) {
  const [telemetry, setTelemetry] = useState(null);
  const [missing, setMissing] = useState(false);
  // One long-lived MJPEG connection, rendered natively by the <img>. The
  // `k` token exists only to force a brand-new connection when the camera
  // or mode changes (or after a reconnect), never to fetch a frame.
  //
  // This replaced per-frame polling of /analytics/snapshot. Polling could
  // not be made to work here at any interval: nine HLS players on this
  // origin exhaust the browser's ~6-connection HTTP/1.1 budget, so snapshot
  // requests queued for seconds behind video segments and the <img> often
  // never completed a load at all -- a blank panel, or one several seconds
  // behind the live player, while the worker itself was reporting 24 fps.
  // See the backend's analytics_stream docstring for the measurements.
  const [k, setK] = useState(0);

  useEffect(() => {
    setTelemetry(null);
    setMissing(false);
    setK((n) => n + 1);
  }, [cameraId, mode, restartKey]);

  usePolling(async () => {
    try {
      setTelemetry(await api(`/analytics/telemetry/${cameraId}?mode=${mode}`));
      setMissing(false);
    } catch (_) {
      // 404 simply means no worker has published for this camera yet
      setMissing(true);
    }
  }, 500);

  if (missing || !telemetry) {
    return <p className="hint">No detector output yet — start {mode} analytics to see detections.</p>;
  }

  const lastSeen = telemetry.last_detection_at
    ? `${Math.round(Date.now() / 1000 - telemetry.last_detection_at)}s ago`
    : "nothing yet";

  return (
    <div className="detector-view">
      <img
        className="detector-frame"
        src={`${API}/analytics/stream/${cameraId}?mode=${mode}&k=${k}`}
        alt={`Live ${mode} detections on camera ${cameraId}`}
        // The stream ends itself when the worker stops publishing; retry so
        // the view comes back on its own once a worker is running again.
        onError={() => setTimeout(() => setK((n) => n + 1), 2000)}
      />
      {telemetry.stale && (
        <p className="hint detector-stale">
          Detector output is {telemetry.age_seconds}s old — the worker may have stopped.
        </p>
      )}
      <dl className="detector-stats">
        <div><dt>tracked now</dt><dd>{telemetry.tracked_now}</dd></div>
        <div><dt>unique tracks</dt><dd>{telemetry.unique_tracks}</dd></div>
        <div><dt>peak</dt><dd>{telemetry.peak_tracked}</dd></div>
        <div><dt>fps</dt><dd>{telemetry.fps ?? "—"}</dd></div>
        <div><dt>last detection</dt><dd>{lastSeen}</dd></div>
        {(mode === "vehicle" || mode === "vehicle_finetuned") && (
          <div><dt>plates reported</dt><dd>{telemetry.plates_reported ?? 0}</dd></div>
        )}
        {telemetry.queue_capacity != null && (
          <div>
            <dt title="Decoded frames waiting for inference. Rising means this worker is falling behind the live feed -- normal briefly after a stream stall, a problem if it stays near capacity.">
              backlog
            </dt>
            <dd>
              <meter
                className="backlog-meter"
                min="0"
                max={telemetry.queue_capacity}
                value={telemetry.queue_depth}
                low={telemetry.queue_capacity * 0.5}
                high={telemetry.queue_capacity * 0.8}
                optimum={0}
              />
              {" "}{telemetry.queue_depth}/{telemetry.queue_capacity}
            </dd>
          </div>
        )}
        {telemetry.resyncs > 0 && (
          <div>
            <dt title="Times the worker reconnected specifically to get back to the live edge, after decoding had fallen behind the stream. Distinct from reconnects forced by the stream dropping.">
              live re-syncs
            </dt>
            <dd>{telemetry.resyncs}</dd>
          </div>
        )}
        {telemetry.dropped_frames > 0 && (
          <div>
            <dt title="Frames evicted because the backlog above was already full when a new one arrived -- these were never seen by the detector.">
              dropped
            </dt>
            <dd>{telemetry.dropped_frames}</dd>
          </div>
        )}
        {mode === "person" && (
          <div><dt>windows posted</dt><dd>{telemetry.windows_posted ?? 0}</dd></div>
        )}
        {mode === "suspicious" && (
          <>
            <div>
              <dt title="People classified as potentially dangerous in the frame just processed.">
                dangerous now
              </dt>
              <dd>{telemetry.dangerous_now ?? 0}</dd>
            </div>
            <div>
              <dt title="Alerts this worker has raised for potentially dangerous people. Each tracked person alerts once; see the Alerts view.">
                alerts raised
              </dt>
              <dd>{telemetry.alerts_raised ?? 0}</dd>
            </div>
            <div><dt>windows posted</dt><dd>{telemetry.windows_posted ?? 0}</dd></div>
          </>
        )}
      </dl>
      {mode === "suspicious" && telemetry.dangerous_now > 0 && (
        <p className="hint detector-warn">
          {telemetry.dangerous_now} potentially dangerous {telemetry.dangerous_now === 1 ? "person" : "people"} in
          frame now — see the Alerts view for the raised alert.
        </p>
      )}
      {(mode === "vehicle" || mode === "vehicle_finetuned") && telemetry.plates_reported === 0 && telemetry.unique_tracks > 0 && (
        <p className="hint">
          Vehicles are being detected and tracked, but no plate has met the confirmation
          bar on this camera. That is the expected result where the survey marked the
          camera as not ANPR-viable.
        </p>
      )}
      {telemetry.time_anchored === false && (
        <p className="hint detector-warn">
          Stream not yet time-anchored — a confirmed plate would be held back rather
          than recorded with an invented timestamp.
        </p>
      )}
    </div>
  );
}
