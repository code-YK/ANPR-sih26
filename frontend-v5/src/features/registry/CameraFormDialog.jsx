import { useEffect, useState } from "react";

import { useConfirm } from "../../components/Page.jsx";
import { Button, Dialog, Field, Input, Select, Textarea } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { isSuperAdmin } from "../../lib/permissions.js";
import { useDepartments } from "../../lib/queries.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { toast } from "../notifications/notificationStore.js";
import LocationPicker from "./LocationPicker.jsx";

const OWNERSHIPS = ["government", "private"];
const CAMERA_TYPES = ["fixed", "ptz", "analog", "ip"];

const CREATE_EMPTY = {
  name: "",
  location_text: "",
  rtsp_url: "",
  hls_url: "",
  webrtc_url: "",
  department: "",
  ownership: "",
  camera_type: "",
  connectivity: "",
  storage_location: "",
  retention_days: "",
  metadata_confidence: "",
  latitude: "",
  longitude: "",
};

const EDIT_FIELDS = [
  "department",
  "ownership",
  "camera_type",
  "connectivity",
  "storage_location",
  "retention_days",
  "metadata_confidence",
  "latitude",
  "longitude",
  "anpr_viable",
  "anpr_notes",
];

function toPayload(form, fields) {
  const payload = {};
  for (const key of fields) {
    const raw = form[key];
    if (raw === "" || raw == null) continue;
    if (key === "retention_days") payload[key] = parseInt(raw, 10);
    else if (key === "latitude" || key === "longitude") payload[key] = parseFloat(raw);
    else if (key === "anpr_viable") payload[key] = raw === "true";
    else payload[key] = raw;
  }
  return payload;
}

/**
 * Create (super admin) or edit (camera admin) a registry camera. Analytics
 * is deliberately not here: AI workers are started from a camera's AI
 * Inference panel and managed in Workspace.
 */
