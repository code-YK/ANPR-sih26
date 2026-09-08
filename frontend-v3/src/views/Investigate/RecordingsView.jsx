import { useCallback, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api.js";
import { usePolling } from "../../hooks/usePolling.js";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import { canAccessDepartment, isSuperAdmin, useAuth } from "../../context/AuthContext.jsx";
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

  const refresh = useCallback(async () => {
    setRecordings(await api("/investigate/recordings"));
  }, []);

  // A recording sitting in "uploading"/"normalising" needs to move on its
  // own without a manual refresh -- poll while any row is still in flight,
  // same reasoning as the Live view's analytics status poll.
  const anyInFlight = recordings.some((r) => r.status === "uploading" || r.status === "normalising");
  usePolling(refresh, anyInFlight ? 3000 : 15000);

  const rows = recordings.filter((r) => !deptFilter || r.department === deptFilter);
  const departments = [...new Set(recordings.map((r) => r.department))].sort();
  // Upload needs operator clearance on the target department; hide the
  // button entirely for an account with no operator grant anywhere rather
  // than let them hit a 403 after picking a department in the modal.
  // `canAccessDepartment` already short-circuits true for a super admin, but
  // only when actually called with a department -- an account with no
  // per-department grants (true of every super admin) has an empty
  // `grants` array, so `.some()` over it would never call the predicate at
  // all. Check the role explicitly first, same as CameraListView/WatchlistView.
  const canUploadAnywhere =
    isSuperAdmin(user) || (user?.grants || []).some((g) => canAccessDepartment(user, g.department, "operator"));

  return (
    <>
      <div className="toolbar">
        <select value={deptFilter} onChange={(e) => setDeptFilter(e.target.value)}>
          <option value="">All departments</option>
          {departments.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        <div className="spacer" />
        {canUploadAnywhere && (
          <button className="primary" onClick={() => setShowUpload(true)}>+ Upload recording</button>
        )}
      </div>

      <table>
        <thead>
          <tr>
            <th>File</th>
            <th>Department</th>
            <th>Duration</th>
            <th>Recorded at</th>
            <th>Status</th>
            <th>Uploaded</th>
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
                <td>{r.recorded_at ? new Date(r.recorded_at).toLocaleString() : <span className="hint">unanchored</span>}</td>
                <td>
                  <span className={`badge ${cls}`} title={r.reject_reason || undefined}>{label}</span>
                </td>
                <td>{new Date(r.created_at).toLocaleString()}</td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr><td colSpan={6} className="hint">No recordings uploaded yet.</td></tr>
          )}
        </tbody>
      </table>

      <UploadModal
        open={showUpload}
        onClose={() => setShowUpload(false)}
        onUploaded={() => refresh()}
      />
    </>
  );
}
