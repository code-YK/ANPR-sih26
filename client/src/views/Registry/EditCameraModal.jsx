import { useEffect, useState } from "react";

import { api } from "../../api.js";
import LocationPicker from "../../components/LocationPicker.jsx";
import { useConfirm } from "../../components/ConfirmDialog.jsx";
import Modal from "../../components/Modal.jsx";
import { useToast } from "../../components/Toast.jsx";
import { isSuperAdmin, useAuth } from "../../context/AuthContext.jsx";
import { useDepartments } from "../../context/DepartmentsContext.jsx";
import { CAMERA_TYPES, OWNERSHIPS } from "./constants.js";

const emptyForm = {
  department: "", ownership: "", camera_type: "", connectivity: "", storage_location: "",
  retention_days: "", metadata_confidence: "", latitude: "", longitude: "",
  anpr_viable: "", anpr_notes: "", analytics_enabled: false,
};

export default function EditCameraModal({ camera, onClose, onSaved }) {
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const showToast = useToast();
  const [confirm, confirmDialog] = useConfirm();
  const { user } = useAuth();
  const { names: departments } = useDepartments();

  useEffect(() => {
    if (!camera) return;
    setForm({
      department: camera.department ?? "",
      ownership: camera.ownership ?? "",
      camera_type: camera.camera_type ?? "",
      connectivity: camera.connectivity ?? "",
      storage_location: camera.storage_location ?? "",
      retention_days: camera.retention_days ?? "",
      metadata_confidence: camera.metadata_confidence ?? "",
      latitude: camera.latitude ?? "",
      longitude: camera.longitude ?? "",
      anpr_viable: camera.anpr_viable === true ? "true" : camera.anpr_viable === false ? "false" : "",
      anpr_notes: camera.anpr_notes ?? "",
      analytics_enabled: camera.analytics_enabled,
    });
  }, [camera]);

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function setLatLng(lat, lng) {
    setForm((f) => ({ ...f, latitude: lat.toFixed(6), longitude: lng.toFixed(6) }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const payload = {};
    for (const [key, raw] of Object.entries(form)) {
      if (raw === "") continue;
      if (key === "retention_days") payload[key] = parseInt(raw, 10);
      else if (key === "latitude" || key === "longitude") payload[key] = parseFloat(raw);
      else if (key === "anpr_viable") payload[key] = raw === "true";
      else payload[key] = raw;
    }
    setSaving(true);
    try {
      await api(`/cameras/${camera.camera_id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      showToast("Saved");
      onClose();
      await onSaved();
    } catch (err) {
      showToast("Save failed: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    const ok = await confirm({
      title: `Delete camera "${camera.name}"?`,
      body: `${camera.camera_id} is removed from the registry. This only works if it has no sightings, alerts, or analytics history on record.`,
      confirmLabel: "Delete camera",
      danger: true,
    });
    if (!ok) return;
    setDeleting(true);
    try {
      await api(`/cameras/${camera.camera_id}`, { method: "DELETE" });
      showToast("Camera deleted");
      onClose();
      await onSaved();
    } catch (err) {
      showToast("Delete failed: " + err.message);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Modal open={!!camera} onClose={onClose}>
      {camera && (
        <>
          <h2>
            Edit — {camera.name} ({camera.location_text})
          </h2>
          <form onSubmit={handleSubmit}>
            <div className="field">
              <label>Department</label>
              <select disabled={!isSuperAdmin(user)} value={form.department} onChange={(e) => set("department", e.target.value)}>
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
              <input
                value={form.connectivity}
                onChange={(e) => set("connectivity", e.target.value)}
                placeholder="e.g. fiber, 4G, unknown"
              />
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
              <input
                type="number"
                min="0"
                value={form.retention_days}
                onChange={(e) => set("retention_days", e.target.value)}
              />
            </div>
            <div className="field">
              <label>Metadata confidence</label>
              <select value={form.metadata_confidence} onChange={(e) => set("metadata_confidence", e.target.value)}>
                <option value="">—</option>
                <option value="confirmed">confirmed</option>
                <option value="inferred">inferred</option>
              </select>
              <div className="hint">
                Set "inferred" if department/ownership was guessed from the location name rather than a real source.
              </div>
            </div>
            <div className="row2">
              <div className="field">
                <label>Latitude (manual override)</label>
                <input
                  type="number"
                  step="0.000001"
                  value={form.latitude}
                  onChange={(e) => set("latitude", e.target.value)}
                />
              </div>
              <div className="field">
                <label>Longitude (manual override)</label>
                <input
                  type="number"
                  step="0.000001"
                  value={form.longitude}
                  onChange={(e) => set("longitude", e.target.value)}
                />
              </div>
            </div>
            <div className="hint">
              Setting both lat/lng marks geocode confidence as "exact". Click the map or drag the pin to set them
              instead of typing.
            </div>
            <div className="field">
              <LocationPicker
                latitude={form.latitude === "" ? null : parseFloat(form.latitude)}
                longitude={form.longitude === "" ? null : parseFloat(form.longitude)}
                onChange={setLatLng}
              />
            </div>
            <div className="field">
              <label>ANPR viable</label>
              <select value={form.anpr_viable} onChange={(e) => set("anpr_viable", e.target.value)}>
                <option value="">— not surveyed —</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </div>
            <div className="field">
              <label>ANPR notes</label>
              <textarea
                rows={2}
                value={form.anpr_notes}
                onChange={(e) => set("anpr_notes", e.target.value)}
                placeholder="e.g. night IR motion blur, PTZ wide angle, plate too few pixels"
              />
            </div>
            <div className="field">
              <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  checked={form.analytics_enabled}
                  onChange={(e) => set("analytics_enabled", e.target.checked)}
                />
                Continuous ANPR monitoring
              </label>
              <div className="hint">
                Keeps a vehicle-mode analytics worker running on this camera automatically -- the supervisor
                starts/restarts it, up to the concurrency cap, ANPR-viable cameras first. This only sets the
                intent; it doesn't start anything itself.
              </div>
            </div>
            <div className="actions">
              {isSuperAdmin(user) && (
                <button
                  type="button"
                  className="link-btn danger"
                  onClick={handleDelete}
                  disabled={deleting || saving}
                  style={{ marginRight: "auto" }}
                >
                  Delete camera
                </button>
              )}
              <button type="button" className="secondary" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="primary" disabled={saving}>
                Save
              </button>
            </div>
          </form>
        </>
      )}
      {confirmDialog}
    </Modal>
  );
}
