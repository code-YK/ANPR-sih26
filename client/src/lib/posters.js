import { useEffect } from "react";

/**
 * Last-frame stills, captured from feeds that are already playing, so a tile
 * that is not holding a live connection can still show its camera.
 *
 * This is what lets the focused view's filmstrip run without live players.
 * With every strip tile playing, the focused camera shared the media origin's
 * ~6 connections with four other HLS players, and the detector's own MJPEG
 * stream queued behind their segment fetches -- 2-4s to a first frame on a
 * worker that was publishing 25 a second. A still costs nothing to show. The
 * same idea as frontend-v5's posters.js.
 *
 * In memory only, per camera, and bounded by the number of cameras. Encoding
 * uses canvas.toBlob, which compresses off the main thread; a synchronous
 * toDataURL blocks rendering for tens of milliseconds per tile, and a wall of
 * tiles capturing on the same beat is a visible hitch.
 */
const posters = new Map();
const MAX_WIDTH = 480;
let busy = false;

/**
 * Returns false when the capture was skipped only because another tile was
 * mid-encode, so the caller can try again shortly rather than waiting out its
 * full interval with no still at all.
 */
export function capturePoster(video, cameraId) {
  if (busy) return false;
  if (!video || !cameraId || video.readyState < 2 || !video.videoWidth) return true;
  if (document.visibilityState !== "visible") return true;
  try {
    const scale = Math.min(1, MAX_WIDTH / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d", { alpha: false }).drawImage(video, 0, 0, canvas.width, canvas.height);
    busy = true;
    canvas.toBlob(
      (blob) => {
        busy = false;
        if (!blob) return;
        const previous = posters.get(cameraId);
        posters.set(cameraId, { url: URL.createObjectURL(blob), at: Date.now() });
        // Let any <img> still showing the old still finish before revoking it.
        if (previous) setTimeout(() => URL.revokeObjectURL(previous.url), 30_000);
      },
      "image/jpeg",
      0.7,
    );
  } catch {
    // A tainted or not-yet-decodable frame: keep the previous still.
    busy = false;
  }
  return true;
}

export function getPoster(cameraId) {
  return posters.get(cameraId) ?? null;
}

/**
 * Keep a camera's still fresh while its video is playing. Jittered, so a wall
 * of tiles that started together never captures on the same frame.
 */
export function usePosterCapture(videoRef, cameraId, playing) {
  useEffect(() => {
    if (!playing) return undefined;
    let retry = null;
    const capture = () => {
      clearTimeout(retry);
      // Measured on a wall of nine: two of eight tiles had no still after ten
      // seconds because their first capture landed while another was encoding.
      if (!capturePoster(videoRef.current, cameraId)) retry = setTimeout(capture, 400 + Math.random() * 600);
    };
    const first = setTimeout(capture, 1_500 + Math.random() * 2_000);
    const id = setInterval(capture, 20_000 + Math.random() * 5_000);
    return () => {
      clearTimeout(first);
      clearTimeout(retry);
      clearInterval(id);
    };
  }, [videoRef, cameraId, playing]);
}
