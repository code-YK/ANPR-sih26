import { createContext, useCallback, useContext, useRef, useState } from "react";

import { api, evidenceUrl } from "../api.js";
import { notify } from "../lib/notifications.js";
import { usePolling } from "../hooks/usePolling.js";

const AlertsCtx = createContext(null);

const POLL_MS = 4000;

/** Same alerts, in the same order, with the same status -- nothing to re-render. */
function sameAlerts(a, b) {
  if (a.length !== b.length) return false;
  return a.every((alert, index) => alert.id === b[index].id && alert.status === b[index].status);
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
      // One card per alert, oldest first so the newest lands nearest the
      // corner; the stack keeps three and counts the rest, and the sound is
      // rate-limited, so a burst stays readable. Whatever was open before this
      // session's first poll counts as already seen.
      const fresh = alerts.filter((a) => newIds.includes(a.id)).reverse();
      for (const alert of fresh) {
        const suspicious = alert.alert_type === "suspicious";
        notify({
          kind: suspicious ? "suspicious" : "watchlist",
          key: `alert:${alert.id}`,
          replaces: alert.sighting_id != null ? `sighting:${alert.sighting_id}` : undefined,
          cameraId: alert.camera_id,
          cameraName: alert.camera_name ?? alert.camera_id,
          // A suspicious-activity alert has no plate; what it says is in label.
          plate: suspicious ? undefined : alert.plate,
          title: suspicious ? alert.label ?? "Potentially dangerous person" : "Watchlist match",
          detail: suspicious
            ? `Severity ${alert.severity ?? "high"}${alert.match_confidence != null ? ` · ${alert.match_confidence.toFixed(2)}` : ""}`
            : [alert.reason_code && alert.reason_code.replace(/_/g, " "), alert.severity && `${alert.severity} severity`]
                .filter(Boolean)
                .join(" · "),
          time: alert.event_time,
          image: alert.has_evidence && alert.sighting_id != null ? evidenceUrl(alert.sighting_id) : null,
          href: `/live/${encodeURIComponent(alert.camera_id)}?ai=${suspicious ? "suspicious" : "anpr"}`,
        });
      }
    }
    firstLoad.current = false;
    alerts.forEach((a) => knownIds.current.add(a.id));
    // Replace the array only when the queue actually changed. Setting a fresh
    // array every tick re-rendered every consumer of this context -- the status
    // strip, the nav badge, the alerts table -- four times a minute while
    // nothing had happened, which is a real cost on a view already carrying
    // live video.
    setOpenAlerts((prev) => (sameAlerts(prev, alerts) ? prev : alerts));
  }, []);

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
