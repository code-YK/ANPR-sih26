import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellOff, Search, ShieldAlert, UserRoundX } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";

import { Page, PageHeader, SubNav, Toolbar } from "../../components/Page.jsx";
import { Badge, Button, EmptyState, Input, PlateChip, Segmented, Skeleton } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { fmtConfidence, fmtDateTime, humanize } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { canAccessDepartment } from "../../lib/permissions.js";
import { keys, useOpenAlerts } from "../../lib/queries.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { useFreshIds } from "../live/events/shared.jsx";
import { toast } from "../notifications/notificationStore.js";
import styles from "./Alerts.module.css";

const SEVERITY_TONE = { high: "critical", medium: "pending", low: undefined };
const STATUS_TONE = { open: "critical", acknowledged: "pending", resolved: "live" };

function AlertsTable({ status }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const open = useOpenAlerts({ enabled: status === "open" });
  const other = useQuery({
    queryKey: keys.alerts(status),
    queryFn: () => api(`/alerts?status=${status}&limit=300`),
    enabled: status !== "open",
    refetchInterval: 10_000,
  });
  const query = status === "open" ? open : other;
  const [search, setSearch] = useState("");
  const [type, setType] = useState("all");
  const [busyId, setBusyId] = useState(null);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (query.data ?? []).filter((alert) => {
      if (type !== "all" && alert.alert_type !== type) return false;
      if (!needle) return true;
      return [alert.plate, alert.label, alert.camera_name, alert.camera_id, alert.location_text, alert.reason_code]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle));
    });
  }, [query.data, search, type]);
  const fresh = useFreshIds(query.data ?? null);

  async function act(alert, action) {
    setBusyId(alert.id);
    try {
      await api(`/alerts/${alert.id}/${action}`, { method: "POST" });
      await queryClient.invalidateQueries({ queryKey: ["alerts"] });
      toast(action === "acknowledge" ? "Alert acknowledged" : "Alert resolved", { tone: "live" });
    } catch (error) {
      toast(`Couldn't ${action} the alert`, { tone: "critical", detail: error.message });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <Toolbar label="Alert filters">
        <div className="ui-search">
          <Search aria-hidden="true" />
          <Input type="search" placeholder="Plate, camera or reason" value={search} onChange={(event) => setSearch(event.target.value)} aria-label="Search alerts" />
        </div>
        <Segmented
          label="Alert type"

          value={type}
          onChange={setType}
          options={[
            { value: "all", label: "All" },
            { value: "watchlist", label: "Watchlist" },
            { value: "suspicious", label: "Suspicious" },
          ]}
        />
      </Toolbar>

      {query.isPending ? (
        <Skeleton height={280} />
      ) : rows.length === 0 ? (
        <div className="ui-card">
          <EmptyState icon={<BellOff />} title={`No ${status} alerts`}>
            {status === "open"
              ? "Watchlist matches and suspicious-activity detections appear here the moment a worker raises them."
              : search || type !== "all"
                ? "Nothing matches these filters."
                : `Alerts you ${status === "acknowledged" ? "acknowledge" : "resolve"} are kept here.`}
          </EmptyState>
        </div>
      ) : (
        <div className="ui-table-wrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th>Subject</th>
                <th>Camera</th>
                <th>Reason</th>
                <th>Severity</th>
                <th className="ui-table__num">Confidence</th>
                <th>Time</th>
                <th>Status</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((alert) => {
                const canAct = canAccessDepartment(user, alert.department, "operator");
                return (
                  <tr key={alert.id} className={fresh.has(alert.id) ? styles.fresh : undefined}>
                    <td>
                      <div className={styles.subject}>
                        {alert.alert_type === "suspicious" ? (
                          <>
                            <span className={styles.subjectIcon} aria-hidden="true">
                              <UserRoundX />
                            </span>
                            <span className="ui-table__primary">{alert.label ?? "Potentially dangerous person"}</span>
                          </>
                        ) : (
                          <>
                            <span className={styles.subjectIcon} data-kind="watchlist" aria-hidden="true">
                              <ShieldAlert />
                            </span>
                            <Link to={`/journeys/${encodeURIComponent(alert.plate)}`} title="View journey">
                              <PlateChip plate={alert.plate} />
                            </Link>
                          </>
                        )}
                      </div>
                    </td>
                    <td>
                      <Link to={`/live/${encodeURIComponent(alert.camera_id)}?ai=${alert.alert_type === "suspicious" ? "suspicious" : "anpr"}`} className="ui-table__primary">
                        {alert.camera_name}
                      </Link>
                      <span className="ui-table__secondary">{alert.location_text}</span>
                    </td>
                    <td>{alert.reason_code ? humanize(alert.reason_code) : <span className="faint">—</span>}</td>
                    <td>{alert.severity ? <Badge tone={SEVERITY_TONE[alert.severity]}>{alert.severity}</Badge> : <span className="faint">—</span>}</td>
                    <td className="ui-table__num data">{fmtConfidence(alert.match_confidence)}</td>
                    <td className="data">{fmtDateTime(alert.event_time)}</td>
                    <td>
                      <Badge tone={STATUS_TONE[alert.status]}>{alert.status}</Badge>
                    </td>
                    <td>
                      {canAct && alert.status !== "resolved" && (
                        <div className="ui-table__actions">
                          {alert.status === "open" && (
                            <Button size="sm" variant="ghost" disabled={busyId === alert.id} onClick={() => act(alert, "acknowledge")}>
                              Acknowledge
                            </Button>
                          )}
                          <Button size="sm" variant="secondary" disabled={busyId === alert.id} onClick={() => act(alert, "resolve")}>
                            Resolve
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function AlertsView() {
  usePageTitle("Alerts");
  const open = useOpenAlerts();
  return (
    <Page>
      <PageHeader
        overline="Monitoring"
        title="Alerts"
        description="Watchlist matches and suspicious activity."
      />
      <SubNav
        label="Alert status"

        items={[
          { to: "/alerts", label: "Open", end: true, count: open.data?.length || null },
          { to: "/alerts/acknowledged", label: "Acknowledged" },
          { to: "/alerts/resolved", label: "Resolved" },
        ]}
      />
      <Routes>
        <Route index element={<AlertsTable status="open" />} />
        <Route path="acknowledged" element={<AlertsTable status="acknowledged" />} />
        <Route path="resolved" element={<AlertsTable status="resolved" />} />
        <Route path="*" element={<Navigate to="/alerts" replace />} />
      </Routes>
    </Page>
  );
}
