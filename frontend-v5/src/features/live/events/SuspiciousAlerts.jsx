import { useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { memo, useMemo, useState } from "react";

import { Badge, Button, EmptyState, Skeleton } from "../../../components/ui.jsx";
import { api } from "../../../lib/api/client.js";
import { fmtClock, fmtConfidence } from "../../../lib/format.js";
import { canAccessDepartment } from "../../../lib/permissions.js";
import { useCameraAlerts } from "../../../lib/queries.js";
import { useAuth } from "../../auth/AuthProvider.jsx";
import { toast } from "../../notifications/notificationStore.js";
import { EventsHeader, useFreshIds, useRegisterPanel } from "./shared.jsx";
import styles from "./Events.module.css";

const STATUS_TONE = { open: "critical", acknowledged: "pending", resolved: undefined };

function SuspiciousAlerts({ camera, variant }) {
  useRegisterPanel(`${camera.camera_id}::suspicious`);
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const alerts = useCameraAlerts(camera.camera_id);
  const [busyId, setBusyId] = useState(null);
  const rows = useMemo(() => (alerts.data ?? []).filter((alert) => alert.alert_type === "suspicious"), [alerts.data]);
  const fresh = useFreshIds(alerts.data ? rows : null);
  const canAct = canAccessDepartment(user, camera.department, "operator");

  async function act(alert, action) {
    setBusyId(alert.id);
    try {
      await api(`/alerts/${alert.id}/${action}`, { method: "POST" });
      await queryClient.invalidateQueries({ queryKey: ["alerts"] });
    } catch (error) {
      toast(`Couldn't ${action} the alert`, { tone: "critical", detail: error.message });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <EventsHeader title="Alerts" count={rows.length || null} />
      {alerts.isPending ? (
        <Skeleton height={52} />
      ) : rows.length === 0 ? (
        <EmptyState compact icon={<ShieldAlert />} title="No suspicious activity flagged">
          A person is flagged only after the model classifies them as potentially dangerous in three consecutive frames.
        </EmptyState>
      ) : (
        <ul className={styles.list} data-variant={variant}>
            {rows.map((alert) => {
              const track = alert.dedup_key?.split(":").pop();
              return (
                <li key={alert.id}>
                  <div className={styles.row} data-static data-fresh={fresh.has(alert.id) || undefined} data-alert={alert.status === "open" ? "true" : undefined}>
                    <span className={`${styles.thumb} ${styles.thumbAlert}`} aria-hidden="true">
                      <ShieldAlert />
                    </span>
                    <span className={styles.rowMain}>
                      <span className={styles.rowTitle}>{alert.label ?? "Potentially dangerous person"}</span>
                      <span className={styles.rowMeta}>
                        {track ? `Track #${track} · ` : ""}confidence <span className="tabular">{fmtConfidence(alert.match_confidence)}</span>
                      </span>
                    </span>
                    <Badge tone={STATUS_TONE[alert.status]}>{alert.status}</Badge>
                    {canAct && alert.status !== "resolved" && (
                      <span className={styles.rowActions}>
                        {alert.status === "open" && (
                          <Button size="sm" variant="ghost" disabled={busyId === alert.id} onClick={() => act(alert, "acknowledge")}>
                            Acknowledge
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" disabled={busyId === alert.id} onClick={() => act(alert, "resolve")}>
                          Resolve
                        </Button>
                      </span>
                    )}
                    <time className={styles.time} dateTime={alert.event_time}>
                      {fmtClock(alert.event_time)}
                    </time>
                  </div>
                </li>
              );
            })}
        </ul>
      )}
    </>
  );
}

export default memo(SuspiciousAlerts);
