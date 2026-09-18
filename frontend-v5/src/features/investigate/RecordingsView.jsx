import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileVideo, Trash2, Upload } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Toolbar, useConfirm } from "../../components/Page.jsx";
import { Badge, Button, EmptyState, IconButton, Select, Skeleton, Tooltip } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { fmtDateTime, fmtDuration } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { canOperateAnywhere, isDepartmentAdmin, isSuperAdmin } from "../../lib/permissions.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { toast } from "../notifications/notificationStore.js";
import UploadDialog from "./UploadDialog.jsx";

const STATUS = {
  uploading: ["Uploading", "pending"],
  normalising: ["Normalising", "pending"],
  ready: ["Ready", "live"],
  rejected: ["Rejected", "critical"],
};

function fmtBytes(bytes) {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
}

export default function RecordingsView() {
  usePageTitle("Investigate");
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [department, setDepartment] = useState("");
  const [uploading, setUploading] = useState(false);
  const [confirm, confirmDialog] = useConfirm();

  const recordings = useQuery({
    queryKey: ["recordings"],
    queryFn: () => api("/investigate/recordings"),
    refetchInterval: (query) => ((query.state.data ?? []).some((row) => row.status === "uploading" || row.status === "normalising") ? 3_000 : 15_000),
  });

  const departments = useMemo(() => [...new Set((recordings.data ?? []).map((row) => row.department))].sort(), [recordings.data]);
  const rows = (recordings.data ?? []).filter((row) => !department || row.department === department);

  const canDelete = (row) => isSuperAdmin(user) || (isDepartmentAdmin(user) && user.home_department === row.department);

  async function remove(row) {
    const ok = await confirm({
      title: `Delete ${row.original_filename}?`,
      body: "The recording, its ingest runs and every extracted track are permanently removed.",
      confirmLabel: "Delete recording",
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/investigate/recordings/${row.id}`, { method: "DELETE" });
      toast("Recording deleted", { tone: "live" });
      queryClient.invalidateQueries({ queryKey: ["recordings"] });
    } catch (error) {
      toast("Couldn't delete the recording", { tone: "critical", detail: error.message });
    }
  }

  return (
    <>
      <Toolbar label="Recordings">
        <Select value={department} onChange={(e) => setDepartment(e.target.value)} aria-label="Department">
          <option value="">All departments</option>
          {departments.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </Select>
        <div style={{ flex: 1 }} />
        {canOperateAnywhere(user) && (
          <Button variant="primary" icon={<Upload />} onClick={() => setUploading(true)}>
            Upload recording
          </Button>
        )}
      </Toolbar>

      {recordings.isPending ? (
        <Skeleton height={260} />
      ) : rows.length === 0 ? (
        <div className="ui-card">
          <EmptyState icon={<FileVideo />} title="No recordings yet">
            Upload footage to extract vehicle and person tracks you can search later.
          </EmptyState>
        </div>
      ) : (
        <div className="ui-table-wrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th>Recording</th>
                <th>Department</th>
                <th className="ui-table__num">Duration</th>
                <th>Recorded</th>
                <th>Status</th>
                <th>Uploaded</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const [label, tone] = STATUS[row.status] ?? [row.status];
                return (
                  <tr key={row.id}>
                    <td>
                      <Link to={`/investigate/recordings/${row.id}`} className="ui-table__primary">
                        {row.original_filename}
                      </Link>
                      <span className="ui-table__secondary">
                        {row.width && row.height ? `${row.width}×${row.height} · ` : ""}
                        {fmtBytes(row.size_bytes)}
                        {row.camera_id ? ` · ${row.camera_id}` : row.location_text ? ` · ${row.location_text}` : ""}
                      </span>
                    </td>
                    <td>{row.department}</td>
                    <td className="ui-table__num data">{fmtDuration(row.duration_seconds)}</td>
                    <td className="data">
                      {row.recorded_at ? (
                        fmtDateTime(row.recorded_at)
                      ) : (
                        <Tooltip content="No recording time was given, so track times are relative to the start of the file.">
                          <span>
                            <Badge outline>unanchored</Badge>
                          </span>
                        </Tooltip>
                      )}
                    </td>
                    <td>
                      <Tooltip content={row.reject_reason ?? null}>
                        <span>
                          <Badge tone={tone}>{label}</Badge>
                        </span>
                      </Tooltip>
                    </td>
                    <td className="data">{fmtDateTime(row.created_at)}</td>
                    <td>
                      <div className="ui-table__actions">
                        {canDelete(row) && (
                          <IconButton label="Delete recording" size="sm" onClick={() => remove(row)}>
                            <Trash2 />
                          </IconButton>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <UploadDialog open={uploading} onClose={() => setUploading(false)} onUploaded={() => queryClient.invalidateQueries({ queryKey: ["recordings"] })} />
      {confirmDialog}
    </>
  );
}