export default function CameraFormDialog({ open, camera, onClose, onSaved }) {
  const { user } = useAuth();
  const departments = useDepartments();
  const editing = Boolean(camera);
  const [form, setForm] = useState(CREATE_EMPTY);
  const [saving, setSaving] = useState(false);
  const [confirm, confirmDialog] = useConfirm();

  useEffect(() => {
    if (!open) return;
    if (camera) {
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
      });
    } else {
      setForm(CREATE_EMPTY);
    }
  }, [open, camera]);

  const set = (field, value) => setForm((current) => ({ ...current, [field]: value }));
  const setLatLng = (lat, lng) => setForm((current) => ({ ...current, latitude: lat.toFixed(6), longitude: lng.toFixed(6) }));

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    try {
      if (editing) {
        await api(`/cameras/${encodeURIComponent(camera.camera_id)}`, { method: "PUT", json: toPayload(form, EDIT_FIELDS) });
        toast(`${camera.name} saved`, { tone: "live" });
      } else {
        const created = await api("/cameras", { method: "POST", json: toPayload(form, Object.keys(CREATE_EMPTY)) });
        toast(`Added ${created.name}`, { tone: "live", detail: `Assigned ${created.camera_id}` });
      }
      await onSaved();
      onClose();
    } catch (error) {
      toast(editing ? "Couldn't save the camera" : "Couldn't add the camera", { tone: "critical", detail: error.message });
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    const ok = await confirm({
      title: `Delete ${camera.name}?`,
      body: "This only works for a camera with no sightings, alerts or analytics history. A camera that has been in real use should have its analytics stopped instead.",
      confirmLabel: "Delete camera",
      danger: true,
    });
    if (!ok) return;
    setSaving(true);
    try {
      await api(`/cameras/${encodeURIComponent(camera.camera_id)}`, { method: "DELETE" });
      toast(`${camera.name} deleted`, { tone: "live" });
      await onSaved();
      onClose();
    } catch (error) {
      toast("Couldn't delete the camera", { tone: "critical", detail: error.message });
    } finally {
      setSaving(false);
    }
  }

  const latitude = form.latitude === "" ? null : parseFloat(form.latitude);
  const longitude = form.longitude === "" ? null : parseFloat(form.longitude);

  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        busy={saving}
        wide
        title={editing ? `Edit ${camera.name}` : "Add a camera"}
        description={
          editing
            ? camera.location_text
            : "For a camera outside the catalogue. It gets a manual-N id so a catalogue sync can never overwrite it. Stream URLs can be added later."
        }
        footer={
          <>
            {editing && isSuperAdmin(user) && (
              <Button variant="danger" onClick={remove} disabled={saving} style={{ marginRight: "auto" }}>
                Delete camera
              </Button>
            )}
            <Button variant="ghost" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" form="camera-form" variant="primary" loading={saving}>
              {editing ? "Save changes" : "Add camera"}
            </Button>
          </>
        }
      >
        <form id="camera-form" onSubmit={submit} style={{ display: "grid", gap: 16 }}>
          {!editing && (
            <>
              <div className="ui-grid-2">
                <Field label="Name" htmlFor="cam-name">
                  <Input id="cam-name" required value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Chowk Junction Camera 2" />
                </Field>
                <Field label="Location" htmlFor="cam-location">
                  <Input id="cam-location" required value={form.location_text} onChange={(e) => set("location_text", e.target.value)} placeholder="Near Chowk Junction, Bhavnagar" />
                </Field>
              </div>
              <Field label="RTSP URL" hint="Optional. Never shown again after saving." htmlFor="cam-rtsp">
                <Input id="cam-rtsp" value={form.rtsp_url} onChange={(e) => set("rtsp_url", e.target.value)} placeholder="rtsp://…" />
              </Field>
              <div className="ui-grid-2">
                <Field label="HLS URL" htmlFor="cam-hls">
                  <Input id="cam-hls" value={form.hls_url} onChange={(e) => set("hls_url", e.target.value)} placeholder="https://…/index.m3u8" />
                </Field>
                <Field label="WebRTC URL" htmlFor="cam-webrtc">
                  <Input id="cam-webrtc" value={form.webrtc_url} onChange={(e) => set("webrtc_url", e.target.value)} placeholder="https://…/whep" />
                </Field>
              </div>
            </>
          )}

          <div className="ui-grid-2">
            <Field label="Department" htmlFor="cam-dept" hint={editing && !isSuperAdmin(user) ? "Only a super admin can reassign a camera." : undefined}>
              <Select id="cam-dept" value={form.department} disabled={editing && !isSuperAdmin(user)} onChange={(e) => set("department", e.target.value)}>
                <option value="">—</option>
                {(departments.data ?? []).map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Metadata confidence" htmlFor="cam-conf" hint="Inferred if department or ownership was guessed.">
              <Select id="cam-conf" value={form.metadata_confidence} onChange={(e) => set("metadata_confidence", e.target.value)}>
                <option value="">—</option>
                <option value="confirmed">confirmed</option>
                <option value="inferred">inferred</option>
              </Select>
            </Field>
          </div>
          <div className="ui-grid-2">
            <Field label="Ownership" htmlFor="cam-own">
              <Select id="cam-own" value={form.ownership} onChange={(e) => set("ownership", e.target.value)}>
                <option value="">—</option>
                {OWNERSHIPS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Camera type" htmlFor="cam-type">
              <Select id="cam-type" value={form.camera_type} onChange={(e) => set("camera_type", e.target.value)}>
                <option value="">—</option>
                {CAMERA_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="ui-grid-2">
            <Field label="Connectivity" htmlFor="cam-conn">
              <Input id="cam-conn" value={form.connectivity} onChange={(e) => set("connectivity", e.target.value)} placeholder="fibre, 4G, unknown" />
            </Field>
            <Field label="Retention (days)" htmlFor="cam-ret">
              <Input id="cam-ret" type="number" min="0" value={form.retention_days} onChange={(e) => set("retention_days", e.target.value)} />
            </Field>
          </div>
          <Field label="Storage location" htmlFor="cam-store">
            <Input id="cam-store" value={form.storage_location} onChange={(e) => set("storage_location", e.target.value)} placeholder="Where footage actually lives" />
          </Field>

          {editing && (
            <div className="ui-grid-2">
              <Field label="Plate reading survey" htmlFor="cam-anpr">
                <Select id="cam-anpr" value={form.anpr_viable} onChange={(e) => set("anpr_viable", e.target.value)}>
                  <option value="">Not surveyed</option>
                  <option value="true">Plates readable</option>
                  <option value="false">Plates not readable</option>
                </Select>
              </Field>
              <Field label="Survey notes" htmlFor="cam-notes">
                <Textarea id="cam-notes" rows={1} value={form.anpr_notes} onChange={(e) => set("anpr_notes", e.target.value)} placeholder="Night IR blur, plate too few pixels…" />
              </Field>
            </div>
          )}

          <div className="ui-grid-2">
            <Field label="Latitude" htmlFor="cam-lat">
              <Input id="cam-lat" type="number" step="0.000001" value={form.latitude} onChange={(e) => set("latitude", e.target.value)} />
            </Field>
            <Field label="Longitude" htmlFor="cam-lng">
              <Input id="cam-lng" type="number" step="0.000001" value={form.longitude} onChange={(e) => set("longitude", e.target.value)} />
            </Field>
          </div>
          {open && <LocationPicker latitude={latitude} longitude={longitude} onChange={setLatLng} />}
        </form>
      </Dialog>
      {confirmDialog}
    </>
  );
}
