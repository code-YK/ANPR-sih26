import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";

import { api } from "../../api.js";
import { useAlerts } from "../../context/AlertsContext.jsx";
import { canAccessDepartment, useAuth } from "../../context/AuthContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";

function fmtTime(iso) {
  return new Date(iso).toLocaleString();
}

function severityBadge(sev) {
  if (!sev) return <span className="badge badge-muted">—</span>;
  const cls = sev === "high" ? "badge-bad" : sev === "medium" ? "badge-warn" : "badge-muted";
  return <span className={`badge ${cls}`}>{sev}</span>;
}

// The identity cell. A watchlist (ANPR) alert shows its plate, linked to the
// vehicle journey. A suspicious-activity alert has no plate or journey -- it
// shows its label instead (e.g. "Potentially dangerous person").
function subjectCell(alert) {
  if (alert.plate) {
    return <Link to={`/journey/${alert.plate}`}>{alert.plate}</Link>;
  }
  return alert.label ?? "—";
}

function statusBadge(status) {
  const cls = status === "open" ? "badge-bad" : status === "acknowledged" ? "badge-warn" : "badge-ok";
  return <span className={`badge ${cls}`}>{status}</span>;
}

function subNavClass({ isActive }) {
  return isActive ? "nav-btn active" : "nav-btn";
}

function AlertsTable({ status }) {
  const { user } = useAuth();
  const { openAlerts, justArrivedIds, refresh } = useAlerts();
  const [cameraId, setCameraId] = useState("");
  const [otherAlerts, setOtherAlerts] = useState([]);
  const [busyId, setBusyId] = useState(null);

  // "open" is already polled by AlertsContext every 4s -- reuse it instead
  // of running a second poller for the same data. Any other status filter
  // gets its own one-off fetch.
  useEffect(() => {
    if (status === "open") return undefined;
    let cancelled = false;
    (async () => {
      const params = new URLSearchParams({ status });
      if (cameraId) params.set("camera_id", cameraId);
      const data = await api(`/alerts?${params.toString()}`);
      if (!cancelled) setOtherAlerts(data);
    })();
    return () => {
      cancelled = true;
    };
  }, [status, cameraId]);

  const rows = useMemo(() => {
    if (status === "open") {
      return cameraId ? openAlerts.filter((a) => a.camera_id === cameraId) : openAlerts;
    }
    return otherAlerts;
  }, [status, cameraId, openAlerts, otherAlerts]);

  async function act(alertId, action) {
    setBusyId(alertId);
    try {
      await api(`/alerts/${alertId}/${action}`, { method: "POST" });
      await refresh();
      if (status !== "open") {
        const params = new URLSearchParams({ status });
        if (cameraId) params.set("camera_id", cameraId);
        setOtherAlerts(await api(`/alerts?${params.toString()}`));
      }
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <div className="toolbar">
        <input
          placeholder="Filter by camera id"
          value={cameraId}
          onChange={(e) => setCameraId(e.target.value)}
          style={{ maxWidth: 180 }}
        />
      </div>

      {rows.length === 0 ? (
        <p className="hint">
          {status === "open"
            ? "No open alerts. Start analytics on a camera to begin monitoring."
            : `No ${status} alerts.`}
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Plate / Subject</th>
              <th>Camera</th>
              <th>Location</th>
              <th>Reason</th>
              <th>Severity</th>
              <th>Confidence</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id} className={justArrivedIds.has(a.id) ? "row-flash" : ""}>
                <td>{fmtTime(a.event_time)}</td>
                <td>{subjectCell(a)}</td>
                <td>{a.camera_name}</td>
                <td>{a.location_text}</td>
                <td>{a.reason_code ?? "—"}</td>
                <td>{severityBadge(a.severity)}</td>
                <td>{a.match_confidence != null ? a.match_confidence.toFixed(2) : "—"}</td>
                <td>{statusBadge(a.status)}</td>
                <td>
                  {canAccessDepartment(user, a.department, "operator") && a.status === "open" && (
                    <>
                      <button className="link-btn" disabled={busyId === a.id} onClick={() => act(a.id, "acknowledge")}>
                        Acknowledge
                      </button>{" "}
                      <button className="link-btn" disabled={busyId === a.id} onClick={() => act(a.id, "resolve")}>
                        Resolve
                      </button>
                    </>
                  )}
                  {canAccessDepartment(user, a.department, "operator") && a.status === "acknowledged" && (
                    <button className="link-btn" disabled={busyId === a.id} onClick={() => act(a.id, "resolve")}>
                      Resolve
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

export default function AlertsView() {
  usePageTitle("Alerts");
  return (
    <section className="view active">
      <nav className="toolbar" style={{ marginBottom: 16 }}>
        <NavLink to="/alerts" end className={subNavClass}>
          Open
        </NavLink>
        <NavLink to="/alerts/acknowledged" className={subNavClass}>
          Acknowledged
        </NavLink>
        <NavLink to="/alerts/resolved" className={subNavClass}>
          Resolved
        </NavLink>
      </nav>
      <Routes>
        <Route index element={<AlertsTable status="open" />} />
        <Route path="acknowledged" element={<AlertsTable status="acknowledged" />} />
        <Route path="resolved" element={<AlertsTable status="resolved" />} />
      </Routes>
    </section>
  );
}
