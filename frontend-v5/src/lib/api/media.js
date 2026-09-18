import { API } from "./client.js";

/**
 * Media URLs.
 *
 * In development, media (HLS segments, the MJPEG AI stream, evidence and
 * thumbnails) is fetched straight from the backend's own origin rather than
 * through the Vite proxy. Browsers allow ~6 HTTP/1.1 connections per origin;
 * a wall of HLS players plus a long-lived MJPEG stream on the app's origin
 * would starve API polls. localhost:5175 and localhost:8000 are separate
 * origins (separate pools) but the same site, so the session cookie still
 * rides along. In a production build FastAPI serves the app itself and these
 * collapse to same-origin relative URLs.
 */
export const MEDIA_ORIGIN = import.meta.env.DEV
  ? `${window.location.protocol}//${window.location.hostname}:8000`
  : "";

export function hlsUrl(cameraId, viewer) {
  return `${MEDIA_ORIGIN}${API}/hls/${encodeURIComponent(cameraId)}/${viewer}/index.m3u8`;
}

export function whepUrl(cameraId) {
  return `${API}/webrtc/${encodeURIComponent(cameraId)}/whep`;
}

/** `key` forces a fresh connection (new worker run, or a retry). */
export function mjpegUrl(cameraId, backendMode, key) {
  return `${MEDIA_ORIGIN}${API}/analytics/stream/${encodeURIComponent(cameraId)}?mode=${backendMode}&k=${encodeURIComponent(key)}`;
}

export function evidenceUrl(sightingId) {
  return `${MEDIA_ORIGIN}${API}/sightings/${sightingId}/evidence`;
}

export function trackThumbUrl(runId, trackRef) {
  return `${MEDIA_ORIGIN}${API}/investigate/runs/${runId}/tracks/${trackRef}/thumb`;
}

export function recordingMediaUrl(recordingId) {
  return `${MEDIA_ORIGIN}${API}/investigate/recordings/${recordingId}/media`;
}

/** Same-origin download/report URL (goes through the proxy in dev). */
export function apiUrl(path) {
  return `${API}${path}`;
}
