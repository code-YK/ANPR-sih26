import { useEffect, useState } from "react";

import { api } from "../api.js";
import { useAlerts } from "../context/AlertsContext.jsx";
import { isSuperAdmin, useAuth } from "../context/AuthContext.jsx";
import { useCameras } from "../context/CamerasContext.jsx";
import { usePolling } from "../hooks/usePolling.js";

const WORKER_POLL_MS = 5000;

// Recomputed on a timer rather than derived at render: nothing else
// re-renders this component between polls, so without its own tick the age
// would sit frozen at "0s" and read as healthy while the backend was gone.
function useSecondsSince(timestamp) {
  const [, force] = useState(0);
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  if (timestamp == null) return null;
  return Math.max(0, Math.round((Date.now() - timestamp) / 1000));
}

/**
 * What's true regardless of which view is open (DESIGN.md §6.1): estate
 * health, worker activity, outstanding alerts, the operator's own scope,
 * and proof the console is still talking to the backend.
 *
 * Every figure here is one the API actually reports. Notably absent: a
 * "queued workers" count and a worker cap denominator -- the analytics
 * caps are server-side config and `/analytics/status` returns only started
 * workers with `queue_position` hardcoded to None, so both would be
 * invented. A console whose job is making the limits of its own knowledge
 * legible cannot open by displaying a number it made up.
 */
export default function StatusStrip() {
  const { cameras } = useCameras();
  const { openAlerts, lastPolledAt } = useAlerts();
  const { user } = useAuth();
  const [workers, setWorkers] = useState(null);

  usePolling(async () => {
    try {
      const rows = await api("/analytics/status");
      setWorkers(rows.filter((row) => row.running).length);
    } catch (_) {
      setWorkers(null); // unknown, not zero -- see the em-rule below
    }
  }, WORKER_POLL_MS);

  const age = useSecondsSince(lastPolledAt);
  const live = cameras.filter((camera) => camera.is_live === true).length;
  const scope = isSuperAdmin(user)
    ? "all departments"
    : `${user.grants?.length ?? 0} dept${user.grants?.length === 1 ? "" : "s"}`;

  // A poll that hasn't come back for several cycles is a real condition an
  // operator should see, not something to hide behind a stale number.
  const stale = age != null && age > 15;

  return (
    <footer className="status-strip">
      {/* Each figure names what it counts. "3 open" read as a bare number
          with no subject -- open what? -- which is exactly the ambiguity a
          strip meant to be self-documenting on a recording cannot afford. */}
      <span className="status-item">
        <b>{live}</b>/{cameras.length} cameras live
      </span>
      <span className="status-sep" aria-hidden="true">·</span>
      <span className="status-item">
        {workers == null ? <span className="status-unknown">—</span> : <b>{workers}</b>} workers running
      </span>
      <span className="status-sep" aria-hidden="true">·</span>
      <span className={`status-item${openAlerts.length > 0 ? " status-item-alert" : ""}`}>
        <b>{openAlerts.length}</b> open alerts
      </span>
      <span className="status-sep" aria-hidden="true">·</span>
      <span className="status-item">{scope}</span>
      <span className="status-spacer" />
      <span className={`status-item status-poll${stale ? " status-poll-stale" : ""}`}>
        {age == null ? "connecting…" : stale ? `no response for ${age}s` : `polled ${age}s ago`}
      </span>
    </footer>
  );
}
