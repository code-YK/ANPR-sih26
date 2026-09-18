/**
 * Last-frame posters, captured from a playing feed. Shown while a focused
 * feed connects (so opening a camera never flashes black) and on filmstrip
 * tiles that aren't holding a live connection. In-memory only.
 *
 * Encoding uses canvas.toBlob, which compresses off the main thread; the
 * earlier synchronous toDataURL blocked rendering for tens of milliseconds
 * per tile, and a wall of tiles captured on the same beat produced a visible
 * hitch every few seconds.
 */
const posters = new Map();
const MAX_WIDTH = 480;
let busy = false;

export function capturePoster(video, cameraId) {
  if (busy || !video || !cameraId || video.readyState < 2 || !video.videoWidth) return;
  if (document.visibilityState !== "visible") return;
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
        // Let any <img> still showing the old poster finish before revoking it.
        if (previous) setTimeout(() => URL.revokeObjectURL(previous.url), 30_000);
      },
      "image/jpeg",
      0.7,
    );
  } catch {
    busy = false; // a tainted or not-yet-decodable frame: keep the previous poster
  }
}

export function getPoster(cameraId) {
  return posters.get(cameraId)?.url ?? null;
}
