import { useMemo, useState } from "react";
import { Circle, CircleMarker, MapContainer, Popup } from "react-leaflet";
import { Link } from "react-router-dom";

import { DarkTileLayer, DEFAULT_CENTER, MAP_COLORS } from "../../components/map/MapBase.jsx";
import { Toolbar } from "../../components/Page.jsx";
import { Checkbox, Select } from "../../components/ui.jsx";
import { usePageTitle } from "../../lib/hooks.js";
import { useCameras, useDepartments } from "../../lib/queries.js";
import styles from "./Registry.module.css";

const RADII = [100, 250, 500];

function healthColor(camera) {
  if (camera.is_live === true) return MAP_COLORS.live;
  if (camera.is_live === false || camera.transport_ok === "none") return MAP_COLORS.critical;
  return MAP_COLORS.unknown;
}

export default function CameraMapView() {
  usePageTitle("Registry · Map");
  const cameras = useCameras();
  const departments = useDepartments();
  const [department, setDepartment] = useState("");
  const [anpr, setAnpr] = useState("");
  const [live, setLive] = useState("");
  const [coverage, setCoverage] = useState(false);
  const [radius, setRadius] = useState(250);

  const filtered = useMemo(
    () =>
      (cameras.data ?? []).filter((camera) => {
        if (department && camera.department !== department) return false;
        if (anpr === "true" && camera.anpr_viable !== true) return false;
        if (anpr === "false" && camera.anpr_viable !== false) return false;
        if (live === "true" && camera.is_live !== true) return false;
        if (live === "false" && camera.is_live !== false) return false;
        return true;
      }),
    [cameras.data, department, anpr, live],
  );
  const placed = filtered.filter((camera) => camera.latitude != null && camera.longitude != null);
  const unplaced = filtered.filter((camera) => camera.latitude == null || camera.longitude == null);
  const ringed = placed.filter((camera) => camera.is_live === true);

  return (
    <>
      <Toolbar label="Map filters">
        <Select value={department} onChange={(e) => setDepartment(e.target.value)} aria-label="Department">
          <option value="">All departments</option>
          {(departments.data ?? []).map((item) => (
            <option key={item.name} value={item.name}>
              {item.name}
            </option>
          ))}
        </Select>
        <Select value={anpr} onChange={(e) => setAnpr(e.target.value)} aria-label="Plate reading">
          <option value="">Any survey result</option>
          <option value="true">Plate-readable</option>
          <option value="false">Not plate-readable</option>
        </Select>
        <Select value={live} onChange={(e) => setLive(e.target.value)} aria-label="Source status">
          <option value="">Any source status</option>
          <option value="true">Live</option>
          <option value="false">Offline</option>
        </Select>
        <Checkbox label="Indicative coverage" checked={coverage} onChange={(e) => setCoverage(e.target.checked)} />
        {coverage && (
          <Select size="sm" value={radius} onChange={(e) => setRadius(Number(e.target.value))} aria-label="Coverage radius" style={{ width: 110, minWidth: 0 }}>
            {RADII.map((value) => (
              <option key={value} value={value}>
                {value} m
              </option>
            ))}
          </Select>
        )}
      </Toolbar>

      <div className={styles.legendRow}>
        <span>
          <i style={{ background: MAP_COLORS.live }} /> live
        </span>
        <span>
          <i style={{ background: MAP_COLORS.critical }} /> offline or unreachable
        </span>
        <span>
          <i style={{ background: MAP_COLORS.unknown }} /> unknown
        </span>
        <span className="faint">
          {coverage ? `${ringed.length} live camera(s) with a ${radius} m planning ring — an approximation, not a measured field of view.` : "Coverage rings are planning approximations, not measured fields of view."}
        </span>
      </div>

      <div className={styles.mapLayout}>
        <MapContainer center={DEFAULT_CENTER} zoom={7} className={styles.bigMap}>
          <DarkTileLayer />
          {coverage &&
            ringed.map((camera) => (
              <Circle
                key={`${camera.camera_id}-ring`}
                center={[camera.latitude, camera.longitude]}
                radius={radius}
                interactive={false}
                pathOptions={{ color: MAP_COLORS.live, fillColor: MAP_COLORS.live, fillOpacity: 0.07, weight: 1 }}
              />
            ))}
          {placed.map((camera) => (
            <CircleMarker
              key={camera.camera_id}
              center={[camera.latitude, camera.longitude]}
              radius={7}
              pathOptions={{ color: "#0c100f", weight: 2, fillColor: healthColor(camera), fillOpacity: 0.95 }}
            >
              <Popup>
                <strong>{camera.name}</strong>
                {camera.location_text}
                <br />
                {camera.department ?? "No department"} · {camera.camera_type ?? "unknown type"}
                <br />
                Plates: {camera.anpr_viable === true ? "readable" : camera.anpr_viable === false ? "not readable" : "not surveyed"} · Geocode: {camera.geocode_confidence ?? "pending"}
                <br />
                <Link to={`/live/${encodeURIComponent(camera.camera_id)}`}>Open live view →</Link>
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>

        <aside className={`ui-card ${styles.unplaced}`}>
          <h3>
            Unplaced <span className="faint tabular">{unplaced.length}</span>
          </h3>
          {unplaced.length === 0 ? (
            <p className="faint">Every filtered camera has coordinates.</p>
          ) : (
            <ul>
              {unplaced.map((camera) => (
                <li key={camera.camera_id}>
                  <strong>{camera.name}</strong>
                  <span className="faint">
                    {camera.location_text} — {camera.geocode_confidence === "failed" ? "geocoding failed" : "not yet geocoded"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </>
  );
}
