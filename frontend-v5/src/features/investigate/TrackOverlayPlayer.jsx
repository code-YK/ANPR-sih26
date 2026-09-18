import { useEffect, useRef, useState } from "react";

import { Notice } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { recordingMediaUrl } from "../../lib/api/media.js";
import styles from "./Investigate.module.css";

const PAD_MS = 2_000;

/** Linear interpolation between fixed-rate samples; null outside the observed span. */
function boxAt(boxes, tMs) {
  const { t0_ms: t0, dt_ms: dt, b } = boxes;
  if (!b?.length) return null;
  const rel = (tMs - t0) / dt;
  if (rel < 0 || rel > b.length - 1) return null;
  const i = Math.min(Math.floor(rel), Math.max(0, b.length - 2));
  const frac = b.length > 1 ? rel - i : 0;
  const a = b[i];
  const c = b[Math.min(i + 1, b.length - 1)];
  return [0, 1, 2, 3].map((k) => a[k] + (c[k] - a[k]) * frac);
}

/**
 * A recorded file has exact frame timing, so -- unlike the live AI view -- a
 * frame-accurate box drawn over the real video is honest here. The clip is
 * virtual: playback seeks to the occurrence rather than cutting a file.
 */
export default function TrackOverlayPlayer({ recordingId, runId, trackRef, firstMs }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const boxesRef = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    boxesRef.current = null;
    setError(null);
    api(`/investigate/runs/${runId}/tracks/${trackRef}/boxes`)
      .then((data) => {
        if (!cancelled) boxesRef.current = data;
      })
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [runId, trackRef]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;
    const seek = () => {
      video.currentTime = Math.max(0, (firstMs - PAD_MS) / 1000);
      video.play().catch(() => {});
    };
    if (video.readyState >= 1) seek();
    video.addEventListener("loadedmetadata", seek);
    return () => video.removeEventListener("loadedmetadata", seek);
  }, [firstMs, recordingId, runId, trackRef]);

  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return undefined;
    const color = getComputedStyle(document.documentElement).getPropertyValue("--signal").trim() || "#6d8ff5";
    // Size from a ResizeObserver, not a layout read per frame, and draw only
    // when the video actually shows a new frame (or seeks) instead of on every
    // display refresh.
    let size = { width: 0, height: 0 };
    const observer = new ResizeObserver(([entry]) => {
      size = { width: Math.round(entry.contentRect.width), height: Math.round(entry.contentRect.height) };
      draw();
    });
    observer.observe(video);
    const ctx = canvas.getContext("2d");
    let frameHandle = 0;
    const draw = () => {
      const vw = video.videoWidth;
      const vh = video.videoHeight;
      if (canvas.width !== size.width) canvas.width = size.width;
      if (canvas.height !== size.height) canvas.height = size.height;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const boxes = boxesRef.current;
      if (boxes && vw && vh) {
        // Account for object-fit: contain letterboxing.
        const scale = Math.min(canvas.width / vw, canvas.height / vh);
        const offX = (canvas.width - vw * scale) / 2;
        const offY = (canvas.height - vh * scale) / 2;
        const box = boxAt(boxes, video.currentTime * 1000);
        if (box) {
          const [cx, cy, bw, bh] = box;
          const x = offX + ((cx - bw / 2) / 1000) * vw * scale;
          const y = offY + ((cy - bh / 2) / 1000) * vh * scale;
          ctx.strokeStyle = color;
          ctx.lineWidth = 2;
          ctx.strokeRect(x, y, (bw / 1000) * vw * scale, (bh / 1000) * vh * scale);
        }
      }
    };
    const supportsFrameCallback = "requestVideoFrameCallback" in HTMLVideoElement.prototype;
    const onFrame = () => {
      draw();
      frameHandle = video.requestVideoFrameCallback(onFrame);
    };
    let raf = 0;
    const onRaf = () => {
      draw();
      if (!video.paused) raf = requestAnimationFrame(onRaf);
    };
    const onPlay = () => {
      if (!supportsFrameCallback) raf = requestAnimationFrame(onRaf);
    };
    if (supportsFrameCallback) frameHandle = video.requestVideoFrameCallback(onFrame);
    video.addEventListener("seeked", draw);
    video.addEventListener("loadeddata", draw);
    video.addEventListener("play", onPlay);
    return () => {
      observer.disconnect();
      if (supportsFrameCallback) video.cancelVideoFrameCallback(frameHandle);
      cancelAnimationFrame(raf);
      video.removeEventListener("seeked", draw);
      video.removeEventListener("loadeddata", draw);
      video.removeEventListener("play", onPlay);
    };
  }, [recordingId, runId, trackRef]);

  return (
    <div className={styles.player}>
      {error && <Notice tone="critical">Couldn't load this track's boxes: {error}</Notice>}
      <div className={styles.playerFrame}>
        <video ref={videoRef} key={`${recordingId}:${runId}:${trackRef}`} src={recordingMediaUrl(recordingId)} controls playsInline />
        <canvas ref={canvasRef} aria-hidden="true" />
      </div>
    </div>
  );
}
