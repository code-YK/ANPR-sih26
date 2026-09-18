// The light build: no subtitles, alternate audio or DRM, none of which a CCTV
// relay uses -- roughly a third less JavaScript on every Live screen.
import Hls from "hls.js/light";
import { useEffect, useRef, useState } from "react";

import { hlsUrl } from "../api/media.js";

const STALL_TIMEOUT_MS = 12_000;
const STALL_POLL_MS = 3_000;
const RECONNECT_BASE_MS = 2_000;
const RECONNECT_MAX_MS = 30_000;

/**
 * hls.js tuned for live-edge playback of relayed CCTV.
 *
 * Latency is dominated by segment duration (set by each clip's keyframe
 * interval) times how many segments behind the live edge the player sits.
 * The v3 console sat 3 segments back with a 30s buffer; this sits 2 back,
 * speeds playback up slightly to catch up after a stall instead of staying
 * behind forever, and keeps buffers short because nothing here seeks.
 *
 * Returns the player's own state plus the measured distance from the live
 * edge -- shown to the operator rather than hidden.
 */
export function useHls(videoRef, cameraId, { enabled = true, trackLatency = false } = {}) {
  const [epoch, setEpoch] = useState(0);
  const [state, setState] = useState("idle");
  const [latency, setLatency] = useState(null);
  const backoffRef = useRef(RECONNECT_BASE_MS);
  const instanceRef = useRef(Math.random().toString(36).slice(2, 10));

  useEffect(() => {
    const video = videoRef.current;
    if (!enabled || !cameraId || !video) {
      setState("idle");
      setLatency(null);
      return undefined;
    }

    const viewer = `${instanceRef.current}-${epoch}`;
    const src = hlsUrl(cameraId, viewer);
    let destroyed = false;
    let reconnectTimer = null;
    setState((current) => (current === "reconnecting" ? current : "connecting"));
    video.crossOrigin = "use-credentials";

    const reconnect = () => {
      if (destroyed || reconnectTimer) return;
      setState("reconnecting");
      const delay = backoffRef.current;
      backoffRef.current = Math.min(backoffRef.current * 2, RECONNECT_MAX_MS);
      reconnectTimer = setTimeout(() => setEpoch((value) => value + 1), delay);
    };

    if (Hls.isSupported()) {
      const hls = new Hls({
        xhrSetup: (xhr) => {
          xhr.withCredentials = true;
        },
        lowLatencyMode: false,
        liveSyncDurationCount: 2,
        liveMaxLatencyDurationCount: 6,
        maxLiveSyncPlaybackRate: 1.25,
        maxBufferLength: 12,
        backBufferLength: 6,
        manifestLoadingMaxRetry: 2,
        manifestLoadingRetryDelay: 1_500,
        fragLoadingMaxRetry: 3,
        fragLoadingRetryDelay: 800,
        enableWorker: true,
      });
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {});
      });
      hls.on(Hls.Events.FRAG_BUFFERED, () => {
        backoffRef.current = RECONNECT_BASE_MS;
        setState("playing");
      });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal || destroyed) return;
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          hls.recoverMediaError();
          return;
        }
        reconnect();
      });

      let lastTime = -1;
      let lastProgressAt = Date.now();
      const watchdog = setInterval(() => {
        // Only the focused player shows latency; tiles skip the re-render.
        const l = hls.latency;
        if (trackLatency && Number.isFinite(l)) setLatency((previous) => (previous != null && Math.abs(previous - l) < 0.1 ? previous : l));
        if (video.paused || video.ended) return;
        if (video.currentTime !== lastTime) {
          lastTime = video.currentTime;
          lastProgressAt = Date.now();
          return;
        }
        if (Date.now() - lastProgressAt > STALL_TIMEOUT_MS) {
          clearInterval(watchdog);
          reconnect();
        }
      }, STALL_POLL_MS);

      return () => {
        destroyed = true;
        clearInterval(watchdog);
        clearTimeout(reconnectTimer);
        hls.destroy();
      };
    }

    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      video.play().catch(() => {});
      const onPlaying = () => setState("playing");
      video.addEventListener("playing", onPlaying);
      video.addEventListener("error", reconnect);
      return () => {
        destroyed = true;
        clearTimeout(reconnectTimer);
        video.removeEventListener("playing", onPlaying);
        video.removeEventListener("error", reconnect);
        video.removeAttribute("src");
        video.load();
      };
    }

    setState("unsupported");
    return undefined;
  }, [videoRef, cameraId, enabled, epoch, trackLatency]);

  return { state, latency };
}
