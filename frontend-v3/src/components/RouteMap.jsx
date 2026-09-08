import { useEffect } from "react";
import { MapContainer, Marker, Polyline, Popup, useMap } from "react-leaflet";
import L from "leaflet";

import DarkTileLayer from "./DarkTileLayer.jsx";

function numberedIcon(n, highlighted) {
  return L.divIcon({
    className: `route-marker${highlighted ? " route-marker-active" : ""}`,
    html: `<div class="route-marker-inner">${n}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

function FitBounds({ positions }) {
  const map = useMap();
  useEffect(() => {
    if (positions.length === 0) return;
    if (positions.length === 1) map.setView(positions[0], 14);
    else map.fitBounds(positions, { padding: [30, 30] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(positions)]);
  return null;
}

/**
 * The map instance stays mounted across searches (JourneyView never gives
 * this component a volatile `key`) -- layers update via props instead of
 * the whole MapContainer remounting, which is the most common React+Leaflet
 * bug per the build spec's hazards list.
 */
export default function RouteMap({ stops, hoveredIndex, onHover }) {
  const placed = stops
    .map((s, i) => ({ ...s, _index: i }))
    .filter((s) => s.latitude != null && s.longitude != null);
  const positions = placed.map((s) => [s.latitude, s.longitude]);

  return (
    <MapContainer center={[22.6, 71.6]} zoom={7} className="route-map">
      <DarkTileLayer />
      <FitBounds positions={positions} />
      {positions.length > 1 && <Polyline positions={positions} color="#1c5cb8" weight={3} />}
      {placed.map((s, i) => (
        <Marker
          key={s.sighting_id}
          position={[s.latitude, s.longitude]}
          icon={numberedIcon(i + 1, hoveredIndex === s._index)}
          eventHandlers={{
            mouseover: () => onHover(s._index),
            mouseout: () => onHover(null),
          }}
        >
          <Popup>
            <strong>
              #{i + 1} {s.camera_name}
            </strong>
            <br />
            {s.location_text}
            <br />
            {new Date(s.seen_at).toLocaleString()}
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}
