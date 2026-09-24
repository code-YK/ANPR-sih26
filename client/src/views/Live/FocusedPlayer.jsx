import { useEffect, useRef, useState } from "react";

import { hlsProxyUrl } from "../../api.js";
import { useHlsPlayer } from "../../hooks/useHlsPlayer.js";
import { getPoster, usePosterCapture } from "../../lib/posters.js";

/**
 * Latency here is inherent to HLS (6-15s, driven by segment duration) and
 * buffering doesn't fix it -- more buffer makes it worse. Rather than
 * fighting it, hls.js's own `.latency` estimate (distance from the live
 * edge) is surfaced directly: honest, pre-empts the obvious question, costs
 * nothing. The sandbox serves recorded footage, so nothing here is
 * time-critical.
 *
 * HLS-only: the recorded-feed relay serves HLS (and RTSP), never WebRTC, so
 * the previous WebRTC-first path only ever opened a second gateway connection
 * and stalled through a negotiation timeout before falling back to HLS anyway.
 */
export default function FocusedPlayer({ camera, onLatency }) {
  const videoRef = useRef(null);
  const hlsRef = useRef(null);
  const [latency, setLatency] = useState(null);
  // Whether the <video> is actually presenting frames, from the element's own
  // events.
  const [playing, setPlaying] = useState(false);
  useEffect(() => setPlaying(false), [camera?.camera_id]);
  usePosterCapture(videoRef, camera?.camera_id, playing);
  const poster = camera ? getPoster(camera.camera_id) : null;

  const { reconnects, stalled, playbackState } = useHlsPlayer(
    camera?.stream_available ? (viewer) => hlsProxyUrl(camera, viewer) : null,
    videoRef,
    (hls) => {
      hlsRef.current = hls;
    },
  );

  // `onLatency` reports hls.js's live-edge estimate outward so the detector's
  // own "behind live" reading can be shown against the player's.
  useEffect(() => {
    const interval = setInterval(() => {
      const l = hlsRef.current?.latency;
      if (typeof l === "number" && Number.isFinite(l)) {
        setLatency(l);
        onLatency?.(l);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [onLatency]);

  if (!camera) {
    return <div className="focused-player empty">Select a camera to focus it.</div>;
  }

  if (!camera.stream_available) {
    return <div className="focused-player empty">{camera.name} has no HLS preview source.</div>;
  }

  return (
    <div className="focused-player">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      {/* The camera's last still, held under the player until it presents a
          frame, so opening a camera never flashes black while HLS buffers its
          first segment. */}
      {poster && !playing && <img className="focused-player-poster" src={poster.url} alt="" aria-hidden="true" />}
      <video
        ref={videoRef}
        muted
        playsInline
        autoPlay
        onPlaying={() => setPlaying(true)}
        onWaiting={() => setPlaying(false)}
        onEmptied={() => setPlaying(false)}
      />
      {latency != null && !stalled && (
        <div className="live-lag-indicator">live −{latency.toFixed(0)}s</div>
      )}
      {playbackState === "connecting" && (
        <div className="live-lag-indicator reconnecting">connecting…</div>
      )}
      {stalled && <div className="live-lag-indicator reconnecting">reconnecting…</div>}
      {/* Reconnects are shown rather than hidden: this gateway expires a
          session every ~15-35s, so a long-running player genuinely is a
          series of sessions, and presenting it as one unbroken feed would
          misrepresent what the operator is watching. */}
      {reconnects > 0 && (
        <div className="reconnect-count">{reconnects} reconnect{reconnects === 1 ? "" : "s"}</div>
      )}
    </div>
  );
}
