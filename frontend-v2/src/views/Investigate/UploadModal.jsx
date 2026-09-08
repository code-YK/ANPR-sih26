import { useState } from "react";

import { API } from "../../api.js";
import Modal from "../../components/Modal.jsx";
import { useToast } from "../../components/Toast.jsx";
import { useAuth } from "../../context/AuthContext.jsx";
import { useDepartments } from "../../context/DepartmentsContext.jsx";

// Upload is a multipart POST with plain query-param fields (not a JSON
// body) on the backend, and it can take a while (streamed to disk, hashed,
// then an ffmpeg normalisation pass) -- so this uses fetch directly rather
// than the api() helper, which has no upload-progress hook and would
// otherwise leave the operator staring at a static "Uploading..." for
// however long normalisation takes with no sense of what's happening.
export default function UploadModal({ open, onClose, onUploaded }) {
  const { user } = useAuth();
  const { names: departmentNames } = useDepartments();
  const showToast = useToast();

  const [file, setFile] = useState(null);
  const [department, setDepartment] = useState(user?.home_department || departmentNames[0] || "");
  const [cameraId, setCameraId] = useState("");
  const [locationText, setLocationText] = useState("");
  const [recordedAt, setRecordedAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");

  function reset() {
    setFile(null);
    setStage("");
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!file || !department) {
      showToast("Choose a file and a department first");
      return;
    }
    setBusy(true);
    setStage("Uploading…");
    try {
      const params = new URLSearchParams({ department });
      if (cameraId) params.set("camera_id", cameraId);
      if (locationText) params.set("location_text", locationText);
      if (recordedAt) params.set("recorded_at", new Date(recordedAt).toISOString());

      const form = new FormData();
      form.append("file", file);

      const resp = await fetch(`${API}/investigate/recordings?${params.toString()}`, {
        method: "POST",
        credentials: "same-origin",
        body: form,
      });
      if (!resp.ok) {
        let detail = resp.statusText;
        try {
          detail = JSON.stringify((await resp.json()).detail);
        } catch {
          // not JSON
        }
        throw new Error(`${resp.status}: ${detail}`);
      }
      setStage("Normalising for playback…");
      const recording = await resp.json();
      showToast(
        recording.status === "ready"
          ? "Uploaded and ready"
          : recording.status === "rejected"
            ? `Upload rejected: ${recording.reject_reason}`
            : `Recording is ${recording.status}`,
      );
      onUploaded(recording);
      reset();
      onClose();
    } catch (err) {
      showToast("Upload failed: " + err.message);
    } finally {
      setBusy(false);
      setStage("");
    }
  }

  return (
    <Modal open={open} onClose={busy ? () => {} : onClose}>
      <h2>Upload a recording</h2>
      <form onSubmit={handleSubmit}>
        <div className="field">
          <label>Video file</label>
          <input
            type="file"
            accept="video/*"
            onChange={(e) => setFile(e.target.files[0] || null)}
            disabled={busy}
          />
        </div>
        <div className="field">
          <label>Department</label>
          <select value={department} onChange={(e) => setDepartment(e.target.value)} disabled={busy}>
            {departmentNames.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
        <div className="row2">
          <div className="field">
            <label>Camera ID (optional)</label>
            <input value={cameraId} onChange={(e) => setCameraId(e.target.value)} disabled={busy} placeholder="e.g. 12" />
          </div>
          <div className="field">
            <label>Location (optional)</label>
            <input value={locationText} onChange={(e) => setLocationText(e.target.value)} disabled={busy} placeholder="if no known camera" />
          </div>
        </div>
        <div className="field">
          <label>Recorded at (optional)</label>
          <input
            type="datetime-local"
            value={recordedAt}
            onChange={(e) => setRecordedAt(e.target.value)}
            disabled={busy}
          />
          <p className="hint">
            Without this, timestamps stay relative to the recording's own start rather than a real
            wall-clock time -- the same honesty rule the live ANPR path applies to an unanchored stream.
          </p>
        </div>
        <div className="actions">
          <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="primary" disabled={busy || !file}>
            {busy ? stage || "Working…" : "Upload"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
