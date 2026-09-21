import { useEffect, useRef } from "react";

import { ensureMapboxToken, mapboxgl, mapboxStyleUrl, useTheme } from "../lib/mapbox.js";

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export default function RouteMap({ stops, hoveredIndex, onHover }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef([]);
  const { isLight } = useTheme();
  const hasToken = ensureMapboxToken();

  const placed = stops
    .map((s, i) => ({ ...s, _index: i }))
    .filter((s) => s.latitude != null && s.longitude != null);
  const positionsKey = placed.map((s) => `${s.longitude},${s.latitude}`).join("|");

  useEffect(() => {
    if (!containerRef.current || !hasToken) return undefined;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: mapboxStyleUrl(isLight),
      center: [71.6, 22.6],
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

    const apply = () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];

      if (map.getLayer("route-line")) map.removeLayer("route-line");
      if (map.getSource("route-line")) map.removeSource("route-line");

      const positions = placed.map((s) => [s.longitude, s.latitude]);

      if (positions.length > 1) {
        map.addSource("route-line", {
          type: "geojson",
          data: {
            type: "Feature",
            geometry: { type: "LineString", coordinates: positions },
          },
        });
        map.addLayer({
          id: "route-line",
          type: "line",
          source: "route-line",
          paint: {
            "line-color": isLight ? "#1d6fd8" : "#5eb0ff",
            "line-width": 3.5,
            "line-opacity": 0.9,
          },
        });
      }

      placed.forEach((s, i) => {
        const el = document.createElement("div");
        el.className = `route-marker${hoveredIndex === s._index ? " route-marker-active" : ""}`;
        el.innerHTML = `<div class="route-marker-inner">${i + 1}</div>`;
        el.addEventListener("mouseenter", () => onHover?.(s._index));
        el.addEventListener("mouseleave", () => onHover?.(null));

        const conf =
          s.confidence != null && Number.isFinite(Number(s.confidence))
            ? Number(s.confidence).toFixed(2)
            : null;
        const when = new Date(s.seen_at);
        const whenLabel = Number.isNaN(when.getTime())
          ? "—"
          : when.toLocaleString(undefined, {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            });
        const popup = new mapboxgl.Popup({
          offset: 18,
          closeButton: true,
          className: "journey-map-popup",
          maxWidth: "300px",
        }).setHTML(
          `<div class="jmp">
            <div class="jmp-head">
              <span class="jmp-step">${i + 1}</span>
              <div class="jmp-head-text">
                <strong class="jmp-title">${escapeHtml(s.camera_name || "Camera")}</strong>
                <span class="jmp-dept">${escapeHtml(s.department || "Sighting")}</span>
              </div>
            </div>
            <p class="jmp-loc">${escapeHtml(s.location_text || "Location unknown")}</p>
            <div class="jmp-meta">
              <span class="jmp-time">${escapeHtml(whenLabel)}</span>
              ${conf != null ? `<span class="jmp-conf">conf ${conf}</span>` : ""}
            </div>
          </div>`,
        );

        const marker = new mapboxgl.Marker({ element: el })
          .setLngLat([s.longitude, s.latitude])
          .setPopup(popup)
          .addTo(map);
        markersRef.current.push(marker);
      });

      if (positions.length === 1) {
        map.easeTo({ center: positions[0], zoom: 14, duration: 400 });
      } else if (positions.length > 1) {
        const bounds = positions.reduce(
          (b, p) => b.extend(p),
          new mapboxgl.LngLatBounds(positions[0], positions[0]),
        );
        map.fitBounds(bounds, { padding: 40, duration: 400 });
      }
    };

    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);

    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [positionsKey, hasToken, isLight]);

  useEffect(() => {
    markersRef.current.forEach((marker, i) => {
      const el = marker.getElement();
      const stop = placed[i];
      if (!el || !stop) return;
      el.classList.toggle("route-marker-active", hoveredIndex === stop._index);
    });
  }, [hoveredIndex, placed]);

  if (!hasToken) {
    return (
      <div className="route-map mapbox-missing">
        Set <code>VITE_MAPBOX_TOKEN</code> to show the journey map.
      </div>
    );
  }

  return <div ref={containerRef} className="route-map" />;
}
