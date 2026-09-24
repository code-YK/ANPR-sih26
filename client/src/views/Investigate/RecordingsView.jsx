import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { Trash2 } from "lucide-react";

import { api } from "../../api.js";
import { useConfirm } from "../../components/ConfirmDialog.jsx";
import { useToast } from "../../components/Toast.jsx";
import { canAccessDepartment, isDepartmentAdmin, isSuperAdmin, useAuth } from "../../context/AuthContext.jsx";
import { usePolling } from "../../hooks/usePolling.js";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import UploadModal from "./UploadModal.jsx";

const STATUS_LABEL = {
  uploading: ["Uploading", "badge-muted"],
  normalising: ["Normalising", "badge-warn"],
  ready: ["Ready", "badge-ok"],
  rejected: ["Rejected", "badge-bad"],
};

export default function RecordingsView() {
  usePageTitle("Investigate");
  const { user } = useAuth();
  const [recordings, setRecordings] = useState([]);
  const [showUpload, setShowUpload] = useState(false);
  const [deptFilter, setDeptFilter] = useState("");
  // Until the first reply the list is unknown, not empty: this said "No
  // recordings uploaded yet" on every visit while the request was in flight.
  const [loaded, setLoaded] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [confirm, confirmDialog] = useConfirm();
  const showToast = useToast();

  const refresh = useCallback(async (signal) => {
    setRecordings(await api("/investigate/recordings", { signal }));
    setLoaded(true);
  }, []);

  const anyInFlight = recordings.some((r) => r.status === "uploading" || r.status === "normalising");
  usePolling(refresh, anyInFlight ? 3000 : 15000);

  const rows = recordings.filter((r) => !deptFilter || r.department === deptFilter);
  const departments = [...new Set(recordings.map((r) => r.department))].sort();
  // Mirrors investigate.py's delete_recording: a department admin for the
  // recording's own department, or a super admin. The API enforces it; this
  // only avoids offering a button that would be refused.
  const canDelete = (r) =>
    isSuperAdmin(user) || (isDepartmentAdmin(user) && user?.home_department === r.department);

  async function remove(r) {
    const ok = await confirm({
      title: `Delete ${r.original_filename}?`,
      body: "The recording, its ingest runs and every track found in it are removed, and the file is deleted from disk. This is recorded in the audit log and cannot be undone.",
      confirmLabel: "Delete recording",
      danger: true,
    });
    if (!ok) return;
    setDeletingId(r.id);
    try {
      await api(`/investigate/recordings/${r.id}`, { method: "DELETE" });
      setRecordings((prev) => prev.filter((row) => row.id !== r.id));
      showToast(`${r.original_filename} deleted`);
    } catch (err) {
      showToast("Delete failed: " + err.message);
    } finally {
      setDeletingId(null);
    }
  }

  const canUploadAnywhere =
    isSuperAdmin(user) || (user?.grants || []).some((g) => canAccessDepartment(user, g.department, "operator"));

  return (
    <div className="investigate-panel">
      <div className="investigate-toolbar">
        <label className="investigate-field">
          <span>Department</span>
          <select value={deptFilter} onChange={(e) => setDeptFilter(e.target.value)}>
            <option value="">All departments</option>
            {departments.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <div className="spacer" />
        {canUploadAnywhere && (
          <button
            type="button"
            className="primary investigate-upload-btn"
            onClick={() => setShowUpload(true)}
          >
            + Upload recording
          </button>
        )}
      </div>

      <div className="investigate-table-wrap">
        <table className="investigate-table">
          <thead>
            <tr>
              <th>File</th>
              <th>Department</th>
              <th>Duration</th>
              <th>Recorded at</th>
              <th>Status</th>
              <th>Uploaded</th>
              <th>
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const [label, cls] = STATUS_LABEL[r.status] || [r.status, "badge-muted"];
              return (
                <tr key={r.id}>
                  <td>
                    <Link to={`/investigate/recordings/${r.id}`}>{r.original_filename}</Link>
                  </td>
                  <td>{r.department}</td>
                  <td>{r.duration_seconds ? `${Math.round(r.duration_seconds)}s` : "—"}</td>
                  <td>
                    {r.recorded_at ? (
                      new Date(r.recorded_at).toLocaleString()
                    ) : (
                      <span className="hint">unanchored</span>
                    )}
                  </td>
                  <td>
                    <span className={`badge ${cls}`} title={r.reject_reason || undefined}>
                      {label}
                    </span>
                  </td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td className="investigate-td-actions">
                    {canDelete(r) && (
                      <button
                        type="button"
                        className="registry-icon-btn"
                        title="Delete recording"
                        aria-label={`Delete ${r.original_filename}`}
                        disabled={deletingId === r.id}
                        onClick={() => remove(r)}
                      >
                        <Trash2 size={15} strokeWidth={2} />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="hint">
                  {!loaded
                    ? "Loading recordings…"
                    : deptFilter
                      ? `No recordings in ${deptFilter}.`
                      : "No recordings uploaded yet."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <UploadModal open={showUpload} onClose={() => setShowUpload(false)} onUploaded={() => refresh()} />
      {confirmDialog}
    </div>
  );
}
