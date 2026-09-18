import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, HeartPulse, Wrench } from "lucide-react";
import { useState } from "react";

import { Section, Toolbar } from "../../components/Page.jsx";
import { Badge, Button, EmptyState, Input, Notice, Select, Skeleton } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { fmtDateTime, humanize } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { canAdminCamera, canOperateCamera } from "../../lib/permissions.js";
import { keys, useCameras } from "../../lib/queries.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { toast } from "../notifications/notificationStore.js";
import { SourceLiveBadge } from "./badges.jsx";
import styles from "./Registry.module.css";

const ORDER_TONE = { open: "critical", in_progress: "pending", resolved: "live", cancelled: undefined };

export default function HealthView() {
  usePageTitle("Registry · Health");
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const cameras = useCameras();
  const [cameraId, setCameraId] = useState("");
  const [summary, setSummary] = useState("");
  const [note, setNote] = useState("");
  const [notes, setNotes] = useState({});
  const [saving, setSaving] = useState(false);
  const [probing, setProbing] = useState(false);

  const camera = (cameras.data ?? []).find((item) => item.camera_id === cameraId) ?? null;
  const enc = encodeURIComponent(cameraId);

  const history = useQuery({
    queryKey: ["health", cameraId],
    queryFn: () => api(`/cameras/${enc}/health-history`),
    enabled: Boolean(cameraId),
  });
  const orders = useQuery({
    queryKey: ["maintenance", cameraId],
    queryFn: () => api(`/cameras/${enc}/maintenance-work-orders`),
    enabled: Boolean(cameraId),
  });

  const canManage = canAdminCamera(user, camera);

  async function probe() {
    setProbing(true);
    try {
      const result = await api(`/probe?camera_id=${enc}`, { method: "POST" });
      toast("Probe recorded", { tone: result.results?.[0]?.transport_ok === "none" ? "critical" : "live", detail: `Transport: ${result.results?.[0]?.transport_ok ?? "unknown"}` });
      queryClient.invalidateQueries({ queryKey: ["health", cameraId] });
      queryClient.invalidateQueries({ queryKey: keys.cameras });
    } catch (error) {
      toast("Probe failed", { tone: "critical", detail: error.message });
    } finally {
      setProbing(false);
    }
  }

  async function mutate(work, message) {
    setSaving(true);
    try {
      await work();
      await queryClient.invalidateQueries({ queryKey: ["maintenance", cameraId] });
      toast(message, { tone: "live" });
      return true;
    } catch (error) {
      toast("Couldn't update maintenance", { tone: "critical", detail: error.message });
      return false;
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Toolbar label="Camera selection">
        <Select value={cameraId} onChange={(e) => setCameraId(e.target.value)} aria-label="Camera" style={{ minWidth: 320 }}>
          <option value="">Choose a camera</option>
          {(cameras.data ?? []).map((item) => (
            <option key={item.camera_id} value={item.camera_id}>
              {item.name} — {item.location_text}
            </option>
          ))}
        </Select>
        {camera && canOperateCamera(user, camera) && (
          <Button icon={<Activity />} loading={probing} onClick={probe}>
            Probe now
          </Button>
        )}
      </Toolbar>

      {!camera ? (
        <div className="ui-card">
          <EmptyState icon={<HeartPulse />} title="Choose a camera">
            See its transport probe history and open or progress maintenance work orders.
          </EmptyState>
        </div>
      ) : (
        <>
          <div className={styles.healthSummary}>
            <div>
              <span className="faint">Source</span>
              <SourceLiveBadge value={camera.is_live} />
            </div>
            <div>
              <span className="faint">Last successful connection</span>
              <span className="data">{camera.last_successful_connect ? fmtDateTime(camera.last_successful_connect) : "never"}</span>
            </div>
            <div>
              <span className="faint">Latest probe</span>
              <span>{camera.health_reason ?? "—"}</span>
            </div>
          </div>

          <Section title="Probe history">
            {history.isPending ? (
              <Skeleton height={160} />
            ) : history.isError ? (
              <Notice tone="critical">{history.error.message}</Notice>
            ) : (history.data ?? []).length === 0 ? (
              <p className="faint">No probe observations yet. Run a probe to record one.</p>
            ) : (
              <div className="ui-table-wrap">
                <table className="ui-table">
                  <thead>
                    <tr>
                      <th>Observed</th>
                      <th>Status</th>
                      <th>Transport</th>
                      <th>Source</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.data.map((row) => (
                      <tr key={row.id}>
                        <td className="data">{fmtDateTime(row.observed_at)}</td>
                        <td>{row.status}</td>
                        <td className="data">{row.transport_ok}</td>
                        <td>
                          <SourceLiveBadge value={row.is_live} />
                        </td>
                        <td>{row.reason ?? <span className="faint">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          <Section title="Maintenance work orders" description="Remediation tasks, kept separate from transport observations. Resolved and cancelled orders are immutable.">
            {canManage ? (
              <form
                className={styles.orderForm}
                onSubmit={async (event) => {
                  event.preventDefault();
                  if (!summary.trim()) return;
                  const ok = await mutate(
                    () => api(`/cameras/${enc}/maintenance-work-orders`, { method: "POST", json: { summary: summary.trim(), ...(note.trim() ? { note: note.trim() } : {}) } }),
                    "Work order opened",
                  );
                  if (ok) {
                    setSummary("");
                    setNote("");
                  }
                }}
              >
                <Input required value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="What needs fixing" aria-label="Work order summary" />
                <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Opening note (optional)" aria-label="Opening note" />
                <Button type="submit" variant="primary" icon={<Wrench />} loading={saving}>
                  Open work order
                </Button>
              </form>
            ) : (
              <p className="faint">Only a super admin or this camera's department admin can change work orders.</p>
            )}

            {orders.isPending ? (
              <Skeleton height={120} />
            ) : (orders.data ?? []).length === 0 ? (
              <p className="faint">No work orders for this camera.</p>
            ) : (
              <div className={styles.orders}>
                {orders.data.map((order) => {
                  const terminal = order.status === "resolved" || order.status === "cancelled";
                  return (
                    <article key={order.id} className={`ui-card ${styles.order}`}>
                      <header>
                        <div>
                          <strong>{order.summary}</strong>
                          <span className="faint data">Opened {fmtDateTime(order.opened_at)}</span>
                        </div>
                        {canManage && !terminal ? (
                          <Select
                            size="sm"
                            value={order.status}
                            disabled={saving}
                            onChange={(e) =>
                              mutate(
                                () => api(`/cameras/${enc}/maintenance-work-orders/${order.id}`, { method: "PATCH", json: { status: e.target.value } }),
                                "Work order updated",
                              )
                            }
                            aria-label="Work order status"
                            style={{ width: 150 }}
                          >
                            <option value="open">Open</option>
                            <option value="in_progress">In progress</option>
                            <option value="resolved">Resolved</option>
                            <option value="cancelled">Cancelled</option>
                          </Select>
                        ) : (
                          <Badge tone={ORDER_TONE[order.status]}>{humanize(order.status)}</Badge>
                        )}
                      </header>
                      <ol className={styles.events}>
                        {order.events.map((event) => (
                          <li key={event.id}>
                            <span className="data faint">{fmtDateTime(event.occurred_at)}</span>
                            <span>
                              {humanize(event.event_type)} · {humanize(event.status)}
                              {event.note ? ` — ${event.note}` : ""}
                            </span>
                          </li>
                        ))}
                      </ol>
                      {canManage && !terminal && (
                        <div className={styles.noteRow}>
                          <Input size="sm" value={notes[order.id] ?? ""} onChange={(e) => setNotes((current) => ({ ...current, [order.id]: e.target.value }))} placeholder="Add a note" aria-label="Note" />
                          <Button
                            size="sm"
                            disabled={saving || !(notes[order.id] ?? "").trim()}
                            onClick={async () => {
                              const ok = await mutate(
                                () => api(`/cameras/${enc}/maintenance-work-orders/${order.id}`, { method: "PATCH", json: { note: notes[order.id].trim() } }),
                                "Note added",
                              );
                              if (ok) setNotes((current) => ({ ...current, [order.id]: "" }));
                            }}
                          >
                            Add note
                          </Button>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </Section>
        </>
      )}
    </>
  );
}
