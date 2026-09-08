import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api.js";
import { useToast } from "../../components/Toast.jsx";
import { isSuperAdmin, useAuth } from "../../context/AuthContext.jsx";
import { useGsapReveal } from "../../hooks/useGsapReveal.js";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import WatchlistEntryModal from "./WatchlistEntryModal.jsx";

function severityBadge(sev) {
  const cls = sev === "high" ? "badge-bad" : sev === "medium" ? "badge-warn" : "badge-muted";
  return <span className={`badge ${cls}`}>{sev}</span>;
}

export default function WatchlistView() {
  usePageTitle("Watchlist");
  const { user } = useAuth();
  const canManage = isSuperAdmin(user);
  const [entries, setEntries] = useState([]);
  const [activeOnly, setActiveOnly] = useState(false);
  const [editing, setEditing] = useState(null);
  const [creating, setCreating] = useState(false);
  const showToast = useToast();

  const tableRef = useGsapReveal("tbody tr", { stagger: 0.03, duration: 0.35, y: 12 }, [entries.length]);

  async function load() {
    const params = activeOnly ? "?active=true" : "";
    setEntries(await api(`/watchlist${params}`));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOnly]);

  async function handleDelete(entry) {
    if (!window.confirm(`Remove ${entry.raw_value} from the watchlist?`)) return;
    try {
      await api(`/watchlist/${entry.id}`, { method: "DELETE" });
      showToast("Removed");
      await load();
    } catch (err) {
      showToast("Delete failed: " + err.message);
    }
  }

  async function handleBulkImport(e) {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const result = await api("/watchlist/bulk", { method: "POST", body: fd });
      showToast(`Import: ${result.added} added, ${result.failed} failed (of ${result.total_rows})`);
      await load();
    } catch (err) {
      showToast("Import failed: " + err.message);
    }
    e.target.value = "";
  }

  return (
    <section className="view active">
      <div className="toolbar">
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} />
          Active only
        </label>
        <div className="spacer" />
        {canManage && (
          <>
            <label className="secondary" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              Bulk import CSV
              <input type="file" accept=".csv" style={{ display: "none" }} onChange={handleBulkImport} />
            </label>
            <button className="primary" onClick={() => setCreating(true)}>+ Add entry</button>
          </>
        )}
      </div>

      {entries.length === 0 ? (
        <p className="hint">No watchlist entries yet.</p>
      ) : (
        <table ref={tableRef}>
          <thead>
            <tr>
              <th>Plate</th>
              <th>Reason</th>
              <th>Severity</th>
              <th>Source</th>
              <th>Active</th>
              <th>Added</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.id}>
                <td>
                  <Link to={`/journey/${entry.normalised_value}`}>{entry.raw_value}</Link>
                </td>
                <td>{entry.reason_code ?? "—"}</td>
                <td>{severityBadge(entry.severity)}</td>
                <td>{entry.source ?? "—"}</td>
                <td>
                  <span className={`badge ${entry.active ? "badge-ok" : "badge-muted"}`}>
                    {entry.active ? "active" : "inactive"}
                  </span>
                </td>
                <td>{new Date(entry.created_at).toLocaleDateString()}</td>
                <td>
                  {canManage && (
                    <>
                      <button className="link-btn" onClick={() => setEditing(entry)}>Edit</button>{" "}
                      <button className="link-btn" onClick={() => handleDelete(entry)}>Delete</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {canManage && <WatchlistEntryModal open={!!editing} entry={editing} onClose={() => setEditing(null)} onSaved={load} />}
      {canManage && <WatchlistEntryModal open={creating} entry={null} onClose={() => setCreating(false)} onSaved={load} />}
    </section>
  );
}
