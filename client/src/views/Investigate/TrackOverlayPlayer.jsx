import { useEffect, useRef, useState } from "react";

import { api, recordingMediaUrl } from "../../api.js";

const PAD_MS = 2000;

// Linear interpolation between the fixed-rate samples in a TrackBoxesOut
// payload. Returns null outside the actually-observed span (the 2s pad
// before/after a clip should show no box, not a box frozen at the edge).
function boxAt(boxes, tMs) {
  const { t0_ms, dt_ms, b } = boxes;
  if (!b || b.length === 0) return null;
  const rel = (tMs - t0_ms) / dt_ms;
  if (rel < 0 || rel > b.length - 1) return null;
  const i = Math.min(Math.floor(rel), b.length - 2 >= 0 ? b.length - 2 : 0);
  const frac = b.length > 1 ? rel - i : 0;
  const a = b[i];
  const c = b[Math.min(i + 1, b.length - 1)];
  return [0, 1, 2, 3].map((k) => a[k] + (c[k] - a[k]) * frac);
}

// The app's first non-HLS video: a recorded file has exact frame timing, so
// (unlike the live detector view, which can only show a side-by-side
// annotated frame) a real frame-accurate overlay on the actual video is
// correct here. The clip is virtual -- seek to the track's start rather
// than cutting a file with ffmpeg, so switching between hits is instant and
// no extra storage is used. Playback itself is a normal video element from
// there on; it does not stop at the track's own end.
export default function TrackOverlayPlayer({ recordingId, runId, trackRef, firstMs, label }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const boxesRef = useRef(null);
  const rafRef = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    boxesRef.current = null;
    setError(null);
    api(`/investigate/runs/${runId}/tracks/${trackRef}/boxes`)
      .then((data) => {
        if (!cancelled) boxesRef.current = data;
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, trackRef]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;

    // Jump straight to where this occurrence starts -- that's the useful
    // part, and stays. Deliberately no longer auto-pausing at the
    // occurrence's end: that made playback stop with no visible reason a
    // couple of seconds in, which reads as broken rather than as "this
    // occurrence is over" -- an operator watching a hit through into
    // whatever happens next in the recording is normal video-player
    // behaviour, not something this view should fight.
    function onLoadedMetadata() {
      video.currentTime = Math.max(0, (firstMs - PAD_MS) / 1000);
    }
    video.addEventListener("loadedmetadata", onLoadedMetadata);
    return () => {
      video.removeEventListener("loadedmetadata", onLoadedMetadata);
    };
  }, [firstMs]);

  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return undefined;

    // A canvas 2D context can't consume a CSS custom property directly, so
    // it's read once from computed style rather than hardcoding a hex --
    // `--entity` is DESIGN.md's one colour for "a clickable identity", and
    // this box is exactly that: pointing at the specific tracked subject a
    // search matched, not a generic alert or a health indicator.
    const entityColor = getComputedStyle(document.documentElement).getPropertyValue("--entity").trim() || "#5b8def";

    function draw() {
      // Checked every frame rather than once at mount (previously) or via a
      // resize-event listener (also tried): this effect runs before the
      // video's metadata has loaded, so video.clientWidth/clientHeight are
      // still the browser's placeholder size for an unloaded <video>, not
      // the real, aspect-ratio-fitted size the max-width/max-height CSS
      // settles on once the source loads -- a one-shot sync locks the
      // canvas to that stale, usually-smaller size, so a box computed as a
      // fraction of it draws outside where the video has since grown to.
      // This keeps the two in lockstep unconditionally, independent of
      // catching the exact moment the video's layout settles.
      if (canvas.width !== video.clientWidth) canvas.width = video.clientWidth;
      if (canvas.height !== video.clientHeight) canvas.height = video.clientHeight;

      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const boxes = boxesRef.current;
      if (boxes && canvas.width > 0) {
        const box = boxAt(boxes, video.currentTime * 1000);
        if (box) {
          const [cx, cy, bw, bh] = box;
          const x = ((cx - bw / 2) / 1000) * canvas.width;
          const y = ((cy - bh / 2) / 1000) * canvas.height;
          const w = (bw / 1000) * canvas.width;
          const h = (bh / 1000) * canvas.height;
          ctx.strokeStyle = entityColor;
          ctx.lineWidth = 2;
          ctx.strokeRect(x, y, w, h);
        }
      }
      rafRef.current = requestAnimationFrame(draw);
    }

    rafRef.current = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(rafRef.current);
    };
  }, [recordingId, runId, trackRef]);

  return (
    <div className="track-overlay-player">
      {label && <h4>{label}</h4>}
      {error && <p className="hint">Could not load this track's timeline: {error}</p>}
      <div className="track-overlay-frame">
        <video
          ref={videoRef}
          key={`${recordingId}:${runId}:${trackRef}`}
          src={recordingMediaUrl(recordingId)}
          controls
          playsInline
        />
        <canvas ref={canvasRef} />
      </div>
    </div>
  );
}
