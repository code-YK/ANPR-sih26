import { useState } from "react";
import { Circle, CircleMarker, MapContainer, Popup } from "react-leaflet";

import DarkTileLayer from "../../components/DarkTileLayer.jsx";
import { useCameras } from "../../context/CamerasContext.jsx";
import { useDepartments } from "../../context/DepartmentsContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";

const GUJARAT_CENTER = [22.6, 71.6];

// Leaflet draws these as canvas/SVG fills, outside the CSS cascade, so they
// can't reference token custom properties. Marker colour is deliberately a
// current health signal, not a claim about ANPR capability or coverage.
function healthColor(camera) {
  if (camera.is_live === true) return "#2fc67f";
  if (camera.is_live === false || camera.transport_ok === "none") return "#ef4f43";
  return "#7a7a7a";
}

const COVERAGE_RADII = [100, 250, 500];

export default function MapView() {
  usePageTitle("Registry · GIS map");
  const { cameras } = useCameras();
  const { names: departments } = useDepartments();
  const [dept, setDept] = useState("");
  const [cameraType, setCameraType] = useState("");
  const [anpr, setAnpr] = useState("");
  const [live, setLive] = useState("");
  const [showCoverage, setShowCoverage] = useState(false);
  const [coverageRadius, setCoverageRadius] = useState(250);

  const filtered = cameras.filter((c) => {
    if (dept && c.department !== dept) return false;
    if (cameraType && c.camera_type !== cameraType) return false;
    if (anpr === "true" && c.anpr_viable !== true) return false;
    if (anpr === "false" && c.anpr_viable !== false) return false;
    if (live === "true" && c.is_live !== true) return false;
    if (live === "false" && c.is_live !== false) return false;
    return true;
  });

  const placed = filtered.filter((c) => c.latitude != null && c.longitude != null);
  const unplaced = filtered.filter((c) => c.latitude == null || c.longitude == null);
  // No camera field-of-view or mounting-height metadata exists yet, so only
  // currently-live cameras receive an optional planning ring. The label and
  // popup make clear this is an operator-selected approximation, never a
  // measured surveillance footprint.
  const coverageCandidates = placed.filter((c) => c.is_live === true);

  return (
    <>
      <div className="toolbar">
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
        </select>
        <select value={live} onChange={(e) => setLive(e.target.value)}>
          <option value="">Any live status</option>
          <option value="true">Live</option>
          <option value="false">Offline</option>
        </select>
        <label className="coverage-toggle">
          <input
            type="checkbox"
            checked={showCoverage}
            onChange={(e) => setShowCoverage(e.target.checked)}
          />
          Indicative coverage
        </label>
        {showCoverage && (
          <select
            aria-label="Indicative coverage radius"
            value={coverageRadius}
            onChange={(e) => setCoverageRadius(Number(e.target.value))}
          >
            {COVERAGE_RADII.map((radius) => <option key={radius} value={radius}>{radius} m radius</option>)}
          </select>
        )}
      </div>
      <p className="map-note">
        Marker colour: green live, red offline/unreachable, grey unknown. {showCoverage
          ? `${coverageCandidates.length} live, geocoded camera(s) have a ${coverageRadius} m planning ring; it is not a measured field of view.`
          : "Coverage rings are optional planning approximations, not measured fields of view."}
      </p>
      <div className="map-layout">
        <MapContainer center={GUJARAT_CENTER} zoom={7} id="map">
          <DarkTileLayer />
          {showCoverage && coverageCandidates.map((c) => (
            <Circle
              key={`${c.camera_id}-coverage`}
              center={[c.latitude, c.longitude]}
              radius={coverageRadius}
              interactive={false}
              pathOptions={{ color: "#2fc67f", fillColor: "#2fc67f", fillOpacity: 0.08, weight: 1 }}
            />
          ))}
          {placed.map((c) => (
            <CircleMarker
              key={c.camera_id}
              center={[c.latitude, c.longitude]}
              radius={7}
              color={healthColor(c)}
              fillColor={healthColor(c)}
              fillOpacity={0.75}
              weight={2}
            >
              <Popup>
                <strong>{c.name}</strong>
                <br />
                {c.location_text}
                <br />
                Department: {c.department ?? "—"}
                <br />
                Type: {c.camera_type ?? "unknown"}
                <br />
                ANPR: {c.anpr_viable === true ? "viable" : c.anpr_viable === false ? "not viable" : "not surveyed"}
                <br />
                Health: {c.is_live === true ? "live" : c.is_live === false ? "offline" : "unknown"}
                <br />
                Geocode: {c.geocode_confidence ?? "pending"}
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>
        {/* <details>, not a div -- and open by default, so this behaves
            exactly as before (always visible) unless the operator chooses
            to collapse it. This is new capability, not a JS-toggle it
            replaced; the list had no collapse state previously. */}
        <details className="unplaced-panel" open>
          <summary>Unplaced cameras</summary>
          {unplaced.length === 0 ? (
            <div className="cam-row loc">None — every filtered camera is placed.</div>
          ) : (
            unplaced.map((c) => (
              <div className="cam-row" key={c.camera_id}>
                <strong>{c.name}</strong>
                <div className="loc">
                  {c.location_text} — {c.geocode_confidence === "failed" ? "geocode failed" : "not yet geocoded"}
                </div>
              </div>
            ))
          )}
        </details>
      </div>
    </>
  );
}
