import { useEffect, useRef, useState } from "react";

import { hlsProxyUrl } from "../../api.js";
import { useHlsPlayer } from "../../hooks/useHlsPlayer.js";
import { useWebRtcPlayer } from "../../hooks/useWebRtcPlayer.js";

/**
 * Latency here is inherent to HLS (6-15s, driven by segment duration) and
 * buffering doesn't fix it -- more buffer makes it worse. Rather than
 * fighting it, hls.js's own `.latency` estimate (distance from the live
 * edge) is surfaced directly: honest, pre-empts the obvious question, costs
 * nothing. The sandbox serves recorded footage, so nothing here is
 * time-critical.
 *
 * Transport selection: WebRTC (a local MediaMTX relay -- see
 * backend/app/pipeline/webrtc_relay.py) is tried first for a genuine
 * low-latency preview; a one-shot failure (relay never starts, negotiation
 * rejected) falls back to the existing HLS path below. The two are never
 * run at once -- that would open a second gateway connection per
 * GOV-ING-012 for no benefit once one transport is already working.
 */
export default function FocusedPlayer({ camera }) {
  const videoRef = useRef(null);
  const hlsRef = useRef(null);
  const [latency, setLatency] = useState(null);
  const [transport, setTransport] = useState("webrtc");

  useEffect(() => {
    setTransport(camera?.webrtc_preview_available ? "webrtc" : "hls");
  }, [camera?.camera_id, camera?.webrtc_preview_available]);

  const { failed: webrtcFailed } = useWebRtcPlayer(
    transport === "webrtc" ? camera : null,
    videoRef,
  );

  useEffect(() => {
    if (webrtcFailed) setTransport(camera?.stream_available ? "hls" : "unavailable");
  }, [webrtcFailed, camera?.stream_available]);

  const { reconnects, stalled, playbackState } = useHlsPlayer(
    transport === "hls" && camera?.stream_available ? (viewer) => hlsProxyUrl(camera, viewer) : null,
    videoRef,
    (hls) => {
      hlsRef.current = hls;
    },
  );

  useEffect(() => {
    if (transport !== "hls") {
      setLatency(null);
      return undefined;
    }
    const interval = setInterval(() => {
      const l = hlsRef.current?.latency;
      if (typeof l === "number" && Number.isFinite(l)) setLatency(l);
    }, 1000);
    return () => clearInterval(interval);
  }, [transport]);

  if (!camera) {
    return <div className="focused-player empty">Select a camera to focus it.</div>;
  }

  if (!camera.webrtc_preview_available && !camera.stream_available) {
    return <div className="focused-player empty">{camera.name} has no RTSP or HLS preview source.</div>;
  }

  if (transport === "unavailable") {
    return (
      <div className="focused-player empty">
        WebRTC could not connect to this RTSP-only source, and no HLS fallback is configured.
      </div>
    );
  }

  return (
    <div className="focused-player">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video ref={videoRef} muted playsInline autoPlay />
      <div className={transport === "webrtc" ? "transport-indicator" : "transport-indicator fallback"}>
        {transport === "webrtc" ? "webrtc" : "hls (fallback)"}
      </div>
      {transport === "hls" && latency != null && !stalled && (
        <div className="live-lag-indicator">live −{latency.toFixed(0)}s</div>
      )}
      {transport === "hls" && playbackState === "connecting" && (
        <div className="live-lag-indicator reconnecting">connecting…</div>
      )}
      {transport === "hls" && stalled && <div className="live-lag-indicator reconnecting">reconnecting…</div>}
      {/* Reconnects are shown rather than hidden: this gateway expires a
          session every ~15-35s, so a long-running player genuinely is a
          series of sessions, and presenting it as one unbroken feed would
          misrepresent what the operator is watching. */}
      {transport === "hls" && reconnects > 0 && (
        <div className="reconnect-count">{reconnects} reconnect{reconnects === 1 ? "" : "s"}</div>
      )}
    </div>
  );
}
