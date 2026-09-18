import { UploadCloud } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button, Dialog, Field, Input, Select } from "../../components/ui.jsx";
import { API } from "../../lib/api/client.js";
import { canAccessDepartment } from "../../lib/permissions.js";
import { useDepartments } from "../../lib/queries.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { toast } from "../notifications/notificationStore.js";
import styles from "./Investigate.module.css";

/**
 * Upload is a multipart POST with query-string fields, and can take minutes
 * (streamed to disk, hashed, then normalised with ffmpeg) -- so it uses XHR
 * for real upload progress instead of the fetch-based api() helper.
 */
export default function UploadDialog({ open, onClose, onUploaded }) {
  const { user } = useAuth();
  const departments = useDepartments();
  const allowed = (departments.data ?? []).filter((item) => canAccessDepartment(user, item.name, "operator"));
  const [file, setFile] = useState(null);
  const [department, setDepartment] = useState("");
  const [cameraId, setCameraId] = useState("");
  const [locationText, setLocationText] = useState("");
  const [recordedAt, setRecordedAt] = useState("");
  const [progress, setProgress] = useState(null);
  const xhrRef = useRef(null);

  useEffect(() => {
    if (open && !department) setDepartment(user.home_department && allowed.some((item) => item.name === user.home_department) ? user.home_department : allowed[0]?.name ?? "");
    if (!open) {
      setFile(null);
      setProgress(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, departments.data]);

  const busy = progress !== null;

  function submit(event) {
    event.preventDefault();
    if (!file || !department) return;
    const params = new URLSearchParams({ department });
    if (cameraId.trim()) params.set("camera_id", cameraId.trim());
    if (locationText.trim()) params.set("location_text", locationText.trim());
    if (recordedAt) params.set("recorded_at", new Date(recordedAt).toISOString());
    const body = new FormData();
    body.append("file", file);

    const xhr = new XMLHttpRequest();
    xhrRef.current = xhr;
    xhr.open("POST", `${API}/investigate/recordings?${params}`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => e.lengthComputable && setProgress(e.loaded / e.total);
    xhr.upload.onload = () => setProgress(1);
    xhr.onload = () => {
      setProgress(null);
      let data = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        // not JSON
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        toast(data?.status === "ready" ? "Recording uploaded and ready" : data?.status === "rejected" ? "Upload rejected" : "Recording uploaded", {
          tone: data?.status === "rejected" ? "critical" : "live",
          detail: data?.reject_reason ?? undefined,
        });
        onUploaded(data);
        onClose();
      } else {
        toast("Upload failed", { tone: "critical", detail: typeof data?.detail === "string" ? data.detail : `HTTP ${xhr.status}` });
      }
    };
    xhr.onerror = () => {
      setProgress(null);
      toast("Upload failed", { tone: "critical", detail: "Network error" });
    };
    setProgress(0);
    xhr.send(body);
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      title="Upload a recording"
      description="Footage is checked, hashed and normalised for playback before ingest can run."
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" form="upload-form" variant="primary" loading={busy} disabled={!file || !department}>
            {progress === null ? "Upload" : progress < 1 ? `Uploading ${Math.round(progress * 100)}%` : "Normalising…"}
          </Button>
        </>
      }
    >
      <form id="upload-form" onSubmit={submit} style={{ display: "grid", gap: 16 }}>
        <label className={styles.drop} data-has-file={Boolean(file) || undefined}>
          <UploadCloud aria-hidden="true" />
          <span>{file ? file.name : "Choose a video file"}</span>
          <small className="faint">{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : "MP4, MKV, MOV…"}</small>
          <input type="file" accept="video/*" disabled={busy} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        {busy && (
          <div className="ui-meter" aria-hidden="true">
            <span className="ui-meter__fill" style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} />
          </div>
        )}
        <Field label="Department" htmlFor="up-dept">
          <Select id="up-dept" value={department} onChange={(e) => setDepartment(e.target.value)} disabled={busy} required>
            {allowed.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </Select>
        </Field>
        <div className="ui-grid-2">
          <Field label="Camera ID" hint="Optional" htmlFor="up-cam">
            <Input id="up-cam" value={cameraId} onChange={(e) => setCameraId(e.target.value)} disabled={busy} placeholder="cam11" />
          </Field>
          <Field label="Location" hint="If it isn't a registered camera" htmlFor="up-loc">
            <Input id="up-loc" value={locationText} onChange={(e) => setLocationText(e.target.value)} disabled={busy} />
          </Field>
        </div>
        <Field label="Recorded at" hint="Without this, track times stay relative to the start of the file." htmlFor="up-at">
          <Input id="up-at" type="datetime-local" value={recordedAt} onChange={(e) => setRecordedAt(e.target.value)} disabled={busy} />
        </Field>
      </form>
    </Dialog>
  );
}
