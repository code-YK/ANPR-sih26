import { useEffect, useRef, useState } from "react";
import { MapContainer, Marker, useMap, useMapEvents } from "react-leaflet";

import { DarkTileLayer, DEFAULT_CENTER, pinIcon } from "../../components/map/MapBase.jsx";
import { Input, Spinner } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import styles from "./Registry.module.css";

// Nominatim's usage policy is one request a second; a pause-length debounce
// keeps a fast typist well inside it. The search itself is proxied by the
// backend so it can send a proper User-Agent.
const DEBOUNCE_MS = 400;

function ClickToPlace({ onChange }) {
  useMapEvents({ click: (event) => onChange(event.latlng.lat, event.latlng.lng) });
  return null;
}

// Leaflet measures its container on mount; inside a dialog that opens after
// the map mounts, it must be told to measure again once visible.
function InvalidateOnShow() {
  const map = useMap();
  useEffect(() => {
    const id = setTimeout(() => map.invalidateSize(), 60);
    return () => clearTimeout(id);
  }, [map]);
  return null;
}

function Recenter({ latitude, longitude }) {
  const map = useMap();
  useEffect(() => {
    if (latitude != null && longitude != null) map.setView([latitude, longitude], Math.max(map.getZoom(), 14));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latitude, longitude]);
  return null;
}

export default function LocationPicker({ latitude, longitude, onChange }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const timer = useRef(null);
  const hasPosition = latitude != null && longitude != null && !Number.isNaN(latitude) && !Number.isNaN(longitude);

  useEffect(() => {
    clearTimeout(timer.current);
    if (query.trim().length < 3) {
      setResults([]);
      return undefined;
    }
    timer.current = setTimeout(async () => {
      setLoading(true);
      try {
        setResults(await api(`/geocode/search?q=${encodeURIComponent(query)}`));
        setOpen(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer.current);
  }, [query]);

  return (
    <div className={styles.picker}>
      <div className={styles.pickerSearch}>
        <Input
          placeholder="Search a place to move the map"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => results.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          aria-label="Search a place"
        />
        {loading && <Spinner className={styles.pickerSpinner} />}
        {open && results.length > 0 && (
          <ul className={styles.pickerResults} role="listbox">
            {results.map((hit, index) => (
              <li
                key={index}
                role="option"
                aria-selected="false"
                onMouseDown={() => {
                  onChange(hit.latitude, hit.longitude);
                  setQuery(hit.display_name);
                  setOpen(false);
                }}
              >
                {hit.display_name}
              </li>
            ))}
          </ul>
        )}
      </div>
      <MapContainer center={hasPosition ? [latitude, longitude] : DEFAULT_CENTER} zoom={hasPosition ? 14 : 7} className={styles.pickerMap}>
        <DarkTileLayer />
        <InvalidateOnShow />
        <Recenter latitude={hasPosition ? latitude : null} longitude={hasPosition ? longitude : null} />
        <ClickToPlace onChange={onChange} />
        {hasPosition && (
          <Marker
            position={[latitude, longitude]}
            icon={pinIcon}
            draggable
            eventHandlers={{
              dragend: (event) => {
                const position = event.target.getLatLng();
                onChange(position.lat, position.lng);
              },
            }}
          />
        )}
      </MapContainer>
      <p className="ui-field__hint">Click the map or drag the pin. Setting a position marks the geocode as exact.</p>
    </div>
  );
}
