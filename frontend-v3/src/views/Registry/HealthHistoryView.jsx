import { useEffect, useState } from "react";

import { api } from "../../api.js";
import { LiveBadge } from "../../components/Badge.jsx";
import { useToast } from "../../components/Toast.jsx";
import { isDepartmentAdmin, isSuperAdmin, useAuth } from "../../context/AuthContext.jsx";
import { useCameras } from "../../context/CamerasContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";

function fmtTime(iso) {
  return new Date(iso).toLocaleString();
}

export default function HealthHistoryView() {
  usePageTitle("Registry · Health history");
  const { cameras } = useCameras();
  const { user } = useAuth();
  const showToast = useToast();
  const [cameraId, setCameraId] = useState("");
  const [history, setHistory] = useState([]);
  const [workOrders, setWorkOrders] = useState([]);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState("");
  const [openingNote, setOpeningNote] = useState("");
  const [notes, setNotes] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!cameraId) {
      setHistory([]);
      setWorkOrders([]);
      return undefined;
    }
    let cancelled = false;
    setError("");
    Promise.all([
      api(`/cameras/${encodeURIComponent(cameraId)}/health-history`),
      api(`/cameras/${encodeURIComponent(cameraId)}/maintenance-work-orders`),
    ])
      .then(([healthRows, maintenanceRows]) => {
        if (!cancelled) {
          setHistory(healthRows);
          setWorkOrders(maintenanceRows);
        }
      })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [cameraId]);

  const selected = cameras.find((camera) => camera.camera_id === cameraId);
  const canManage = Boolean(
    selected && (isSuperAdmin(user) || (isDepartmentAdmin(user) && selected.department === user.home_department)),
  );

  async function reloadWorkOrders() {
    const rows = await api(`/cameras/${encodeURIComponent(cameraId)}/maintenance-work-orders`);
    setWorkOrders(rows);
  }

  async function createWorkOrder(e) {
    e.preventDefault();
    if (!summary.trim()) return;
    setSaving(true);
    try {
      await api(`/cameras/${encodeURIComponent(cameraId)}/maintenance-work-orders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ summary: summary.trim(), ...(openingNote.trim() ? { note: openingNote.trim() } : {}) }),
      });
      setSummary("");
      setOpeningNote("");
      await reloadWorkOrders();
      showToast("Maintenance work order opened");
    } catch (err) {
      showToast("Could not open work order: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  async function updateWorkOrder(order, changes) {
    setSaving(true);
    try {
      await api(`/cameras/${encodeURIComponent(cameraId)}/maintenance-work-orders/${order.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(changes),
      });
      setNotes((current) => ({ ...current, [order.id]: "" }));
      await reloadWorkOrders();
      showToast("Maintenance history updated");
    } catch (err) {
      showToast("Could not update work order: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="toolbar">
        <select value={cameraId} onChange={(e) => setCameraId(e.target.value)} aria-label="Camera health history">
          <option value="">Select an authorised camera</option>
          {cameras.map((camera) => (
            <option key={camera.camera_id} value={camera.camera_id}>{camera.name} — {camera.location_text}</option>
          ))}
        </select>
      </div>
      {selected && (
        <p className="hint">
          Current catalogue state: <LiveBadge value={selected.is_live} /> · last successful transport: {selected.last_successful_connect ? fmtTime(selected.last_successful_connect) : "never"}
          {selected.health_reason ? ` · latest probe: ${selected.health_reason}` : ""}
        </p>
      )}
      {error && <p className="hint hint-warn">Health or maintenance history unavailable: {error}</p>}
      {cameraId && !error && history.length === 0 && <p className="hint">No probe observations yet. Run a single-camera probe to record one.</p>}
      {history.length > 0 && (
        <table>
          <thead><tr><th>Observed UTC</th><th>Status</th><th>Transport</th><th>Catalogue live</th><th>Reason</th></tr></thead>
          <tbody>
            {history.map((row) => (
              <tr key={row.id}>
                <td>{fmtTime(row.observed_at)}</td>
                <td>{row.status}</td>
                <td>{row.transport_ok}</td>
                <td><LiveBadge value={row.is_live} /></td>
                <td>{row.reason ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {selected && (
        <section style={{ marginTop: 24 }}>
          <h3>Maintenance work orders</h3>
          <p className="hint">Open and progress remediation tasks separately from transport observations. Resolved and cancelled records are immutable.</p>
          {canManage && (
            <form className="toolbar" onSubmit={createWorkOrder}>
              <input value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="Remediation summary" aria-label="Maintenance summary" required />
              <input value={openingNote} onChange={(e) => setOpeningNote(e.target.value)} placeholder="Optional opening note" aria-label="Maintenance opening note" />
              <button className="secondary" disabled={saving}>Open work order</button>
            </form>
          )}
          {!canManage && <p className="hint">Only a super admin or this camera’s home-department admin can change maintenance work orders.</p>}
          {workOrders.length === 0 && <p className="hint">No maintenance work orders yet.</p>}
          {workOrders.length > 0 && (
            <table>
              <thead><tr><th>Opened UTC</th><th>Summary</th><th>Status</th><th>Lifecycle history</th><th>Update</th></tr></thead>
              <tbody>
                {workOrders.map((order) => {
                  const terminal = ["resolved", "cancelled"].includes(order.status);
                  return (
                    <tr key={order.id}>
                      <td>{fmtTime(order.opened_at)}</td>
                      <td>{order.summary}</td>
                      <td>
                        {canManage && !terminal ? (
                          <select value={order.status} disabled={saving} onChange={(e) => updateWorkOrder(order, { status: e.target.value })} aria-label={`Maintenance status for ${order.summary}`}>
                            <option value="open">Open</option><option value="in_progress">In progress</option><option value="resolved">Resolved</option><option value="cancelled">Cancelled</option>
                          </select>
                        ) : order.status}
                      </td>
                      <td>{order.events.map((event) => <div key={event.id}>{fmtTime(event.occurred_at)} · {event.event_type.replace("_", " ")} · {event.status}{event.note ? ` — ${event.note}` : ""}</div>)}</td>
                      <td>{canManage && !terminal && (
                        <div className="toolbar">
                          <input value={notes[order.id] ?? ""} onChange={(e) => setNotes((current) => ({ ...current, [order.id]: e.target.value }))} placeholder="Add note" aria-label={`Maintenance note for ${order.summary}`} />
                          <button className="link-btn" type="button" disabled={saving || !(notes[order.id] ?? "").trim()} onClick={() => updateWorkOrder(order, { note: notes[order.id].trim() })}>Add note</button>
                        </div>
                      )}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      )}
    </>
  );
}
