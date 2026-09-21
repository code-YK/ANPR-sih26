import { createContext, useCallback, useContext, useRef, useState } from "react";

import { api } from "../api.js";
import { useToast } from "../components/Toast.jsx";
import { usePolling } from "../hooks/usePolling.js";

const AlertsCtx = createContext(null);

const POLL_MS = 4000;

function beep() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.2, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.3);
  } catch (_) {
    // Audio blocked (autoplay policy) or unavailable -- toast + nav badge
    // still carry the alert, the beep is a nice-to-have on top.
  }
}

/**
 * Polls GET /api/alerts?status=open every 4s. Alerts require §5's
 * "automated real-time alerting" to actually surface without a manual API
 * call, so this lives above the router (in App.jsx) rather than inside the
 * Alerts view -- the nav badge and the toast/sound both need to fire no
 * matter which view is currently open.
 */
export function AlertsProvider({ children }) {
  const [openAlerts, setOpenAlerts] = useState([]);
  const [justArrivedIds, setJustArrivedIds] = useState(new Set());
  // This 4s poll is the app's real heartbeat, so the status strip reads its
  // timestamp rather than running a second timer just to prove liveness.
  // Only set on a *successful* poll: if the backend goes away, this stops
  // advancing and the strip's "polled Ns ago" climbs, which is exactly the
  // signal an operator needs.
  const [lastPolledAt, setLastPolledAt] = useState(null);
  const knownIds = useRef(new Set());
  const firstLoad = useRef(true);
  const showToast = useToast();

  const load = useCallback(async () => {
    let alerts;
    try {
      alerts = await api("/alerts?status=open");
    } catch (_) {
      return; // a failed poll just tries again next tick
    }
    setLastPolledAt(Date.now());

    const newIds = alerts.filter((a) => !knownIds.current.has(a.id)).map((a) => a.id);

    if (!firstLoad.current && newIds.length > 0) {
      setJustArrivedIds(new Set(newIds));
      const first = alerts.find((a) => a.id === newIds[0]);
      // A watchlist alert names its plate; a suspicious-activity alert has
      // none, so fall back to its label ("Potentially dangerous person").
      const subject = first.plate ?? first.label ?? "alert";
      showToast(
        newIds.length === 1
          ? `Alert: ${subject} on camera ${first.camera_id}`
          : `${newIds.length} new alerts, most recent: ${subject} on camera ${first.camera_id}`
      );
      beep();
    }
    firstLoad.current = false;
    alerts.forEach((a) => knownIds.current.add(a.id));
    setOpenAlerts(alerts);
  }, [showToast]);

  usePolling(load, POLL_MS);

  return (
    <AlertsCtx.Provider value={{ openAlerts, justArrivedIds, lastPolledAt, refresh: load }}>
      {children}
    </AlertsCtx.Provider>
  );
}

export function useAlerts() {
  const ctx = useContext(AlertsCtx);
  if (!ctx) throw new Error("useAlerts must be used within an AlertsProvider");
  return ctx;
}
