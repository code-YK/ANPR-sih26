import { useEffect, useRef } from "react";
import { Camera, Radio, WifiOff } from "lucide-react";

import { hlsProxyUrl } from "../../api.js";
import { AnprBadge, LiveBadge, PlaybackBadge } from "../../components/Badge.jsx";
import StatusDot from "../../components/StatusDot.jsx";
import { useHlsPlayer } from "../../hooks/useHlsPlayer.js";
import { useVisibility } from "../../hooks/useVisibility.js";

function tileTone({ streamAvailable, active, focused, stalled, playbackState, isLive }) {
  if (focused) return "tone-focus";
  if (stalled || playbackState === "reconnecting") return "tone-warn";
  if (active && playbackState === "connected") return "tone-live";
  if (active && (playbackState === "connecting" || !playbackState)) return "tone-pending";
  if (!streamAvailable) return "tone-offline";
  if (isLive === false) return "tone-offline";
  return "tone-idle";
}

function TileSpinner() {
  return (
    <span className="tile-spinner" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  );
}

function TileStage({ variant, icon, title, detail, compact }) {
  return (
    <div className={`camera-tile-stage camera-tile-stage-${variant}${compact ? " is-compact" : ""}`}>
      {!compact && <div className="camera-tile-stage-orb" aria-hidden="true" />}
      <div className="camera-tile-stage-body">
        {variant === "loading" || variant === "waiting" || variant === "reconnecting" ? (
          <TileSpinner />
        ) : (
          icon
        )}
        <strong>{title}</strong>
        {!compact && detail ? <span>{detail}</span> : null}
      </div>
    </div>
  );
}

