import { useState } from "react";

import { API, api } from "../../api.js";
import { AnprBadge, GeocodeBadge, LiveBadge, MetadataBadge } from "../../components/Badge.jsx";
import { useToast } from "../../components/Toast.jsx";
import { isDepartmentAdmin, isSuperAdmin, useAuth } from "../../context/AuthContext.jsx";
import { useCameras } from "../../context/CamerasContext.jsx";
import { useDepartments } from "../../context/DepartmentsContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import CreateCameraModal from "./CreateCameraModal.jsx";
import EditCameraModal from "./EditCameraModal.jsx";

export default function CameraListView() {
  usePageTitle("Registry");
  const { cameras, refresh } = useCameras();
  const { user } = useAuth();
  const { names: departments } = useDepartments();
  const superAdmin = isSuperAdmin(user);
  const [dept, setDept] = useState("");
  const [query, setQuery] = useState("");
  const [cameraType, setCameraType] = useState("");
  const [anpr, setAnpr] = useState("");
  const [live, setLive] = useState("");
  const [editing, setEditing] = useState(null);
  const [creating, setCreating] = useState(false);
  const showToast = useToast();

  const rows = cameras.filter((c) => {
    const needle = query.trim().toLowerCase();
    if (needle && ![c.camera_id, c.name, c.location_text, c.department].some((value) => value?.toLowerCase().includes(needle))) return false;
    if (dept && c.department !== dept) return false;
    if (cameraType && c.camera_type !== cameraType) return false;
    if (anpr === "true" && c.anpr_viable !== true) return false;
    if (anpr === "false" && c.anpr_viable !== false) return false;
    if (anpr === "null" && c.anpr_viable !== null) return false;
    if (live === "true" && c.is_live !== true) return false;
    if (live === "false" && c.is_live !== false) return false;
    return true;
  });

  async function handleResync() {
    showToast("Syncing catalogue…");
    try {
      const result = await api("/sync", { method: "POST" });
      showToast(`Synced: ${result.fetched} fetched, ${result.inserted} new, ${result.updated} updated`);
      await refresh();
    } catch (e) {
      showToast("Sync failed: " + e.message);
    }
  }

  async function handleBulkImport(e) {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const result = await api("/cameras/bulk", { method: "POST", body: fd });
      showToast(`Import: ${result.created} created, ${result.updated} updated, ${result.failed} failed (of ${result.total_rows})`);
      await refresh();
    } catch (err) {
      showToast("Import failed: " + err.message);
    }
    e.target.value = "";
  }

  function exportRegistry(format) {
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    if (dept) params.set("department", dept);
    if (cameraType) params.set("camera_type", cameraType);
    if (anpr) params.set("anpr_viable", anpr);
    if (live) params.set("is_live", live);
    params.set("format", format);
    window.location.assign(`${API}/cameras/export?${params.toString()}`);
  }

  return (
    <>
      <div className="toolbar">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search ID, name, location, department"
          aria-label="Search cameras"
          style={{ minWidth: 220 }}
        />
        <select value={dept} onChange={(e) => setDept(e.target.value)}>
          <option value="">All departments</option>
          {departments.map((d) => (
            <option key={d}>{d}</option>
          ))}
        </select>
        <select value={cameraType} onChange={(e) => setCameraType(e.target.value)}>
          <option value="">All camera types</option>
          <option value="fixed">Fixed</option>
          <option value="ptz">PTZ</option>
          <option value="analog">Analog</option>
          <option value="ip">IP</option>
        </select>
        <select value={anpr} onChange={(e) => setAnpr(e.target.value)}>
          <option value="">Any ANPR status</option>
          <option value="true">ANPR viable</option>
          <option value="false">Not ANPR viable</option>
          <option value="null">Not surveyed</option>
        </select>
        <select value={live} onChange={(e) => setLive(e.target.value)}>
          <option value="">Any live status</option>
          <option value="true">Live</option>
          <option value="false">Offline</option>
        </select>
        <button className="secondary" onClick={() => exportRegistry("csv")}>Export CSV</button>
        <button className="secondary" onClick={() => exportRegistry("json")}>Export JSON</button>
        <div className="spacer" />
        {superAdmin && (
          <>
            <label className="secondary" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              Bulk import CSV
              <input type="file" accept=".csv" style={{ display: "none" }} onChange={handleBulkImport} />
            </label>
            <button className="secondary" onClick={handleResync}>Re-sync catalogue</button>
            <button className="primary" onClick={() => setCreating(true)}>+ Add camera</button>
          </>
        )}
      </div>

      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Name</th>
            <th>Location</th>
            <th>Department</th>
            <th>Live</th>
            <th>ANPR viable</th>
            <th>Geocode</th>
            <th>Transport</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.camera_id}>
              <td>{c.camera_number}</td>
              <td>{c.name}</td>
              <td>{c.location_text}</td>
              <td>
                {c.department ?? "—"} <MetadataBadge camera={c} />
              </td>
              <td>
                <LiveBadge value={c.is_live} />
              </td>
              <td>
                <AnprBadge value={c.anpr_viable} />
              </td>
              <td>
                <GeocodeBadge value={c.geocode_confidence} />
              </td>
              <td>{c.transport_ok ?? "—"}</td>
              <td>
                {(superAdmin || (isDepartmentAdmin(user) && c.department === user.home_department)) && (
                  <button className="link-btn" onClick={() => setEditing(c)}>Edit</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <EditCameraModal camera={editing} onClose={() => setEditing(null)} onSaved={refresh} />
      {superAdmin && <CreateCameraModal open={creating} onClose={() => setCreating(false)} onCreated={refresh} />}
    </>
  );
}
