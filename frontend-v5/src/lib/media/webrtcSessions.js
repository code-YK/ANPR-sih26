import { whepUrl } from "../api/media.js";

/**
 * One WHEP/WebRTC session per camera, shared and reference-counted.
 *
 * The focused raw feed changes layout (plain view -> inference sheet ->
 * side-by-side) and React may remount its <video>. Renegotiating on every
 * mount would black the feed out for up to a keyframe interval each time, so
 * the negotiated MediaStream lives here and simply re-attaches. A released
 * session lingers briefly before closing so a remount picks it straight up.
 *
 * Media flows browser <-> local MediaMTX over loopback UDP; only signaling
 * goes through the backend (see backend/app/routers/webrtc.py).
 */

const ICE_GATHERING_TIMEOUT_MS = 3_000;
const DISCONNECT_GRACE_MS = 4_000;
const RELEASE_LINGER_MS = 8_000;

const sessions = new Map();

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

function emit(session) {
  for (const listener of session.listeners) listener(session);
}

function setState(session, state, error = null) {
  if (session.state === "closed") return;
  session.state = state;
  session.error = error;
  emit(session);
}

async function negotiate(session) {
  const pc = new RTCPeerConnection({ bundlePolicy: "max-bundle" });
  session.pc = pc;
  const transceiver = pc.addTransceiver("video", { direction: "recvonly" });
  // Nothing here needs smoothing buffers beyond what the browser requires.
  if ("jitterBufferTarget" in transceiver.receiver) {
    try {
      transceiver.receiver.jitterBufferTarget = 0;
    } catch {
      // not supported
    }
  }

  pc.ontrack = (event) => {
    session.stream = event.streams[0] ?? new MediaStream([event.track]);
    emit(session);
  };

  pc.onconnectionstatechange = () => {
    if (session.state === "closed") return;
    const state = pc.connectionState;
    if (state === "connected") {
      clearTimeout(session.disconnectTimer);
      session.disconnectTimer = null;
      if (session.state !== "live") setState(session, "connected");
      return;
    }
    if (state === "failed") {
      setState(session, "failed", "The WebRTC connection failed");
      return;
    }
    if (state === "disconnected" && !session.disconnectTimer) {
      session.disconnectTimer = setTimeout(() => {
        if (pc.connectionState !== "connected") setState(session, "failed", "The WebRTC connection dropped");
      }, DISCONNECT_GRACE_MS);
    }
  };

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await waitForIceGathering(pc);
  if (session.state === "closed") return;

  const resp = await fetch(whepUrl(session.cameraId), {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/sdp" },
    body: pc.localDescription.sdp,
  });
  if (!resp.ok) {
    let detail = `relay rejected the offer (${resp.status})`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // not JSON
    }
    throw new Error(detail);
  }
  session.resourceUrl = resp.headers.get("Location");
  const answer = await resp.text();
  if (session.state === "closed") return;
  await pc.setRemoteDescription({ type: "answer", sdp: answer });
}

function close(session) {
  if (session.state === "closed") return;
  session.state = "closed";
  clearTimeout(session.disconnectTimer);
  clearTimeout(session.releaseTimer);
  if (session.resourceUrl) {
    fetch(session.resourceUrl, { method: "DELETE", credentials: "same-origin" }).catch(() => {});
  }
  try {
    session.pc?.close();
  } catch {
    // already closed
  }
  sessions.delete(session.cameraId);
  emit(session);
}

/** Acquire the camera's session, negotiating if needed. Pair with release(). */
export function acquireWebRtc(cameraId) {
  let session = sessions.get(cameraId);
  if (session && session.state === "failed") {
    close(session);
    session = null;
  }
  if (!session) {
    session = {
      cameraId,
      state: "connecting",
      error: null,
      stream: null,
      pc: null,
      resourceUrl: null,
      refs: 0,
      listeners: new Set(),
      disconnectTimer: null,
      releaseTimer: null,
      firstFrameAt: null,
    };
    sessions.set(cameraId, session);
    const current = session;
    negotiate(current).catch((error) => setState(current, "failed", error.message));
  }
  clearTimeout(session.releaseTimer);
  session.releaseTimer = null;
  session.refs += 1;
  return session;
}

export function releaseWebRtc(session) {
  if (!session || session.state === "closed") return;
  session.refs = Math.max(0, session.refs - 1);
  if (session.refs === 0 && !session.releaseTimer) {
    session.releaseTimer = setTimeout(() => {
      if (session.refs === 0) close(session);
    }, session.state === "failed" ? 0 : RELEASE_LINGER_MS);
  }
}

export function subscribeWebRtc(session, listener) {
  session.listeners.add(listener);
  return () => session.listeners.delete(listener);
}

/** A connection that negotiates but never decodes a frame is still a failure. */
export function markWebRtcFailed(session, reason) {
  if (session && session.state !== "closed") setState(session, "failed", reason);
}

export function markWebRtcLive(session) {
  if (session && session.state !== "closed" && session.state !== "live") {
    session.firstFrameAt = Date.now();
    setState(session, "live");
  }
}

/**
 * Decoder health for the session's video track: frames decoded so far,
 * cumulative freeze time (seconds) and the receiver's average buffer delay.
 * Null when stats are unavailable.
 */
export async function webrtcHealth(session) {
  if (!session?.pc) return null;
  try {
    const stats = await session.pc.getStats();
    for (const report of stats.values()) {
      if (report.type === "inbound-rtp" && report.kind === "video") {
        return {
          framesDecoded: report.framesDecoded ?? 0,
          totalFreezesDuration: report.totalFreezesDuration ?? null,
          bufferMs: report.jitterBufferEmittedCount > 0 ? (report.jitterBufferDelay / report.jitterBufferEmittedCount) * 1000 : null,
        };
      }
    }
  } catch {
    // stats unavailable
  }
  return null;
}

// Cameras whose WebRTC feed stalled or kept freezing in this browser session.
const UNSUITABLE_KEY = "sentinel.webrtc.unsuitable";

function readUnsuitable() {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(UNSUITABLE_KEY) ?? "[]"));
  } catch {
    return new Set();
  }
}

export function isWebRtcUnsuitable(cameraId) {
  return readUnsuitable().has(cameraId);
}

export function rememberWebRtcUnsuitable(cameraId) {
  try {
    const set = readUnsuitable();
    set.add(cameraId);
    sessionStorage.setItem(UNSUITABLE_KEY, JSON.stringify([...set]));
  } catch {
    // storage unavailable: the check simply runs again next time
  }
}
