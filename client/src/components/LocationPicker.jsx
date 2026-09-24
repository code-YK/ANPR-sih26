import { useEffect, useRef, useState } from "react";

import { api } from "../api.js";
import { ensureMapboxToken, mapboxgl, mapboxStyleUrl, useTheme } from "../lib/mapbox.js";

const GUJARAT_CENTER = [71.6, 22.6]; // lng, lat

/**
 * Click-to-place camera location on Mapbox. Same contract as the Leaflet
 * picker: onChange({ latitude, longitude, geocode_confidence }).
 */
const SEARCH_MIN_CHARS = 3;
const SEARCH_DEBOUNCE_MS = 400;

export default function LocationPicker({ value, onChange, height = 280 }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const { isLight } = useTheme();
  const hasToken = ensureMapboxToken();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [open, setOpen] = useState(false);
  const searchTimer = useRef(null);

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

  // Place search through the backend's Nominatim proxy (GET /geocode/search),
  // which sends a proper User-Agent. Nominatim's policy is one request a
  // second, so typing is debounced and nothing is sent under three characters.
  useEffect(() => {
    clearTimeout(searchTimer.current);
    const text = query.trim();
    if (text.length < SEARCH_MIN_CHARS) {
      setResults([]);
      setSearching(false);
      setSearchError("");
      return undefined;
    }
    const controller = new AbortController();
    searchTimer.current = setTimeout(async () => {
      setSearching(true);
      setSearchError("");
      try {
        setResults(await api(`/geocode/search?q=${encodeURIComponent(text)}`, { signal: controller.signal }));
      } catch (err) {
        if (!controller.signal.aborted) {
          setResults([]);
          setSearchError(err.message);
        }
      } finally {
        if (!controller.signal.aborted) setSearching(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(searchTimer.current);
      controller.abort();
    };
  }, [query]);

  function pick(hit) {
    setQuery(hit.display_name);
    setOpen(false);
    const map = mapRef.current;
    if (map) placeMarker(map, hit.longitude, hit.latitude);
    // A place-name match, not the camera's surveyed point -- recorded as
    // approximate. Clicking the map to refine it records an exact position.
    onChange?.({ latitude: hit.latitude, longitude: hit.longitude, geocode_confidence: "approximate" });
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
      <div className="location-search">
        <input
          type="search"
          value={query}
          placeholder="Search a place — street, junction or landmark"
          aria-label="Search a place"
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
        {open && (searching || searchError || results.length > 0 || query.trim().length >= SEARCH_MIN_CHARS) && (
          <ul className="location-search-results" role="listbox" aria-label="Places">
            {searching ? (
              <li className="location-search-note">Searching…</li>
            ) : searchError ? (
              <li className="location-search-note is-error">Place search failed: {searchError}</li>
            ) : results.length === 0 ? (
              <li className="location-search-note">No places match.</li>
            ) : (
              results.map((hit, index) => (
                <li key={`${hit.latitude},${hit.longitude},${index}`}>
                  <button type="button" role="option" aria-selected="false" onMouseDown={(e) => e.preventDefault()} onClick={() => pick(hit)}>
                    {hit.display_name}
                  </button>
                </li>
              ))
            )}
          </ul>
        )}
      </div>
      <div ref={containerRef} className="location-picker-map" style={{ height }} />
      <p className="hint">
        Search a place or click the map to set coordinates
        {lat != null && lng != null ? ` · ${lat.toFixed(5)}, ${lng.toFixed(5)}` : ""}
      </p>
    </div>
  );
}
