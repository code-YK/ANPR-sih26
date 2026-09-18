import { memo, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { HlsTileVideo } from "./LiveVideo.jsx";
import { getPoster } from "./posters.js";
import styles from "./Focused.module.css";

/**
 * Other cameras, kept one click away. Tiles show a recent still and only open
 * a live preview while hovered or focused, so the focused view spends its
 * connection budget on the feed that matters.
 */
// Hover intent: sweeping the pointer across the strip must not spin up (and
// tear down) a stream per tile it passes over.
const HOVER_INTENT_MS = 450;

const FilmstripTile = memo(function FilmstripTile({ camera, aiRunning }) {
  const [hot, setHot] = useState(false);
  const timer = useRef(null);
  const poster = getPoster(camera.camera_id);
  useEffect(() => () => clearTimeout(timer.current), []);
  const warm = () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setHot(true), HOVER_INTENT_MS);
  };
  const cool = () => {
    clearTimeout(timer.current);
    setHot(false);
  };
  return (
    <li>
      <Link
        to={`/live/${encodeURIComponent(camera.camera_id)}`}
        className={styles.stripTile}
        onPointerEnter={warm}
        onPointerLeave={cool}
        onFocus={warm}
        onBlur={cool}
        aria-label={`Open ${camera.name}`}
      >
        <div className={styles.stripMedia}>
          {camera.stream_available ? (
            hot ? (
              <HlsTileVideo cameraId={camera.camera_id} active />
            ) : poster ? (
              <img src={poster} alt="" className={styles.stripPoster} />
            ) : (
              <span className={styles.stripEmpty}>{camera.camera_id}</span>
            )
          ) : (
            <span className={styles.stripEmpty}>No stream</span>
          )}
          {aiRunning && <span className={styles.stripAi}>AI</span>}
        </div>
        <span className={styles.stripName}>{camera.name}</span>
      </Link>
    </li>
  );
});

function CameraFilmstrip({ cameras, currentId, aiCameraIds }) {
  const others = cameras.filter((camera) => camera.camera_id !== currentId);
  if (others.length === 0) return null;
  return (
    <section className={styles.strip} aria-label="Other cameras">
      <div className={styles.stripHeader}>
        <h3>Other cameras</h3>
        <span className="faint">{others.length}</span>
      </div>
      <ul className={styles.stripList}>
        {others.map((camera) => (
          <FilmstripTile key={camera.camera_id} camera={camera} aiRunning={aiCameraIds.has(camera.camera_id)} />
        ))}
      </ul>
    </section>
  );
}

export default memo(CameraFilmstrip);