export default function CameraTile({
  camera,
  active,
  focused,
  paused,
  analyticsState,
  onFocus,
  onVisibilityChange,
  compact = false,
  listMode = false,
}) {
  const videoRef = useRef(null);
  const [visRef, visible] = useVisibility();

  useEffect(() => {
    onVisibilityChange(camera.camera_id, visible);
    return () => onVisibilityChange(camera.camera_id, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, camera.camera_id]);

  const { stalled, playbackState } = useHlsPlayer(
    active ? (viewer) => hlsProxyUrl(camera, viewer) : null,
    videoRef,
  );

  const tone = tileTone({
    streamAvailable: camera.stream_available,
    active,
    focused,
    stalled,
    playbackState,
    isLive: camera.is_live,
  });

  const shortName = camera.name?.length > 28 ? `${camera.name.slice(0, 26)}…` : camera.name;

  const listStatus = !camera.stream_available && !camera.webrtc_preview_available
    ? "Offline"
    : !active
      ? paused
        ? "Paused"
        : "Standby"
      : stalled || playbackState === "reconnecting"
        ? "Reconnecting"
        : playbackState === "connected"
          ? "Live"
          : "Connecting";

  const chrome = listMode ? (
    <div className="camera-tile-chrome camera-tile-chrome-list">
      <div className="camera-list-main">
        <span className="camera-tile-name" title={camera.name}>{camera.name}</span>
        <span className="camera-list-sub">
          <span className="camera-list-id">{camera.camera_id}</span>
          {camera.location_text ? <span className="camera-list-loc">{camera.location_text}</span> : null}
        </span>
      </div>
      <div className="camera-list-meta">
        <span className="camera-list-dept">{camera.department || "—"}</span>
        {camera.anpr_viable === true || camera.anpr_viable === false ? (
          <AnprBadge value={camera.anpr_viable} />
        ) : null}
        {(analyticsState === "running" || analyticsState === "queued") && (
          <StatusDot
            state={analyticsState}
            title={analyticsState === "running" ? "ANPR running" : "ANPR queued"}
          />
        )}
      </div>
      <div className={`camera-list-status is-${listStatus.toLowerCase()}`}>
        <span className="camera-list-status-dot" aria-hidden="true" />
        {listStatus}
      </div>
    </div>
  ) : (
    <div className="camera-tile-chrome">
      <div className="camera-tile-top">
        {!compact && (
          <span className="camera-tile-id">
            <Radio size={11} strokeWidth={2.25} aria-hidden="true" />
            CAM · {String(camera.camera_id).slice(0, 8)}
          </span>
        )}
        <div className="camera-tile-flags">
          {active
            ? playbackState === "connected"
              ? <PlaybackBadge state={playbackState} />
              : null
            : compact
              ? null
              : <LiveBadge value={camera.is_live} />}
          {!compact && camera.anpr_viable !== null && camera.anpr_viable !== undefined && (
            <AnprBadge value={camera.anpr_viable} />
          )}
          {(analyticsState === "running" || analyticsState === "queued") && (
            <StatusDot
              state={analyticsState}
              title={analyticsState === "running" ? "ANPR running" : "ANPR enabled, waiting for a worker slot"}
            />
          )}
        </div>
      </div>
      <div className="camera-tile-bottom">
        <span className="camera-tile-name" title={camera.name}>
          {compact ? shortName : camera.name}
        </span>
        {!compact && (
          <span className="camera-tile-meta">
            {[camera.department, camera.camera_type].filter(Boolean).join(" · ") || "—"}
          </span>
        )}
      </div>
    </div>
  );

  if (!camera.stream_available) {
    const focusable = Boolean(camera.webrtc_preview_available);
    return (
      <div
        ref={visRef}
        className={`camera-tile camera-tile-empty camera-tile-nostream ${tone}${focused ? " focused" : ""}${compact ? " is-compact" : ""}${listMode ? " is-list" : ""}`}
        onClick={focusable ? () => onFocus(camera.camera_id) : undefined}
        role={focusable ? "button" : undefined}
        tabIndex={focusable ? 0 : undefined}
        onKeyDown={
          focusable
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") onFocus(camera.camera_id);
              }
            : undefined
        }
      >
        <TileStage
          compact={compact}
          variant="offline"
          icon={<WifiOff size={compact ? 16 : 22} strokeWidth={1.75} aria-hidden="true" />}
          title={compact ? (focusable ? "Preview" : "No stream") : focusable ? "WebRTC preview available" : "No stream endpoint"}
          detail={focusable ? "Open focused view to preview" : "Source not configured for HLS"}
        />
        {chrome}
      </div>
    );
  }

  const isReconnecting = active && (stalled || playbackState === "reconnecting");
  const showConnecting = active && !isReconnecting && playbackState !== "connected";
  let stage = null;
  if (!active) {
    if (paused) {
      stage = (
        <TileStage
          compact={compact}
          variant="paused"
          icon={<Camera size={compact ? 16 : 22} strokeWidth={1.75} aria-hidden="true" />}
          title="Paused"
          detail="Focused camera holds the stream budget"
        />
      );
    } else if (visible) {
      stage = (
        <TileStage
          compact={compact}
          variant="waiting"
          title={compact ? "Queued" : "Waiting for a free slot"}
          detail="Preview limit reached — another feed will release soon"
        />
      );
    } else {
      stage = (
        <TileStage
          compact={compact}
          variant="idle"
          icon={<Camera size={compact ? 16 : 22} strokeWidth={1.75} aria-hidden="true" />}
          title={compact ? "Standby" : "Standby"}
          detail="Scroll into view to activate"
        />
      );
    }
  } else if (isReconnecting) {
    stage = (
      <TileStage
        compact={compact}
        variant="reconnecting"
        title={compact ? "Recovering" : "Reconnecting"}
        detail="Stream stalled — recovering link…"
      />
    );
  } else if (showConnecting) {
    stage = (
      <TileStage
        compact={compact}
        variant="loading"
        title={compact ? "Connecting" : "Connecting"}
        detail="Negotiating stream with gateway…"
      />
    );
  }

  return (
    <div
      ref={visRef}
      className={`camera-tile ${tone}${focused ? " focused" : ""}${compact ? " is-compact" : ""}${listMode ? " is-list" : ""}`}
      onClick={() => onFocus(camera.camera_id)}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onFocus(camera.camera_id);
      }}
    >
      <div className="camera-tile-frame">
        {active && <video ref={videoRef} muted playsInline autoPlay />}
        {stage}
      </div>
      {chrome}
    </div>
  );
}
