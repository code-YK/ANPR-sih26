import { useEffect, useRef, useState } from "react";
import { MapContainer, Marker, useMap, useMapEvents } from "react-leaflet";

import { api } from "../api.js";
import DarkTileLayer from "./DarkTileLayer.jsx";

// Roughly centred on Gujarat -- same default as the vanilla app's picker.
const GUJARAT_CENTER = [22.6, 71.6];

// Long enough that a normal typing cadence never fires more than one
// request per pause, short enough to still feel responsive. Nominatim's
// usage policy is 1 req/sec; this keeps a fast typist well under it without
// the backend needing its own request-level throttle for a single search box.
const SEARCH_DEBOUNCE_MS = 400;

function ClickToPlace({ onChange }) {
  useMapEvents({
    click(e) {
      onChange(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

// Leaflet measures its container's size once, at mount, to lay out tiles.
// Inside a native <dialog> (Modal.jsx), this map's own mount effect fires
// before the dialog's effect calls showModal() -- React runs a child's
// effects before its parent's -- so Leaflet measures a still-closed,
// zero-size <dialog> and lays tiles out wrong; any drag forces Leaflet to
// recompute, which is why it "fixes itself" on interaction. Recomputing
// once after paint, when the dialog is actually open and sized, fixes it
// without the drag.
function InvalidateOnShow() {
  const map = useMap();
  useEffect(() => {
    const id = requestAnimationFrame(() => map.invalidateSize());
    return () => cancelAnimationFrame(id);
  }, [map]);
  return null;
}

function Recenter({ latitude, longitude }) {
  const map = useMap();
  useEffect(() => {
    if (latitude != null && longitude != null) map.setView([latitude, longitude], 14);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latitude, longitude]);
  return null;
}

/**
 * Free-text search above the map: type a place name, pick a result, and it
 * behaves exactly like a click on the map (recenter + drop the pin) via the
 * same `onChange`. Debounced client-side; the actual Nominatim call is
 * proxied through the backend's `/api/geocode/search` (see
 * backend/app/pipeline/geocode.py's search_locations) because Nominatim's
 * usage policy expects a real User-Agent, which a browser fetch can't set.
 */
function LocationSearch({ onSelect }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    if (query.trim().length < 3) {
      setResults([]);
      return undefined;
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const hits = await api(`/geocode/search?q=${encodeURIComponent(query)}`);
        setResults(hits);
        setOpen(true);
      } catch (_) {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(debounceRef.current);
  }, [query]);

  function pick(hit) {
    onSelect(hit.latitude, hit.longitude);
    setQuery(hit.display_name);
    setOpen(false);
  }

  return (
    <div className="location-search">
      <input
        type="text"
        placeholder="Search a place to jump the map…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {loading && <span className="location-search-status">searching…</span>}
      {open && results.length > 0 && (
        <ul className="location-search-results">
          {results.map((hit, i) => (
            // Nominatim results have no stable id; index is fine, this list
            // is replaced wholesale on every search, never reordered in place.
            <li key={i} onMouseDown={() => pick(hit)}>
              {hit.display_name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Click the map or drag the pin to set (latitude, longitude); typing into
 * the paired number inputs elsewhere in the form re-centres this map via
 * the `latitude`/`longitude` props -- same bidirectional behaviour as the
 * vanilla app's createLocationPicker, rebuilt on react-leaflet idioms
 * instead of raw Leaflet calls against manually-queried <input> elements.
 */
export default function LocationPicker({ latitude, longitude, onChange }) {
  const hasPosition = latitude != null && longitude != null;

  return (
    <div className="location-picker-wrap">
      <LocationSearch onSelect={onChange} />
      <MapContainer
        center={hasPosition ? [latitude, longitude] : GUJARAT_CENTER}
        zoom={hasPosition ? 14 : 7}
        className="location-picker"
      >
        <DarkTileLayer />
        <InvalidateOnShow />
        <Recenter latitude={latitude} longitude={longitude} />
        <ClickToPlace onChange={onChange} />
        {hasPosition && (
          <Marker
            position={[latitude, longitude]}
            draggable
            eventHandlers={{
              dragend: (e) => {
                const pos = e.target.getLatLng();
                onChange(pos.lat, pos.lng);
              },
            }}
          />
        )}
      </MapContainer>
    </div>
  );
}
