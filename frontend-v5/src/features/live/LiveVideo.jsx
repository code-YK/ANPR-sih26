import { Radio, WifiOff } from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";

import { Badge, Spinner, Tooltip } from "../../components/ui.jsx";
import { useHls } from "../../lib/media/useHls.js";
import {
  acquireWebRtc,
  isWebRtcUnsuitable,
  markWebRtcFailed,
  markWebRtcLive,
  releaseWebRtc,
  rememberWebRtcUnsuitable,
  subscribeWebRtc,
  webrtcHealth,
} from "../../lib/media/webrtcSessions.js";
import { capturePoster, getPoster } from "./posters.js";
import styles from "./LiveVideo.module.css";

/** A WebRTC session that connects but never decodes a frame is treated as failed. */
const FIRST_FRAME_TIMEOUT_MS = 12_000;
/** Live video that stops decoding for this long falls back to HLS. */
const STALL_FALLBACK_MS = 5_000;
/** More than FREEZE_BUDGET_S of freezes inside FREEZE_WINDOW_MS also falls back. */
const FREEZE_WINDOW_MS = 12_000;
const FREEZE_BUDGET_S = 2.5;

function onFirstFrame(video, callback) {
  if ("requestVideoFrameCallback" in HTMLVideoElement.prototype) {
    const handle = video.requestVideoFrameCallback(() => callback());
    return () => video.cancelVideoFrameCallback(handle);
  }
  const handler = () => callback();
  video.addEventListener("playing", handler, { once: true });
  return () => video.removeEventListener("playing", handler);
}

/**
 * Keep a recent still of a playing feed. Captured on an interval rather than
 * at teardown: by then the player has already detached its media source.
 */
