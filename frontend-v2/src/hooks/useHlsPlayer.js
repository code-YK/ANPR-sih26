import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Hls from "hls.js";

// The gateway expires a session's media playlist every ~15-35s in this
// sandbox -- measured directly against the raw gateway, with no proxy and a
// single consumer, across nine cameras. The Python workers already survive
// it by reconnecting (their logs show dozens of reconnects per run); hls.js
// on its own does not, because an expired session returns a *structurally
// valid* empty playlist rather than an error, so there is nothing for its
// retry logic to catch. Playback simply freezes.
//
// So the browser player reconnects the same way the workers do: watch for
// playback that has stopped advancing, then rebuild with a fresh session.
const STALL_TIMEOUT_MS = 12000;
const STALL_POLL_MS = 3000;
// Bounded exponential backoff, per GOV-ING-006.
const RECONNECT_BASE_MS = 2000;
const RECONNECT_MAX_MS = 30000;

/**
 * Attaches hls.js to a <video> element for `src`, tears it down whenever
 * `src` changes (including to null) or the component unmounts, and
 * transparently reconnects when the stream stalls.
 *
 * `hls.destroy()` on cleanup is mandatory, not tidiness: a leaked instance
 * holds a gateway connection open, and GOV-ING-012 counts every connection
 * as a stream copy. Passing `src=null` (a tile scrolling out of view, or
 * the concurrency cap being reached) tears the player down through this
 * same path -- LiveView controls mount/unmount purely by flipping `src`.
 *
 * Returns the actual state of this player (`connecting`, `connected`, or
 * `reconnecting`) in addition to the reconnect count. A catalogue's `live`
 * bit and the presence of an HLS URL are both metadata; only a buffered
 * fragment proves this browser currently has media.
 */
export function useHlsPlayer(makeSrc, videoRef, onHlsReady) {
  // `epoch` forces a full teardown+rebuild with a new session token.
  const [epoch, setEpoch] = useState(0);
  const [stalled, setStalled] = useState(false);
  const [playbackState, setPlaybackState] = useState("idle");
  const reconnectsRef = useRef(0);
  const backoffRef = useRef(RECONNECT_BASE_MS);

  // One stable id per player instance, so two tiles never share a gateway
  // session. It must NOT be recomputed on every render -- deriving it from
  // Date.now() in the render body would change `src` continuously and
  // rebuild the player on a loop.
  const instanceIdRef = useRef(null);
  if (instanceIdRef.current === null) {
    instanceIdRef.current = Math.random().toString(36).slice(2, 10);
  }
  const viewer = useMemo(() => `${instanceIdRef.current}-${epoch}`, [epoch]);
  const src = typeof makeSrc === "function" ? makeSrc(viewer) : makeSrc;

  const bumpEpoch = useCallback(() => {
    reconnectsRef.current += 1;
    setStalled(true);
    setPlaybackState("reconnecting");
    const delay = backoffRef.current;
    backoffRef.current = Math.min(backoffRef.current * 2, RECONNECT_MAX_MS);
    setTimeout(() => setEpoch((e) => e + 1), delay);
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!src || !video) {
      setPlaybackState("idle");
      return undefined;
    }

    // Native HLS (Safari) must opt into sending the same host-scoped auth
    // cookie when dev media is sharded from :5173 to :8000.
    video.crossOrigin = "use-credentials";

    let destroyed = false;
    setPlaybackState("connecting");

    if (Hls.isSupported()) {
      const hls = new Hls({
        // Dev media is deliberately sharded onto port 8000. The auth cookie
        // is host-scoped (not port-scoped), and credentialed XHR keeps the
        // HLS relay protected without giving the browser a raw stream URL.
        xhrSetup: (xhr) => {
          xhr.withCredentials = true;
        },
        // Low-latency mode off on purpose. The gateway publishes LL-HLS
        // parts with PART-TARGET~0.32s, and playback runs through the
        // backend's same-origin relay (hls_proxy.py, required because the
        // gateway's CORS header is malformed). That extra hop is enough
        // that a part is often already expired upstream when the proxy
        // asks for it. Full segments are ~10s and long-lived, so they
        // survive the relay -- at the cost of latency against footage
        // that is recorded and looped anyway.
        lowLatencyMode: false,
        maxBufferLength: 30,
        liveSyncDurationCount: 3,
        manifestLoadingMaxRetry: 2,
        manifestLoadingRetryDelay: 2000,
        fragLoadingMaxRetry: 3,
        fragLoadingRetryDelay: 1000,
      });

      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {});
      });

      hls.on(Hls.Events.FRAG_BUFFERED, () => {
        // Any successful fragment means this session is healthy again.
        backoffRef.current = RECONNECT_BASE_MS;
        setStalled(false);
        setPlaybackState("connected");
      });

      hls.on(Hls.Events.ERROR, (_evt, data) => {
        if (!data.fatal || destroyed) return;
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          hls.recoverMediaError();
          return;
        }
        // A dead upstream session surfaces as a network error (the proxy
        // turns an empty playlist into a 503 precisely so it is one).
        // Recover by rebuilding against a brand-new session, not by
        // retrying the dead one.
        bumpEpoch();
      });

      if (onHlsReady) onHlsReady(hls);

      // Watchdog for the silent case: no error fires, the buffer simply
      // stops advancing because the playlist stopped listing new segments.
      let lastTime = -1;
      let lastProgressAt = Date.now();
      const watchdog = setInterval(() => {
        if (video.paused || video.ended) return;
        if (video.currentTime !== lastTime) {
          lastTime = video.currentTime;
          lastProgressAt = Date.now();
          return;
        }
        if (Date.now() - lastProgressAt > STALL_TIMEOUT_MS) {
          clearInterval(watchdog);
          bumpEpoch();
        }
      }, STALL_POLL_MS);

      return () => {
        destroyed = true;
        clearInterval(watchdog);
        hls.destroy();
      };
    }

    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      video.play().catch(() => {});
      const onPlaying = () => {
        setStalled(false);
        setPlaybackState("connected");
      };
      const onError = () => bumpEpoch();
      video.addEventListener("playing", onPlaying);
      video.addEventListener("error", onError);
      return () => {
        video.removeEventListener("playing", onPlaying);
        video.removeEventListener("error", onError);
        video.removeAttribute("src");
        video.load();
      };
    }

    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, epoch]);

  return { reconnects: reconnectsRef.current, stalled, playbackState };
}
