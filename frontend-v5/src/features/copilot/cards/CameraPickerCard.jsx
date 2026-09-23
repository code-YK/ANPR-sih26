
import { CircleMarker, MapContainer, Tooltip as MapTooltip } from "react-leaflet";

import { DarkTileLayer, DEFAULT_CENTER, MAP_COLORS } from "../../../components/map/MapBase.jsx";
import { Button } from "../../../components/ui.jsx";
import styles from "../Copilot.module.css";

function healthColor(camera) {
  if (camera.is_live === true) return MAP_COLORS.live;
  if (camera.is_live === false) return MAP_COLORS.critical;
  return MAP_COLORS.unknown;
}

/**
 * Candidate cameras for a place the operator named instead of an id.
 *
 * Tapping a pin answers the assistant's question for them -- it sends the
 * camera id back as the next user turn, which is far less friction than
 * typing an id they would have to look up first. Cameras without
 * coordinates still appear, as buttons, rather than silently vanishing.
 */
export default function CameraPickerCard({ data, onPick, disabled }) {
  const cameras = data?.cameras ?? [];
  const placed = cameras.filter((camera) => camera.latitude != null && camera.longitude != null);
  const unplaced = cameras.filter((camera) => camera.latitude == null || camera.longitude == null);

  if (cameras.length === 0) {
    return <p className={styles.cardEmpty}>No cameras matched “{data?.query}”.</p>;
  }

  const center = placed.length
    ? [placed[0].latitude, placed[0].longitude]
    : DEFAULT_CENTER;

  return (
    <div className={styles.picker}>
      {placed.length > 0 && (
        <MapContainer center={center} zoom={placed.length === 1 ? 14 : 11} className={styles.pickerMap}>
          <DarkTileLayer />
          {placed.map((camera) => (
            <CircleMarker
              key={camera.camera_id}
              center={[camera.latitude, camera.longitude]}
              radius={7}
              pathOptions={{
                color: healthColor(camera),
                fillColor: healthColor(camera),
                fillOpacity: 0.7,
                weight: 2,
              }}
              eventHandlers={{ click: () => !disabled && onPick?.(camera) }}
            >
              <MapTooltip>
                {camera.camera_id} · {camera.name}
              </MapTooltip>
            </CircleMarker>
          ))}
        </MapContainer>
      )}

      <ul className={styles.pickerList}>
        {cameras.map((camera) => (
          <li key={camera.camera_id}>
            <Button
              size="sm"
              variant="ghost"
              disabled={disabled}
              className={styles.pickerButton}
              onClick={() => onPick?.(camera)}
            >
              <span className={styles.pickerId}>{camera.camera_id}</span>
              <span className={styles.pickerName}>{camera.location || camera.name}</span>
            </Button>
          </li>
        ))}
      </ul>

      {unplaced.length > 0 && placed.length > 0 && (
        <p className={styles.cardNote}>
          {unplaced.length} of these have no coordinates and appear only in the list.
        </p>
      )}
    </div>
  );
}
