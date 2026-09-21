import { useState } from "react";

import { api } from "../../api.js";
import LocationPicker from "../../components/LocationPicker.jsx";
import Modal from "../../components/Modal.jsx";
import { useToast } from "../../components/Toast.jsx";
import { useDepartments } from "../../context/DepartmentsContext.jsx";
import { CAMERA_TYPES, OWNERSHIPS } from "./constants.js";

const emptyForm = {
  name: "", location_text: "", rtsp_url: "", hls_url: "", webrtc_url: "",
  department: "", ownership: "", camera_type: "", connectivity: "", storage_location: "",
  retention_days: "", metadata_confidence: "", latitude: "", longitude: "",
};

export default function CreateCameraModal({ open, onClose, onCreated }) {
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const showToast = useToast();
  const { names: departments } = useDepartments();

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function setLatLng(lat, lng) {
    setForm((f) => ({ ...f, latitude: lat.toFixed(6), longitude: lng.toFixed(6) }));
  }

  function close() {
    setForm(emptyForm);
    onClose();
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const payload = {};
    for (const [key, raw] of Object.entries(form)) {
      if (raw === "") continue;
      if (key === "retention_days") payload[key] = parseInt(raw, 10);
      else if (key === "latitude" || key === "longitude") payload[key] = parseFloat(raw);
      else payload[key] = raw;
    }
    setSaving(true);
    try {
      const created = await api("/cameras", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      showToast(`Added ${created.camera_id} (#${created.camera_number})`);
      close();
      await onCreated();
    } catch (err) {
      showToast("Add camera failed: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={close}>
      <h2>Add camera manually</h2>
      <div className="hint" style={{ marginBottom: 14 }}>
        For a camera that isn't in the sandbox catalogue. It's assigned an id like <code>manual-1</code> so a future
        catalogue sync can never collide with or overwrite it. A stream URL is optional — you can register the
        camera now and add RTSP/HLS/WebRTC later via Edit.
      </div>
      <form onSubmit={handleSubmit}>
        <div className="field">
          <label>Name *</label>
          <input required value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Chowk Junction Camera 2" />
        </div>
        <div className="field">
          <label>Location *</label>
          <input
            required
            value={form.location_text}
            onChange={(e) => set("location_text", e.target.value)}
            placeholder="e.g. Near Chowk Junction, Bhavnagar"
          />
        </div>
        <div className="field">
          <label>
            RTSP URL <span className="hint" style={{ display: "inline" }}>(optional)</span>
          </label>
          <input value={form.rtsp_url} onChange={(e) => set("rtsp_url", e.target.value)} placeholder="rtsp://..." />
        </div>
        <div className="row2">
          <div className="field">
            <label>
              HLS URL <span className="hint" style={{ display: "inline" }}>(optional)</span>
            </label>
            <input value={form.hls_url} onChange={(e) => set("hls_url", e.target.value)} placeholder="https://.../index.m3u8" />
          </div>
          <div className="field">
            <label>
              WebRTC URL <span className="hint" style={{ display: "inline" }}>(optional)</span>
            </label>
            <input value={form.webrtc_url} onChange={(e) => set("webrtc_url", e.target.value)} placeholder="https://.../whep" />
          </div>
        </div>
        <div className="field">
          <label>Department</label>
          <select value={form.department} onChange={(e) => set("department", e.target.value)}>
            <option value="">—</option>
            {departments.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </div>
        <div className="row2">
          <div className="field">
            <label>Ownership</label>
            <select value={form.ownership} onChange={(e) => set("ownership", e.target.value)}>
              <option value="">—</option>
              {OWNERSHIPS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Camera type</label>
            <select value={form.camera_type} onChange={(e) => set("camera_type", e.target.value)}>
              <option value="">—</option>
              {CAMERA_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label>Connectivity</label>
          <input value={form.connectivity} onChange={(e) => set("connectivity", e.target.value)} placeholder="e.g. fiber, 4G, unknown" />
        </div>
        <div className="field">
          <label>Storage location</label>
          <input
            value={form.storage_location}
            onChange={(e) => set("storage_location", e.target.value)}
            placeholder="where footage actually lives"
          />
        </div>
        <div className="field">
          <label>Retention (days)</label>
          <input type="number" min="0" value={form.retention_days} onChange={(e) => set("retention_days", e.target.value)} />
        </div>
        <div className="field">
          <label>Metadata confidence</label>
          <select value={form.metadata_confidence} onChange={(e) => set("metadata_confidence", e.target.value)}>
            <option value="">—</option>
            <option value="confirmed">confirmed</option>
            <option value="inferred">inferred</option>
          </select>
          <div className="hint">Set "inferred" if department/ownership was guessed rather than a real source.</div>
        </div>
        <div className="row2">
          <div className="field">
            <label>Latitude</label>
            <input type="number" step="0.000001" value={form.latitude} onChange={(e) => set("latitude", e.target.value)} />
          </div>
          <div className="field">
            <label>Longitude</label>
            <input type="number" step="0.000001" value={form.longitude} onChange={(e) => set("longitude", e.target.value)} />
          </div>
        </div>
        <div className="hint">
          Setting both lat/lng marks geocode confidence as "exact". Click the map or drag the pin to set them instead
          of typing.
        </div>
        <div className="field">
          <LocationPicker
            latitude={form.latitude === "" ? null : parseFloat(form.latitude)}
            longitude={form.longitude === "" ? null : parseFloat(form.longitude)}
            onChange={setLatLng}
          />
        </div>
        <div className="actions">
          <button type="button" className="secondary" onClick={close}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={saving}>
            Add camera
          </button>
        </div>
      </form>
    </Modal>
  );
}
