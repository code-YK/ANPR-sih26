import { useEffect, useState } from "react";

import { webrtcWhepUrl } from "../api.js";

// MediaMTX's WHEP implementation expects a complete (non-trickle) offer --
// all ICE candidates gathered before the SDP is sent. Gathering normally
// finishes in well under a second on a loopback relay; the timeout is a
// last resort so a stalled ICE gatherer can never hang the negotiation
// forever.
const ICE_GATHERING_TIMEOUT_MS = 3000;

// A loopback ICE connection can flap to "disconnected" transiently (a
// consent-check miss, briefly) and recover on its own -- falling back to
// HLS on the very first blip would defeat the point of trying WebRTC at
// all. "failed" is unambiguous and never given this grace period.
const ICE_DISCONNECT_GRACE_MS = 4000;

function waitForIceGathering(pc) {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const check = () => {
      if (pc.iceGatheringState === "complete") {
        pc.removeEventListener("icegatheringstatechange", check);
        clearTimeout(timer);
        resolve();
      }
    };
    const timer = setTimeout(() => {
      pc.removeEventListener("icegatheringstatechange", check);
      resolve();
    }, ICE_GATHERING_TIMEOUT_MS);
    pc.addEventListener("icegatheringstatechange", check);
  });
}

/**
 * Negotiates a WHEP session against the backend's WebRTC relay proxy
 * (see backend/app/routers/webrtc.py) and attaches the resulting stream to
 * `videoRef`. This is a one-shot attempt, not a reconnecting player like
 * useHlsPlayer: WebRTC here is genuinely a "try the low-latency path once,
 * fall back to HLS" transport, not the primary path with its own retry
 * logic -- a relay that fails to start (source unreachable, mediamtx not
 * installed on this machine) is exactly what HLS already handles.
 *
 * Returns { failed } -- once true, the caller should mount useHlsPlayer
 * instead for this camera.
 */
export function useWebRtcPlayer(camera, videoRef) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!camera?.webrtc_preview_available || !video) return undefined;

    setFailed(false);
    let cancelled = false;
    let pc = null;
    let resourceUrl = null;
    let disconnectTimer = null;

    async function negotiate() {
      pc = new RTCPeerConnection();
      pc.addTransceiver("video", { direction: "recvonly" });
      pc.ontrack = (event) => {
        video.srcObject = event.streams[0];
      };
      // Negotiation succeeding (getting an SDP answer) is not the same as
      // the media actually connecting -- ICE can still fail or drop after
      // the fact, and that has no other signal in this hook's control flow.
      pc.onconnectionstatechange = () => {
        if (cancelled) return;
        if (pc.connectionState === "connected") {
          if (disconnectTimer) {
            clearTimeout(disconnectTimer);
            disconnectTimer = null;
          }
          return;
        }
        if (pc.connectionState === "failed") {
          setFailed(true);
          return;
        }
        if (pc.connectionState === "disconnected" && !disconnectTimer) {
          disconnectTimer = setTimeout(() => {
            if (!cancelled && pc.connectionState !== "connected") setFailed(true);
          }, ICE_DISCONNECT_GRACE_MS);
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitForIceGathering(pc);
      if (cancelled) return;

      const resp = await fetch(webrtcWhepUrl(camera), {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/sdp" },
        body: pc.localDescription.sdp,
      });
      if (!resp.ok) throw new Error(`WHEP offer rejected: ${resp.status}`);

      resourceUrl = resp.headers.get("Location");
      const answerSdp = await resp.text();
      if (cancelled) return;
      await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
    }

    negotiate().catch(() => {
      if (!cancelled) setFailed(true);
    });

    return () => {
      cancelled = true;
      if (disconnectTimer) clearTimeout(disconnectTimer);
      if (resourceUrl) {
        fetch(resourceUrl, { method: "DELETE", credentials: "same-origin" }).catch(() => {});
      }
      pc?.close();
      video.srcObject = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera?.camera_id, camera?.webrtc_preview_available]);

  return { failed };
}
