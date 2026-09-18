import { useQueryClient } from "@tanstack/react-query";
import { Activity, Cctv, Download, MapPin, Pencil, Plus, RefreshCw, Search, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Toolbar } from "../../components/Page.jsx";
import { Button, EmptyState, IconButton, Input, Select, Skeleton } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { apiUrl } from "../../lib/api/media.js";
import { usePageTitle } from "../../lib/hooks.js";
import { canAdminCamera, canOperateCamera, isSuperAdmin } from "../../lib/permissions.js";
import { keys, useCameras, useDepartments } from "../../lib/queries.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { toast } from "../notifications/notificationStore.js";
import { GeocodeBadge, InferredMark, SourceLiveBadge, SurveyBadge } from "./badges.jsx";
import CameraFormDialog from "./CameraFormDialog.jsx";

export default function CameraListView() {
  usePageTitle("Registry");
  const { user } = useAuth();
  const superAdmin = isSuperAdmin(user);
  const queryClient = useQueryClient();
  const cameras = useCameras();
  const departments = useDepartments();
  const fileRef = useRef(null);

  const [query, setQuery] = useState("");
  const [department, setDepartment] = useState("");
  const [cameraType, setCameraType] = useState("");
  const [anpr, setAnpr] = useState("");
  const [live, setLive] = useState("");
  const [dialog, setDialog] = useState({ open: false, camera: null });
  const [busy, setBusy] = useState(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.cameras });

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (cameras.data ?? []).filter((camera) => {
      if (needle && ![camera.camera_id, camera.name, camera.location_text, camera.department].some((value) => value?.toLowerCase().includes(needle))) return false;
      if (department && camera.department !== department) return false;
      if (cameraType && camera.camera_type !== cameraType) return false;
      if (anpr === "true" && camera.anpr_viable !== true) return false;
      if (anpr === "false" && camera.anpr_viable !== false) return false;
      if (anpr === "null" && camera.anpr_viable != null) return false;
      if (live === "true" && camera.is_live !== true) return false;
      if (live === "false" && camera.is_live !== false) return false;
      return true;
    });
  }, [cameras.data, query, department, cameraType, anpr, live]);

  function exportUrl(format) {
    const params = new URLSearchParams({ format });
    if (query.trim()) params.set("q", query.trim());
    if (department) params.set("department", department);
    if (cameraType) params.set("camera_type", cameraType);
    if (anpr === "true" || anpr === "false") params.set("anpr_viable", anpr);
    if (live) params.set("is_live", live);
    return apiUrl(`/cameras/export?${params}`);
  }

  async function run(label, work) {
    setBusy(label);
    try {
      await work();
    } finally {
      setBusy(null);
    }
  }

  const resync = () =>
    run("sync", async () => {
      try {
        const result = await api("/sync", { method: "POST" });
        toast("Catalogue synced", { tone: "live", detail: `${result.fetched} fetched · ${result.inserted} new · ${result.updated} updated` });
        refresh();
      } catch (error) {
        toast("Catalogue sync failed", { tone: "critical", detail: error.message });
      }
    });

  const probe = (camera) =>
    run(`probe:${camera.camera_id}`, async () => {
      try {
        const result = await api(`/probe?camera_id=${encodeURIComponent(camera.camera_id)}`, { method: "POST" });
        const item = result.results?.[0];
        toast(`Probed ${camera.name}`, { tone: item?.transport_ok === "none" ? "critical" : "live", detail: item ? `Transport: ${item.transport_ok}` : undefined });
        refresh();
      } catch (error) {
        toast("Probe failed", { tone: "critical", detail: error.message });
      }
    });

  const geocode = (camera) =>
    run(`geo:${camera.camera_id}`, async () => {
      try {
        const result = await api(`/geocode?camera_id=${encodeURIComponent(camera.camera_id)}&force=true`, { method: "POST" });
        const item = result.results?.[0];
        toast(`Geocoded ${camera.name}`, { tone: item?.geocode_confidence === "failed" ? "critical" : "live", detail: item ? `Result: ${item.geocode_confidence}` : undefined });
        refresh();
      } catch (error) {
        toast("Geocoding failed", { tone: "critical", detail: error.message });
      }
    });

  async function bulkImport(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    try {
      const result = await api("/cameras/bulk", { method: "POST", body });
      toast("Registry import finished", {
        tone: result.failed ? "critical" : "live",
        detail: `${result.created} created · ${result.updated} updated · ${result.failed} failed of ${result.total_rows}`,
      });
      refresh();
    } catch (error) {
      toast("Import failed", { tone: "critical", detail: error.message });
    }
  }

  return (
    <>
      <Toolbar label="Registry filters">
        <div className="ui-search">
          <Search aria-hidden="true" />
          <Input type="search" placeholder="Search ID, name, location, department" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search cameras" />
        </div>
        <Select value={department} onChange={(e) => setDepartment(e.target.value)} aria-label="Department">
          <option value="">All departments</option>
          {(departments.data ?? []).map((item) => (
            <option key={item.name} value={item.name}>
              {item.name}
            </option>
          ))}
        </Select>
        <Select value={cameraType} onChange={(e) => setCameraType(e.target.value)} aria-label="Camera type">
          <option value="">All types</option>
          <option value="fixed">Fixed</option>
          <option value="ptz">PTZ</option>
          <option value="analog">Analog</option>
          <option value="ip">IP</option>
        </Select>
        <Select value={anpr} onChange={(e) => setAnpr(e.target.value)} aria-label="Plate reading survey">
          <option value="">Any survey result</option>
          <option value="true">Plate-readable</option>
          <option value="false">Not plate-readable</option>
          <option value="null">Not surveyed</option>
        </Select>
        <Select value={live} onChange={(e) => setLive(e.target.value)} aria-label="Source status">
          <option value="">Any source status</option>
          <option value="true">Live</option>
          <option value="false">Offline</option>
        </Select>
        <div style={{ flex: 1 }} />
        <a className="ui-btn ui-btn--ghost ui-btn--sm" href={exportUrl("csv")}>
          <Download aria-hidden="true" /> CSV
        </a>
        <a className="ui-btn ui-btn--ghost ui-btn--sm" href={exportUrl("json")}>
          <Download aria-hidden="true" /> JSON
        </a>
        {superAdmin && (
          <>
            <input ref={fileRef} type="file" accept=".csv" hidden onChange={bulkImport} />
            <Button size="sm" icon={<Upload />} onClick={() => fileRef.current?.click()}>
              Import
            </Button>
            <Button size="sm" icon={<RefreshCw />} loading={busy === "sync"} onClick={resync}>
              Sync catalogue
            </Button>
            <Button size="sm" variant="primary" icon={<Plus />} onClick={() => setDialog({ open: true, camera: null })}>
              Add camera
            </Button>
          </>
        )}
      </Toolbar>

      {cameras.isPending ? (
        <Skeleton height={360} />
      ) : rows.length === 0 ? (
        <div className="ui-card">
          <EmptyState icon={<Cctv />} title="No cameras match">
            Clear the filters, or onboard cameras with a catalogue sync or manual entry.
          </EmptyState>
        </div>
      ) : (
        <div className="ui-table-wrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th className="ui-table__num">#</th>
                <th>Camera</th>
                <th>Department</th>
                <th>Source</th>
                <th>Plate reading</th>
                <th>Location</th>
                <th>Transport</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((camera) => (
                <tr key={camera.camera_id}>
                  <td className="ui-table__num data faint">{camera.camera_number}</td>
                  <td>
                    <Link to={`/live/${encodeURIComponent(camera.camera_id)}`} className="ui-table__primary">
                      {camera.name}
                    </Link>
                    <span className="ui-table__secondary">
                      <span className="data">{camera.camera_id}</span> · {camera.location_text}
                    </span>
                  </td>
                  <td>
                    <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                      {camera.department ?? <span className="faint">—</span>}
                      <InferredMark camera={camera} />
                    </span>
                  </td>
                  <td>
                    <SourceLiveBadge value={camera.is_live} />
                  </td>
                  <td>
                    <SurveyBadge value={camera.anpr_viable} />
                  </td>
                  <td>
                    <GeocodeBadge value={camera.geocode_confidence} />
                  </td>
                  <td className="data">{camera.transport_ok ?? <span className="faint">—</span>}</td>
                  <td>
                    <div className="ui-table__actions">
                      {canOperateCamera(user, camera) && (
                        <>
                          <IconButton label="Probe stream now" size="sm" disabled={busy === `probe:${camera.camera_id}`} onClick={() => probe(camera)}>
                            <Activity />
                          </IconButton>
                          <IconButton label="Re-geocode from location" size="sm" disabled={busy === `geo:${camera.camera_id}`} onClick={() => geocode(camera)}>
                            <MapPin />
                          </IconButton>
                        </>
                      )}
                      {canAdminCamera(user, camera) && (
                        <IconButton label="Edit camera" size="sm" onClick={() => setDialog({ open: true, camera })}>
                          <Pencil />
                        </IconButton>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CameraFormDialog open={dialog.open} camera={dialog.camera} onClose={() => setDialog({ open: false, camera: null })} onSaved={refresh} />
    </>
  );
}
