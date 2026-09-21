import { useEffect, useRef } from "react";

import { ensureMapboxToken, mapboxgl, mapboxStyleUrl, useTheme } from "../../lib/mapbox.js";

const CENTER = [77.209, 28.6139];

const ROUTE_A = [
  [77.219, 28.632],
  [77.21, 28.625],
  [77.206, 28.618],
  [77.2, 28.61],
  [77.195, 28.602],
];

const ROUTE_B = [
  [77.19, 28.64],
  [77.2, 28.63],
  [77.215, 28.62],
  [77.225, 28.612],
];

const NODES = [
  [77.219, 28.632],
  [77.206, 28.618],
  [77.195, 28.602],
  [77.19, 28.64],
  [77.225, 28.612],
];

export default function LandingMap() {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const { isLight, accent } = useTheme();
  const tokenOk = ensureMapboxToken();

  useEffect(() => {
    if (!containerRef.current || !tokenOk) return undefined;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: mapboxStyleUrl(isLight),
      center: CENTER,
      zoom: 12.4,
      pitch: 48,
      bearing: -18,
      interactive: false,
      attributionControl: false,
      antialias: true,
    });
    mapRef.current = map;

    map.on("load", () => {
      if (!isLight) {
        try {
          map.setFog({
            color: "rgb(12, 18, 32)",
            "high-color": "rgb(36, 58, 98)",
            "horizon-blend": 0.08,
            "space-color": "rgb(8, 12, 24)",
            "star-intensity": 0.15,
          });
        } catch {
          /* ignore */
        }
      }

      map.addSource("route-a", {
        type: "geojson",
        data: { type: "Feature", geometry: { type: "LineString", coordinates: ROUTE_A } },
      });
      map.addSource("route-b", {
        type: "geojson",
        data: { type: "Feature", geometry: { type: "LineString", coordinates: ROUTE_B } },
      });
      map.addSource("nodes", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: NODES.map((c) => ({
            type: "Feature",
            geometry: { type: "Point", coordinates: c },
          })),
        },
      });

      const styles = getComputedStyle(document.documentElement);
      const lineColor = (styles.getPropertyValue("--entity-hex").trim()
        || styles.getPropertyValue("--entity-bright-hex").trim()
        || (isLight ? "#2563eb" : "#7ec4ff"));
      const nodeColor = (styles.getPropertyValue("--entity-bright-hex").trim()
        || styles.getPropertyValue("--entity-hex").trim()
        || lineColor);

      map.addLayer({
        id: "route-a-line",
        type: "line",
        source: "route-a",
        paint: {
          "line-color": lineColor,
          "line-width": 3.2,
          "line-opacity": 0.85,
          "line-blur": 0.4,
        },
      });
      map.addLayer({
        id: "route-b-line",
        type: "line",
        source: "route-b",
        paint: {
          "line-color": lineColor,
          "line-width": 2,
          "line-opacity": 0.45,
          "line-dasharray": [1.2, 1.6],
        },
      });
      map.addLayer({
        id: "nodes-glow",
        type: "circle",
        source: "nodes",
        paint: {
          "circle-radius": 10,
          "circle-color": nodeColor,
          "circle-opacity": 0.18,
          "circle-blur": 0.6,
        },
      });
      map.addLayer({
        id: "nodes-core",
        type: "circle",
        source: "nodes",
        paint: {
          "circle-radius": 4.5,
          "circle-color": nodeColor,
          "circle-stroke-width": 2,
          "circle-stroke-color": isLight ? "#ffffff" : "#0b1220",
        },
      });
    });

    let raf;
    let t = 0;
    const drift = () => {
      t += 0.004;
      if (mapRef.current) {
        mapRef.current.setCenter([
          CENTER[0] + Math.cos(t * 0.85) * 0.018,
          CENTER[1] + Math.sin(t) * 0.014,
        ]);
        mapRef.current.setBearing(-18 + Math.sin(t * 0.5) * 4);
      }
      raf = requestAnimationFrame(drift);
    };
    raf = requestAnimationFrame(drift);

    return () => {
      cancelAnimationFrame(raf);
      map.remove();
      mapRef.current = null;
    };
  }, [tokenOk, isLight, accent]);

  if (!tokenOk) {
    return <div className="landing-map landing-map-fallback" aria-hidden="true" />;
  }

  return <div ref={containerRef} className="landing-map" aria-hidden="true" />;
}
