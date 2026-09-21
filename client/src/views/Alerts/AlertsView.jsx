import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { Search, Shield, UserRound } from "lucide-react";

import { api } from "../../api.js";
import { useAlerts } from "../../context/AlertsContext.jsx";
import { canAccessDepartment, useAuth } from "../../context/AuthContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import { plateGroups } from "../../lib/plate.js";

function fmtTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return "—";
  }
}

function subjectTitle(alert) {
  if (alert.plate) return alert.plate;
  return alert.label ?? "Unlabelled event";
}

function isWatchlistAlert(a) {
  return Boolean(a.plate) || a.kind === "watchlist" || a.alert_type === "watchlist";
}

function isSuspiciousAlert(a) {
  return !isWatchlistAlert(a);
}

function AlertsBoard({ status }) {
  const { user } = useAuth();
  const { openAlerts, justArrivedIds, refresh } = useAlerts();
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState("all"); // all | watchlist | suspicious
  const [otherAlerts, setOtherAlerts] = useState([]);
  const [busyId, setBusyId] = useState(null);

  useEffect(() => {
    if (status === "open") return undefined;
    let cancelled = false;
    (async () => {
      try {
        const params = new URLSearchParams({ status });
        const data = await api(`/alerts?${params.toString()}`);
        if (!cancelled) setOtherAlerts(data);
      } catch {
        if (!cancelled) setOtherAlerts([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status]);

  const baseRows = useMemo(() => {
    if (status === "open") return openAlerts ?? [];
    return otherAlerts;
  }, [status, openAlerts, otherAlerts]);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return baseRows.filter((a) => {
      if (kindFilter === "watchlist" && !isWatchlistAlert(a)) return false;
      if (kindFilter === "suspicious" && !isSuspiciousAlert(a)) return false;
      if (!needle) return true;
      const hay = [
        a.plate,
        a.label,
        a.camera_name,
        a.camera_id,
        a.location_text,
        a.reason_code,
        a.reason,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(needle);
    });
  }, [baseRows, query, kindFilter]);

  async function act(alertId, action) {
    setBusyId(alertId);
    try {
      await api(`/alerts/${alertId}/${action}`, { method: "POST" });
      await refresh();
      if (status !== "open") {
        const params = new URLSearchParams({ status });
        setOtherAlerts(await api(`/alerts?${params.toString()}`));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="alerts-board">
      <div className="alerts-board-bar">
        <label className="alerts-search">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Plate, camera or reason"
            aria-label="Search alerts"
          />
          <Search size={15} strokeWidth={2} aria-hidden="true" />
        </label>

        <div className="alerts-kind-pills" role="group" aria-label="Alert type">
          <button
            type="button"
            className={kindFilter === "all" ? "alerts-kind-pill is-active" : "alerts-kind-pill"}
            onClick={() => setKindFilter("all")}
          >
            All
          </button>
          <button
            type="button"
            className={kindFilter === "watchlist" ? "alerts-kind-pill is-active" : "alerts-kind-pill"}
            onClick={() => setKindFilter("watchlist")}
          >
            Watchlist
          </button>
          <button
            type="button"
            className={kindFilter === "suspicious" ? "alerts-kind-pill is-active" : "alerts-kind-pill"}
            onClick={() => setKindFilter("suspicious")}
          >
            Suspicious
          </button>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="alerts-void">
          <h2>{status === "open" ? "Queue is clear" : `No ${status} alerts`}</h2>
          <p>
            {status === "open"
              ? "New watchlist hits and detector events will land here for the duty desk."
              : `Nothing in the ${status} state for the current filter.`}
          </p>
        </div>
      ) : (
        <div className="alerts-table-wrap">
          <table className="alerts-table">
            <thead>
              <tr>
                <th>Subject</th>
                <th>Camera</th>
                <th>Reason</th>
                <th>Severity</th>
                <th>Confidence</th>
                <th>Time</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => {
                const isNew = justArrivedIds?.has?.(a.id);
                const sev = a.severity || "low";
                const watchlist = isWatchlistAlert(a);
                const conf =
                  a.match_confidence != null
                    ? Number(a.match_confidence).toFixed(2)
                    : a.confidence != null
                      ? Number(a.confidence).toFixed(2)
                      : "—";
                const reason = a.reason_code || a.reason || "—";
                const canAct =
                  canAccessDepartment(user, a.department, "operator") &&
                  (a.status === "open" || a.status === "acknowledged");

                return (
                  <tr key={a.id} className={`alerts-row sev-${sev}${isNew ? " is-new" : ""}`}>
                    <td className="alerts-td-subject">
                      <div className="alerts-subject-cell">
                        <span className={`alerts-subject-icon ${watchlist ? "is-watchlist" : "is-person"}`}>
                          {watchlist ? <Shield size={14} strokeWidth={2} /> : <UserRound size={14} strokeWidth={2} />}
                        </span>
                        {a.plate ? (
                          <Link
                            to={`/journey/${a.plate}`}
                            className={
                              String(a.plate).endsWith("?")
                                ? "alerts-plate-chip alerts-plate-chip--tentative"
                                : "alerts-plate-chip"
                            }
                            title={String(a.plate).endsWith("?") ? "Tentative read — not confirmed" : a.plate}
                            aria-label={`Plate ${String(a.plate).replace("?", "")}${String(a.plate).endsWith("?") ? ", tentative" : ""}`}
                          >
                            <span className="alerts-plate-chip-stripe" aria-hidden="true">
                              IND
                            </span>
                            <span className="alerts-plate-chip-text" aria-hidden="true">
                              {plateGroups(a.plate).map((group, index) => (
                                <span key={index}>{group}</span>
                              ))}
                            </span>
                          </Link>
                        ) : (
                          <span className="alerts-subject-name">{subjectTitle(a)}</span>
                        )}
                      </div>
                    </td>
                    <td className="alerts-td-camera">
                      <strong>{a.camera_name || a.camera_id || "—"}</strong>
                      {a.location_text ? <span>{a.location_text}</span> : null}
                    </td>
                    <td className="alerts-td-reason">{reason}</td>
                    <td>
                      <span className={`alerts-sev-pill sev-${sev}`}>{sev}</span>
                    </td>
                    <td className="alerts-td-conf mono">{conf}</td>
                    <td className="alerts-td-time">{fmtTime(a.event_time)}</td>
                    <td>
                      <span className={`alerts-status-pill status-${a.status}`}>{a.status}</span>
                    </td>
                    <td className="alerts-td-actions">
                      {canAct && (
                        <>
                          {a.status === "open" && (
                            <button
                              type="button"
                              className="alerts-action-btn"
                              disabled={busyId === a.id}
                              onClick={() => act(a.id, "acknowledge")}
                            >
                              Acknowledge
                            </button>
                          )}
                          <button
                            type="button"
                            className="alerts-action-btn primary"
                            disabled={busyId === a.id}
                            onClick={() => act(a.id, "resolve")}
                          >
                            Resolve
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function AlertsView() {
  usePageTitle("Alerts");
  const { openAlerts } = useAlerts();
  const location = useLocation();
  const openCount = openAlerts?.length ?? 0;

  const tab = location.pathname.includes("acknowledged")
    ? "acknowledged"
    : location.pathname.includes("resolved")
      ? "resolved"
      : "open";

  return (
    <section className="alerts-shell">
      <header className="alerts-shell-top">
        <div>
          <p className="alerts-shell-eyebrow">Monitoring</p>
          <h1>Alerts</h1>
          <p className="alerts-shell-lead">Watchlist matches and suspicious activity.</p>
        </div>
      </header>

      <div className="alerts-shell-nav" data-active={tab}>
        <NavLink to="/alerts" end className={({ isActive }) => (isActive ? "is-on" : undefined)}>
          Open
          {openCount > 0 ? <b>{openCount}</b> : null}
        </NavLink>
        <NavLink
          to="/alerts/acknowledged"
          className={({ isActive }) => (isActive ? "is-on" : undefined)}
        >
          Acknowledged
        </NavLink>
        <NavLink
          to="/alerts/resolved"
          className={({ isActive }) => (isActive ? "is-on" : undefined)}
        >
          Resolved
        </NavLink>
      </div>

      <Routes>
        <Route index element={<AlertsBoard status="open" />} />
        <Route path="acknowledged" element={<AlertsBoard status="acknowledged" />} />
        <Route path="resolved" element={<AlertsBoard status="resolved" />} />
      </Routes>
    </section>
  );
}
