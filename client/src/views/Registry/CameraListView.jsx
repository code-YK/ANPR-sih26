import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, LocateFixed, MapPin, Pencil, Plus, Radar, RefreshCw, Search, Upload } from "lucide-react";

import { API, api } from "../../api.js";
import { AnprBadge, GeocodeBadge, LiveBadge } from "../../components/Badge.jsx";
import { useToast } from "../../components/Toast.jsx";
import { canAccessDepartment, isDepartmentAdmin, isSuperAdmin, useAuth } from "../../context/AuthContext.jsx";
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
  const [busy, setBusy] = useState(null);
  const navigate = useNavigate();
  const showToast = useToast();

  const rows = cameras.filter((c) => {
    const needle = query.trim().toLowerCase();
    if (
      needle &&
      ![c.camera_id, c.name, c.location_text, c.department].some((value) =>
        value?.toLowerCase().includes(needle),
      )
    ) {
      return false;
    }
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
      showToast(
        `Synced: ${result.fetched} fetched, ${result.inserted} new, ${result.updated} updated`,
      );
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
      showToast(
        `Import: ${result.created} created, ${result.updated} updated, ${result.failed} failed (of ${result.total_rows})`,
      );
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

  // Both run for one camera and need only operator clearance on its
  // department (pipeline.py); the whole-registry variants stay super-admin.
  const canOperate = (c) => canAccessDepartment(user, c.department, "operator");

  async function probe(c) {
    setBusy(`probe:${c.camera_id}`);
    try {
      const result = await api(`/probe?camera_id=${encodeURIComponent(c.camera_id)}`, { method: "POST" });
      const row = result.results?.[0];
      showToast(
        row?.transport_ok && row.transport_ok !== "none"
          ? `${c.name}: reachable over ${row.transport_ok}${row.width ? ` · ${row.width}×${row.height}` : ""}`
          : `${c.name}: probe failed — ${row?.error ?? "no transport reachable"}`,
      );
      await refresh();
    } catch (err) {
      showToast("Probe failed: " + err.message);
    } finally {
      setBusy(null);
    }
  }

  async function regeocode(c) {
    setBusy(`geo:${c.camera_id}`);
    try {
      const result = await api(`/geocode?camera_id=${encodeURIComponent(c.camera_id)}&force=true`, { method: "POST" });
      const row = result.results?.[0];
      showToast(
        row?.latitude != null
          ? `${c.name}: located (${row.geocode_confidence}) at ${row.latitude.toFixed(5)}, ${row.longitude.toFixed(5)}`
          : `${c.name}: its location text could not be geocoded`,
      );
      await refresh();
    } catch (err) {
      showToast("Geocode failed: " + err.message);
    } finally {
      setBusy(null);
    }
  }

  function canEdit(c) {
    return superAdmin || (isDepartmentAdmin(user) && c.department === user.home_department);
  }

  return (
    <div className="registry-panel">
      <div className="registry-toolbar">
        <label className="registry-search">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search ID, name, location, department"
            aria-label="Search cameras"
          />
          <Search size={15} strokeWidth={2} aria-hidden="true" />
        </label>

        <select
          className="registry-select"
          value={dept}
          onChange={(e) => setDept(e.target.value)}
          aria-label="Department"
        >
          <option value="">All departments</option>
          {departments.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>

        <select
          className="registry-select"
          value={cameraType}
          onChange={(e) => setCameraType(e.target.value)}
          aria-label="Camera type"
        >
          <option value="">All types</option>
          <option value="fixed">Fixed</option>
          <option value="ptz">PTZ</option>
          <option value="analog">Analog</option>
          <option value="ip">IP</option>
        </select>

        <select
          className="registry-select"
          value={anpr}
          onChange={(e) => setAnpr(e.target.value)}
          aria-label="Survey result"
        >
          <option value="">Any survey result</option>
          <option value="true">Viable</option>
          <option value="false">Not viable</option>
          <option value="null">Not surveyed</option>
        </select>

        <select
          className="registry-select"
          value={live}
          onChange={(e) => setLive(e.target.value)}
          aria-label="Source status"
        >
          <option value="">Any source status</option>
          <option value="true">Live</option>
          <option value="false">Offline</option>
        </select>

        <div className="registry-toolbar-spacer" />

        <button type="button" className="secondary registry-tool-btn" onClick={() => exportRegistry("csv")}>
          CSV
        </button>
        <button type="button" className="secondary registry-tool-btn" onClick={() => exportRegistry("json")}>
          JSON
        </button>
        {superAdmin && (
          <label className="secondary registry-tool-btn registry-import-label">
            <Upload size={14} strokeWidth={2} />
            Import
            <input type="file" accept=".csv" hidden onChange={handleBulkImport} />
          </label>
        )}
      </div>

      <div className="registry-actions-row">
        {superAdmin && (
          <>
            <button type="button" className="secondary registry-tool-btn" onClick={handleResync}>
              <RefreshCw size={14} strokeWidth={2} />
              Sync catalogue
            </button>
            <button type="button" className="primary registry-add-btn" onClick={() => setCreating(true)}>
              <Plus size={16} strokeWidth={2.25} />
              Add camera
            </button>
          </>
        )}
      </div>

      <div className="registry-table-wrap">
        <table className="registry-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Camera</th>
              <th>Department</th>
              <th>Source</th>
              <th>Plate reading</th>
              <th>Location</th>
              <th>Transport</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.camera_id}>
                <td className="registry-td-num mono">{c.camera_number ?? "—"}</td>
                <td className="registry-td-camera">
                  <strong>{c.name}</strong>
                  <span>
                    {c.camera_id}
                    {c.location_text ? ` · ${c.location_text}` : ""}
                  </span>
                </td>
                <td>{c.department ?? "—"}</td>
                <td>
                  <LiveBadge value={c.is_live} />
                </td>
                <td>
                  <AnprBadge value={c.anpr_viable} />
                </td>
                <td>
                  <GeocodeBadge value={c.geocode_confidence} />
                </td>
                <td className="mono registry-td-transport">{c.transport_ok ?? "—"}</td>
                <td className="registry-td-actions">
                  <button
                    type="button"
                    className="registry-icon-btn"
                    title="Health"
                    aria-label={`Health ${c.name}`}
                    // In-app navigation onto this camera -- this was a full page
                    // load that dropped every live player and opened Health with
                    // nothing selected.
                    onClick={() => navigate(`/registry/health-history?camera=${encodeURIComponent(c.camera_id)}`)}
                  >
                    <Activity size={15} strokeWidth={2} />
                  </button>
                  <button
                    type="button"
                    className="registry-icon-btn"
                    title="Map"
                    aria-label={`Map ${c.name}`}
                    onClick={() => navigate("/registry/map")}
                  >
                    <MapPin size={15} strokeWidth={2} />
                  </button>
                  {canOperate(c) && (
                    <>
                      <button
                        type="button"
                        className="registry-icon-btn"
                        title="Probe stream now"
                        aria-label={`Probe ${c.name} now`}
                        disabled={busy === `probe:${c.camera_id}`}
                        onClick={() => probe(c)}
                      >
                        <Radar size={15} strokeWidth={2} />
                      </button>
                      <button
                        type="button"
                        className="registry-icon-btn"
                        title="Re-geocode from location"
                        aria-label={`Re-geocode ${c.name} from its location text`}
                        disabled={busy === `geo:${c.camera_id}`}
                        onClick={() => regeocode(c)}
                      >
                        <LocateFixed size={15} strokeWidth={2} />
                      </button>
                    </>
                  )}
                  {canEdit(c) && (
                    <button
                      type="button"
                      className="registry-icon-btn"
                      title="Edit"
                      aria-label={`Edit ${c.name}`}
                      onClick={() => setEditing(c)}
                    >
                      <Pencil size={15} strokeWidth={2} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="hint">
                  No cameras match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <EditCameraModal camera={editing} onClose={() => setEditing(null)} onSaved={refresh} />
      {superAdmin && (
        <CreateCameraModal open={creating} onClose={() => setCreating(false)} onCreated={refresh} />
      )}
    </div>
  );
}
