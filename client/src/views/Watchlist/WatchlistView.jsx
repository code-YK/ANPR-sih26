import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Pencil, Plus, Search, Trash2, Upload } from "lucide-react";

import { api } from "../../api.js";
import { useToast } from "../../components/Toast.jsx";
import { isSuperAdmin, useAuth } from "../../context/AuthContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import { plateGroups } from "../../lib/plate.js";
import WatchlistEntryModal from "./WatchlistEntryModal.jsx";

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "—";
  }
}

function PlateChip({ plate }) {
  if (!plate) return <span className="faint">—</span>;
  const tentative = String(plate).endsWith("?");
  return (
    <span
      className={
        tentative ? "alerts-plate-chip alerts-plate-chip--tentative" : "alerts-plate-chip"
      }
      aria-label={`Plate ${String(plate).replace("?", "")}`}
    >
      <span className="alerts-plate-chip-stripe" aria-hidden="true">
        IND
      </span>
      <span className="alerts-plate-chip-text" aria-hidden="true">
        {plateGroups(plate).map((group, index) => (
          <span key={index}>{group}</span>
        ))}
      </span>
    </span>
  );
}

export default function WatchlistView() {
  usePageTitle("Watchlist");
  const { user } = useAuth();
  const canManage = isSuperAdmin(user);
  const [entries, setEntries] = useState([]);
  const [activeOnly, setActiveOnly] = useState(false);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(null);
  const [creating, setCreating] = useState(false);
  const showToast = useToast();

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

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return entries;
    return entries.filter((e) => {
      const hay = [e.raw_value, e.reason_code, e.reason, e.notes, e.source]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(needle);
    });
  }, [entries, query]);

  return (
    <section className="watchlist-shell">
      <header className="watchlist-page-header">
        <div>
          <p className="watchlist-eyebrow">Monitoring</p>
          <h1>Watchlist</h1>
          <p className="watchlist-lead">
            Plates that raise an alert when a camera confirms them.
          </p>
        </div>
        {canManage && (
          <div className="watchlist-header-actions">
            <label className="secondary watchlist-import-btn">
              <Upload size={15} strokeWidth={2} />
              Import CSV
              <input type="file" accept=".csv,text/csv" onChange={handleBulkImport} hidden />
            </label>
            <button
              type="button"
              className="primary watchlist-add-btn"
              onClick={() => setCreating(true)}
            >
              <Plus size={16} strokeWidth={2.25} />
              Add plate
            </button>
          </div>
        )}
      </header>

      <div className="watchlist-toolbar">
        <label className="watchlist-search">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search plate, reason or source"
            aria-label="Search watchlist"
          />
          <Search size={15} strokeWidth={2} aria-hidden="true" />
        </label>
        <label className="watchlist-toggle">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => setActiveOnly(e.target.checked)}
          />
          Active only
        </label>
      </div>

      {rows.length === 0 ? (
        <div className="watchlist-empty">
          <strong>{activeOnly || query ? "No matching entries" : "Watchlist is empty"}</strong>
          <p>
            {canManage
              ? "Add a plate or import a CSV to start receiving priority alerts."
              : "No entries are visible under the current filter."}
          </p>
        </div>
      ) : (
        <div className="watchlist-table-wrap">
          <table className="watchlist-table">
            <thead>
              <tr>
                <th>Plate</th>
                <th>Reason</th>
                <th>Severity</th>
                <th>Source</th>
                <th>Status</th>
                <th>Added</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((entry) => (
                <tr key={entry.id} className={entry.active ? "is-active" : "is-idle"}>
                  <td>
                    <Link to={`/journey/${entry.raw_value}`} className="watchlist-plate-link">
                      <PlateChip plate={entry.raw_value} />
                    </Link>
                  </td>
                  <td className="watchlist-td-reason">
                    <strong>{entry.reason_code || entry.reason || "—"}</strong>
                    {entry.notes ? <span>{entry.notes}</span> : null}
                  </td>
                  <td>
                    <span className={`alerts-sev-pill sev-${entry.severity || "low"}`}>
                      {entry.severity || "low"}
                    </span>
                  </td>
                  <td className="watchlist-td-source mono">{entry.source || "—"}</td>
                  <td>
                    <span
                      className={
                        entry.active
                          ? "watchlist-status-pill is-active"
                          : "watchlist-status-pill is-idle"
                      }
                    >
                      {entry.active ? "active" : "inactive"}
                    </span>
                  </td>
                  <td className="watchlist-td-added">
                    {fmtDate(entry.created_at || entry.added_at || entry.updated_at)}
                  </td>
                  <td className="watchlist-td-actions">
                    {canManage && (
                      <>
                        <button
                          type="button"
                          className="watchlist-icon-btn"
                          title="Edit"
                          aria-label={`Edit ${entry.raw_value}`}
                          onClick={() => setEditing(entry)}
                        >
                          <Pencil size={15} strokeWidth={2} />
                        </button>
                        <button
                          type="button"
                          className="watchlist-icon-btn is-danger"
                          title="Delete"
                          aria-label={`Delete ${entry.raw_value}`}
                          onClick={() => handleDelete(entry)}
                        >
                          <Trash2 size={15} strokeWidth={2} />
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {canManage && (
        <WatchlistEntryModal
          open={!!editing}
          entry={editing}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
      {canManage && (
        <WatchlistEntryModal
          open={creating}
          entry={null}
          onClose={() => setCreating(false)}
          onSaved={load}
        />
      )}
    </section>
  );
}
