import { useEffect, useRef, useState } from "react";

import { useCameras } from "../../context/CamerasContext.jsx";
import { useDepartments } from "../../context/DepartmentsContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import { ensureMapboxToken, mapboxgl, mapboxStyleUrl, useTheme } from "../../lib/mapbox.js";

const GUJARAT_CENTER = [71.6, 22.6]; // lng, lat
const COVERAGE_RADII = [100, 250, 500];

function healthColor(camera) {
  if (camera.is_live === true) return "#2fc67f";
  if (camera.is_live === false || camera.transport_ok === "none") return "#ef4f43";
  return "#7a7a7a";
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export default function MapView() {
  usePageTitle("Registry · GIS map");
  const { cameras } = useCameras();
  const { names: departments } = useDepartments();
  const { isLight } = useTheme();
  const hasToken = ensureMapboxToken();

  const [dept, setDept] = useState("");
  const [cameraType, setCameraType] = useState("");
  const [anpr, setAnpr] = useState("");
  const [live, setLive] = useState("");
  const [showCoverage, setShowCoverage] = useState(false);
  const [coverageRadius, setCoverageRadius] = useState(250);

  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef([]);

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
  const coverageCandidates = placed.filter((c) => c.is_live === true);

  useEffect(() => {
    if (!mapContainerRef.current || !hasToken) return undefined;

    const map = new mapboxgl.Map({
      container: mapContainerRef.current,
      style: mapboxStyleUrl(isLight),
      center: GUJARAT_CENTER,
      zoom: 7,
      attributionControl: true,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    return () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, [hasToken, isLight]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !hasToken) return undefined;

    const paint = () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];

      for (const id of ["coverage-fill", "coverage-outline", "cameras-circle", "cameras-stroke"]) {
        if (map.getLayer(id)) map.removeLayer(id);
      }
      for (const id of ["coverage", "cameras"]) {
        if (map.getSource(id)) map.removeSource(id);
      }

      if (showCoverage && coverageCandidates.length > 0) {
        // Approximate rings as GeoJSON circles (64 steps)
        const features = coverageCandidates.map((c) => ({
          type: "Feature",
          geometry: {
            type: "Polygon",
            coordinates: [circlePolygon(c.longitude, c.latitude, coverageRadius)],
          },
          properties: { id: c.camera_id },
        }));
        map.addSource("coverage", {
          type: "geojson",
          data: { type: "FeatureCollection", features },
        });
        map.addLayer({
          id: "coverage-fill",
          type: "fill",
          source: "coverage",
          paint: { "fill-color": "#2fc67f", "fill-opacity": 0.08 },
        });
        map.addLayer({
          id: "coverage-outline",
          type: "line",
          source: "coverage",
          paint: { "line-color": "#2fc67f", "line-width": 1, "line-opacity": 0.5 },
        });
      }

      map.addSource("cameras", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: placed.map((c) => ({
            type: "Feature",
            geometry: { type: "Point", coordinates: [c.longitude, c.latitude] },
            properties: {
              id: c.camera_id,
              name: c.name,
              color: healthColor(c),
              location: c.location_text || "",
              department: c.department || "—",
              type: c.camera_type || "unknown",
              anpr:
                c.anpr_viable === true
                  ? "viable"
                  : c.anpr_viable === false
                    ? "not viable"
                    : "not surveyed",
              health:
                c.is_live === true ? "live" : c.is_live === false ? "offline" : "unknown",
              geocode: c.geocode_confidence || "pending",
            },
          })),
        },
      });

      map.addLayer({
        id: "cameras-circle",
        type: "circle",
        source: "cameras",
        paint: {
          "circle-radius": 7,
          "circle-color": ["get", "color"],
          "circle-opacity": 0.85,
          "circle-stroke-width": 2,
          "circle-stroke-color": isLight ? "#ffffff" : "#0b1220",
        },
      });

      map.on("click", "cameras-circle", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties;
        new mapboxgl.Popup({ offset: 12 })
          .setLngLat(f.geometry.coordinates)
          .setHTML(
            `<strong>${escapeHtml(p.name)}</strong><br/>${escapeHtml(p.location)}<br/>
             Department: ${escapeHtml(p.department)}<br/>
             Type: ${escapeHtml(p.type)}<br/>
             ANPR: ${escapeHtml(p.anpr)}<br/>
             Health: ${escapeHtml(p.health)}<br/>
             Geocode: ${escapeHtml(p.geocode)}`,
          )
          .addTo(map);
      });

      map.on("mouseenter", "cameras-circle", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "cameras-circle", () => {
        map.getCanvas().style.cursor = "";
      });

      if (placed.length === 1) {
        map.easeTo({
          center: [placed[0].longitude, placed[0].latitude],
          zoom: 12,
          duration: 400,
        });
      } else if (placed.length > 1) {
        const bounds = placed.reduce(
          (b, c) => b.extend([c.longitude, c.latitude]),
          new mapboxgl.LngLatBounds(
            [placed[0].longitude, placed[0].latitude],
            [placed[0].longitude, placed[0].latitude],
          ),
        );
        map.fitBounds(bounds, { padding: 48, maxZoom: 12, duration: 400 });
      }
    };

    if (map.isStyleLoaded()) paint();
    else map.once("load", paint);

    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    hasToken,
    isLight,
    showCoverage,
    coverageRadius,
    placed.map((c) => c.camera_id).join(","),
  ]);

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
            {COVERAGE_RADII.map((radius) => (
              <option key={radius} value={radius}>
                {radius} m radius
              </option>
            ))}
          </select>
        )}
      </div>
      <p className="map-note">
        Marker colour: green live, red offline/unreachable, grey unknown.{" "}
        {showCoverage
          ? `${coverageCandidates.length} live, geocoded camera(s) have a ${coverageRadius} m planning ring; it is not a measured field of view.`
          : "Coverage rings are optional planning approximations, not measured fields of view."}
      </p>
      <div className="map-layout">
        {hasToken ? (
          <div ref={mapContainerRef} id="map" className="registry-mapbox" />
        ) : (
          <div id="map" className="registry-mapbox mapbox-missing">
            Set <code>VITE_MAPBOX_TOKEN</code> to load the registry map.
          </div>
        )}
        <details className="unplaced-panel" open>
          <summary>Unplaced cameras</summary>
          {unplaced.length === 0 ? (
            <div className="cam-row loc">None — every filtered camera is placed.</div>
          ) : (
            unplaced.map((c) => (
              <div className="cam-row" key={c.camera_id}>
                <strong>{c.name}</strong>
                <div className="loc">
                  {c.location_text} —{" "}
                  {c.geocode_confidence === "failed" ? "geocode failed" : "not yet geocoded"}
                </div>
              </div>
            ))
          )}
        </details>
      </div>
    </>
  );
}

/** Approximate a circle in lon/lat for a radius in metres. */
function circlePolygon(lng, lat, radiusM, steps = 64) {
  const coords = [];
  const latRad = (lat * Math.PI) / 180;
  const mPerDegLat = 111320;
  const mPerDegLng = 111320 * Math.cos(latRad);
  for (let i = 0; i <= steps; i += 1) {
    const theta = (i / steps) * Math.PI * 2;
    const dx = (radiusM * Math.cos(theta)) / mPerDegLng;
    const dy = (radiusM * Math.sin(theta)) / mPerDegLat;
    coords.push([lng + dx, lat + dy]);
  }
  return coords;
}
