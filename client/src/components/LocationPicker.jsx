import { useEffect, useRef, useState } from "react";

import { api } from "../api.js";
import { ensureMapboxToken, mapboxgl, mapboxStyleUrl, useTheme } from "../lib/mapbox.js";

const GUJARAT_CENTER = [71.6, 22.6]; // lng, lat

/**
 * Click-to-place camera location on Mapbox. Same contract as the Leaflet
 * picker: onChange({ latitude, longitude, geocode_confidence }).
 */
export default function LocationPicker({ value, onChange, height = 280 }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const { isLight } = useTheme();
  const hasToken = ensureMapboxToken();
  const [busy, setBusy] = useState(false);

  const lat = value?.latitude ?? null;
  const lng = value?.longitude ?? null;

  useEffect(() => {
    if (!containerRef.current || !hasToken) return undefined;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: mapboxStyleUrl(isLight),
      center: lng != null && lat != null ? [lng, lat] : GUJARAT_CENTER,
      zoom: lng != null && lat != null ? 14 : 7,
      attributionControl: true,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    map.on("click", async (e) => {
      const { lng: clickLng, lat: clickLat } = e.lngLat;
      placeMarker(map, clickLng, clickLat);
      onChange?.({
        latitude: clickLat,
        longitude: clickLng,
        geocode_confidence: "exact",
      });
    });

    if (lng != null && lat != null) {
      map.on("load", () => placeMarker(map, lng, lat));
    }

    return () => {
      markerRef.current?.remove();
      markerRef.current = null;
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasToken, isLight]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || lng == null || lat == null) return;
    placeMarker(map, lng, lat);
    map.easeTo({ center: [lng, lat], zoom: Math.max(map.getZoom(), 12), duration: 300 });
  }, [lat, lng]);

  function placeMarker(map, longitude, latitude) {
    if (markerRef.current) {
      markerRef.current.setLngLat([longitude, latitude]);
      return;
    }
    markerRef.current = new mapboxgl.Marker({ color: "#1d6fd8" })
      .setLngLat([longitude, latitude])
      .addTo(map);
  }

  async function reverseHint() {
    if (lat == null || lng == null) return;
    setBusy(true);
    try {
      await api(`/geocode/reverse?lat=${lat}&lng=${lng}`);
    } catch {
      /* optional hint */
    } finally {
      setBusy(false);
    }
  }

  if (!hasToken) {
    return (
      <div className="location-picker mapbox-missing" style={{ height }}>
        Set <code>VITE_MAPBOX_TOKEN</code> to place cameras on the map.
      </div>
    );
  }

  return (
    <div className="location-picker">
      <div ref={containerRef} className="location-picker-map" style={{ height }} />
      <p className="hint">
        Click the map to set coordinates
        {lat != null && lng != null ? ` · ${lat.toFixed(5)}, ${lng.toFixed(5)}` : ""}
        {busy ? " · …" : ""}
      </p>
    </div>
  );
}
