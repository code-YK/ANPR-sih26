import { ArrowUpRight, VideoOff } from "lucide-react";
import { memo, useCallback, useState } from "react";
import { Link } from "react-router-dom";

import { Spinner } from "../../components/ui.jsx";
import { BACKEND_LABEL } from "../workers/modes.js";
import { HlsTileVideo } from "./LiveVideo.jsx";
import styles from "./CameraGrid.module.css";

const MODE_ORDER = { vehicle_finetuned: 0, vehicle: 1, person: 2, suspicious: 3 };

function AiChips({ workers }) {
  if (!workers?.length) return null;
  const sorted = [...workers].sort((a, b) => (MODE_ORDER[a.mode] ?? 9) - (MODE_ORDER[b.mode] ?? 9));
  return (
    <div className={styles.aiChips}>
      {sorted.map((row) => (
        <span key={row.mode} className={styles.aiChip} data-state={row.state}>
          <span className={styles.aiChipDot} aria-hidden="true" />
          {BACKEND_LABEL[row.mode] === "ANPR (baseline model)" ? "ANPR·base" : BACKEND_LABEL[row.mode] ?? row.mode}
          <span className="visually-hidden">{row.state === "queued" ? " queued" : " running"}</span>
        </span>
      ))}
    </div>
  );
}

function CameraTile({ camera, active, visible, workers, relayed, register }) {
  const [state, setState] = useState("idle");
  const ref = useCallback((element) => register(camera.camera_id, element), [register, camera.camera_id]);
  const previewable = camera.stream_available;

  let overlay = null;
  if (!previewable) {
    overlay = (
      <div className={`${styles.placeholder} ${styles.hatch}`}>
        <VideoOff aria-hidden="true" />
        <span>{camera.webrtc_preview_available ? "Open to view (real-time only)" : "No stream"}</span>
      </div>
    );
  } else if (!active) {
    overlay = visible ? (
      <div className={`${styles.placeholder} ${styles.dots}`}>
        <span>Preview paused · limit reached</span>
      </div>
    ) : null;
  } else if (state !== "playing") {
    overlay = (
      <div className={styles.status}>
        <Spinner />
        <span>{state === "reconnecting" ? "Reconnecting" : "Connecting"}</span>
      </div>
    );
  }

  return (
    <article ref={ref} data-camera-id={camera.camera_id} className={styles.tile} data-ai={workers?.length ? "true" : undefined}>
      <Link
        to={`/live/${encodeURIComponent(camera.camera_id)}`}
        className={styles.tileLink}
        aria-label={`Open ${camera.name}${workers?.length ? `, AI running` : ""}`}
      >
        <div className={styles.media}>
          {previewable && <HlsTileVideo cameraId={camera.camera_id} active={active} onState={setState} />}
          {overlay}
        </div>
        <div className={styles.topRow}>
          <span className={styles.idChip}>{camera.camera_id}</span>
          {relayed && <span className={styles.replayChip}>Replay</span>}
          <AiChips workers={workers} />
        </div>
        <div className={styles.bottom}>
          <div className={styles.names}>
            <span className={styles.name}>{camera.name}</span>
            <span className={styles.location}>{camera.location_text}</span>
          </div>
          <span className={styles.open} aria-hidden="true">
            <ArrowUpRight />
          </span>
        </div>
      </Link>
    </article>
  );
}

export default memo(CameraTile);