function usePosterCapture(videoRef, cameraId, playing) {
  useEffect(() => {
    if (!playing) return undefined;
    const capture = () => capturePoster(videoRef.current, cameraId);
    // Jittered so a wall of tiles that started together never captures on the same frame.
    const first = setTimeout(capture, 1_500 + Math.random() * 2_000);
    const id = setInterval(capture, 20_000 + Math.random() * 5_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [videoRef, cameraId, playing]);
}

/**
 * A grid/filmstrip tile's player. `active` mounts or tears down the HLS
 * connection -- a paused player would still hold a stream copy open.
 */
export const HlsTileVideo = memo(function HlsTileVideo({ cameraId, active, className, onState }) {
  const videoRef = useRef(null);
  const { state } = useHls(videoRef, cameraId, { enabled: active });

  useEffect(() => {
    onState?.(state);
  }, [state, onState]);

  usePosterCapture(videoRef, cameraId, state === "playing");

  const poster = getPoster(cameraId);
  return (
    <div className={`${styles.frame} ${className ?? ""}`}>
      {poster && state !== "playing" && <img className={styles.poster} src={poster} alt="" aria-hidden="true" />}
      {active && (
        <video
          ref={videoRef}
          className={styles.video}
          data-ready={state === "playing"}
          muted
          playsInline
          autoPlay
          disablePictureInPicture
        />
      )}
    </div>
  );
});

/**
 * The focused camera's raw feed: WebRTC first for near-real-time playback,
 * falling back to HLS if the relay can't start, the connection drops, or no
 * frame decodes (e.g. a source with B-frames, which WebRTC can't carry).
 */
export const RawFeed = memo(function RawFeed({ camera, className, showTransport = true }) {
  const videoRef = useRef(null);
  const cameraId = camera.camera_id;
  // A camera whose WebRTC feed already stalled this session goes straight to HLS.
  const webrtcCapable = Boolean(camera.webrtc_preview_available ?? camera.analytics_stream_available) && !isWebRtcUnsuitable(camera.camera_id);
  const [transport, setTransport] = useState(webrtcCapable ? "webrtc" : camera.stream_available ? "hls" : "none");
  const [webrtcState, setWebrtcState] = useState("connecting");
  const [bufferMs, setBufferMs] = useState(null);
  const [fallbackReason, setFallbackReason] = useState(null);

  useEffect(() => {
    setTransport(webrtcCapable ? "webrtc" : camera.stream_available ? "hls" : "none");
    setFallbackReason(null);
  }, [cameraId, webrtcCapable, camera.stream_available]);

  // WebRTC
  useEffect(() => {
    if (transport !== "webrtc") return undefined;
    const video = videoRef.current;
    const session = acquireWebRtc(cameraId);
    let cancelFrame = null;
    let firstFrameTimer = null;

    const sync = (current) => {
      setWebrtcState(current.state);
      if (current.state === "failed" || current.state === "closed") {
        setFallbackReason(current.error ?? "WebRTC unavailable");
        setTransport(camera.stream_available ? "hls" : "none");
        return;
      }
      if (current.stream && video && video.srcObject !== current.stream) {
        video.srcObject = current.stream;
        video.play().catch(() => {});
        cancelFrame?.();
        cancelFrame = onFirstFrame(video, () => {
          clearTimeout(firstFrameTimer);
          markWebRtcLive(current);
        });
      }
    };

    const unsubscribe = subscribeWebRtc(session, sync);
    sync(session);
    if (session.state !== "live") {
      firstFrameTimer = setTimeout(() => {
        if (session.state !== "live") markWebRtcFailed(session, "No video frame arrived over WebRTC");
      }, FIRST_FRAME_TIMEOUT_MS);
    }

    // A connected session can still stall or stutter -- a source with B-frames
    // decodes out of order over WebRTC, and MediaMTX drops frames when the
    // reader falls behind. Watch the decoder itself and fall back to HLS if
    // video stops advancing or keeps freezing.
    let lastDecoded = null;
    let lastAdvanceAt = Date.now();
    let freezeBaseline = null;
    const statsTimer = setInterval(async () => {
      const health = await webrtcHealth(session);
      if (!health) return;
      if (health.bufferMs != null) setBufferMs((previous) => (previous != null && Math.abs(previous - health.bufferMs) < 15 ? previous : health.bufferMs));
      if (session.state !== "live") return;
      const now = Date.now();
      if (health.framesDecoded !== lastDecoded) {
        lastDecoded = health.framesDecoded;
        lastAdvanceAt = now;
      } else if (now - lastAdvanceAt > STALL_FALLBACK_MS) {
        rememberWebRtcUnsuitable(cameraId);
        markWebRtcFailed(session, "WebRTC video stopped advancing");
        return;
      }
      if (health.totalFreezesDuration != null) {
        if (freezeBaseline === null) freezeBaseline = { at: now, seconds: health.totalFreezesDuration };
        else if (now - freezeBaseline.at >= FREEZE_WINDOW_MS) {
          if (health.totalFreezesDuration - freezeBaseline.seconds > FREEZE_BUDGET_S) {
            rememberWebRtcUnsuitable(cameraId);
            markWebRtcFailed(session, "WebRTC video kept freezing");
            return;
          }
          freezeBaseline = { at: now, seconds: health.totalFreezesDuration };
        }
      }
    }, 2_000);

    return () => {
      unsubscribe();
      cancelFrame?.();
      clearTimeout(firstFrameTimer);
      clearInterval(statsTimer);
      if (video) video.srcObject = null;
      releaseWebRtc(session);
    };
  }, [transport, cameraId, camera.stream_available]);

  // HLS fallback
  const hls = useHls(videoRef, cameraId, { enabled: transport === "hls", trackLatency: showTransport });

  const playing = transport === "webrtc" ? webrtcState === "live" : hls.state === "playing";
  usePosterCapture(videoRef, cameraId, playing);
  const poster = getPoster(cameraId);

  if (transport === "none") {
    return (
      <div className={`${styles.frame} ${styles.unavailable} ${className ?? ""}`}>
        <div className={styles.center}>
          <WifiOff aria-hidden="true" />
          <span>{fallbackReason ? "Live video unavailable" : "No stream configured for this camera"}</span>
          {fallbackReason && <small>{fallbackReason}</small>}
        </div>
      </div>
    );
  }

  return (
    <div className={`${styles.frame} ${className ?? ""}`}>
      {poster && !playing && <img className={styles.poster} src={poster} alt="" aria-hidden="true" />}
      <video
        ref={videoRef}
        className={styles.video}
        data-ready={playing}
        muted
        playsInline
        autoPlay
        disablePictureInPicture
        aria-label={`Live video, ${camera.name}`}
      />
      {!playing && (
        <div className={styles.connecting}>
          <Spinner />
          <span>{transport === "webrtc" ? "Connecting in real time…" : hls.state === "reconnecting" ? "Reconnecting…" : "Connecting…"}</span>
        </div>
      )}
      {showTransport && (
        <div className={styles.transport}>
          <TransportChip transport={transport} playing={playing} latency={hls.latency} bufferMs={bufferMs} fallbackReason={fallbackReason} />
        </div>
      )}
    </div>
  );
});

export function TransportChip({ transport, playing, latency, bufferMs, fallbackReason }) {
  if (transport === "webrtc") {
    return (
      <Tooltip
        content={
          bufferMs != null
            ? `WebRTC via the local relay. Receiver buffer ${Math.round(bufferMs)} ms.`
            : "WebRTC via the local relay — the lowest-latency path."
        }
      >
        <Badge tone={playing ? "live" : "pending"} icon={<Radio aria-hidden="true" />}>
          {playing ? "Real-time" : "Connecting"}
        </Badge>
      </Tooltip>
    );
  }
  const behind = latency != null ? `${latency.toFixed(1)} s behind` : null;
  return (
    <Tooltip content={fallbackReason ? `HLS fallback: ${fallbackReason}` : "HLS stream through the backend relay"}>
      <Badge tone={playing ? undefined : "pending"}>{`HLS${behind ? ` · ${behind}` : ""}`}</Badge>
    </Tooltip>
  );
}
