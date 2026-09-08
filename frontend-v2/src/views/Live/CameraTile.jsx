import { useEffect, useRef } from "react";

import { hlsProxyUrl } from "../../api.js";
import { AnprBadge, LiveBadge, PlaybackBadge } from "../../components/Badge.jsx";
import StatusDot from "../../components/StatusDot.jsx";
import { useHlsPlayer } from "../../hooks/useHlsPlayer.js";
import { useVisibility } from "../../hooks/useVisibility.js";

/**
 * `active` (decided by LiveView, combining viewport visibility with the
 * global concurrency cap) is the only thing that mounts/unmounts this
 * tile's player -- passing null to useHlsPlayer tears it down, never just
 * pauses it (a paused player still holds its connection open).
 *
 * `analyticsState` ("running"/"queued"/undefined) is this tile's own ANPR
 * state from LiveView's single bulk GET /analytics/status poll -- several
 * cameras can run ANPR at once now (see AnalyticsToggle.jsx), so a strip/
 * grid tile needs to show its own state rather than only the focused
 * camera's side panel knowing it.
 */
export default function CameraTile({ camera, active, focused, paused, analyticsState, onFocus, onVisibilityChange }) {
  const videoRef = useRef(null);
  const [visRef, visible] = useVisibility();

  useEffect(() => {
    onVisibilityChange(camera.camera_id, visible);
    return () => onVisibilityChange(camera.camera_id, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, camera.camera_id]);

  const { stalled, playbackState } = useHlsPlayer(
    active ? (viewer) => hlsProxyUrl(camera, viewer) : null,
    videoRef,
  );

  if (!camera.stream_available) {
    const focusable = Boolean(camera.webrtc_preview_available);
    return (
      <div
        ref={visRef}
        className={`camera-tile camera-tile-empty camera-tile-nostream${focused ? " focused" : ""}`}
        onClick={focusable ? () => onFocus(camera.camera_id) : undefined}
        role={focusable ? "button" : undefined}
        tabIndex={focusable ? 0 : undefined}
        onKeyDown={focusable ? (event) => {
          if (event.key === "Enter" || event.key === " ") onFocus(camera.camera_id);
        } : undefined}
      >
        <div className="camera-tile-placeholder">
          {focusable ? "open focused WebRTC preview" : "no stream endpoint"}
        </div>
        <div className="camera-tile-overlay">
          <span className="camera-tile-name">{camera.name}</span>
          <LiveBadge value={camera.is_live} />
        </div>
      </div>
    );
  }

  return (
    <div
      ref={visRef}
      className={`camera-tile${focused ? " focused" : ""}`}
      onClick={() => onFocus(camera.camera_id)}
    >
      {active ? (
        <>
          <video ref={videoRef} muted playsInline autoPlay />
          {stalled && <div className="tile-reconnecting">reconnecting…</div>}
        </>
      ) : (
        <div className="camera-tile-placeholder camera-tile-capped">
          {/* Distinguishes the two reasons a tile isn't playing. "Paused"
              is a deliberate choice made on this tile's behalf so the
              focused camera gets the connection budget; "waiting for a
              free slot" is the concurrency cap. Showing the cap message
              for both made a paused tile look like it had failed. */}
          {paused ? "paused — focused view" : visible ? "waiting for a free slot…" : ""}
        </div>
      )}
      <div className="camera-tile-overlay">
        <span className="camera-tile-name">{camera.name}</span>
        {active ? <PlaybackBadge state={playbackState} /> : <LiveBadge value={camera.is_live} />}
        {/* Both surveyed outcomes render -- an operator relying on this feed
            for plate reads needs "not viable" as plainly as "viable". An
            un-surveyed camera stays silent here; the tile overlay isn't the
            place to raise "not surveyed" for every un-surveyed camera on
            the wall. */}
        {camera.anpr_viable !== null && camera.anpr_viable !== undefined && (
          <AnprBadge value={camera.anpr_viable} />
        )}
        {/* Silent for the vast majority of tiles that never have ANPR
            enabled -- only rendered once there's an actual state to show,
            so it doesn't add noise to every camera on the wall. */}
        {(analyticsState === "running" || analyticsState === "queued") && (
          <StatusDot
            state={analyticsState}
            title={analyticsState === "running" ? "ANPR running" : "ANPR enabled, waiting for a worker slot"}
          />
        )}
      </div>
    </div>
  );
}
