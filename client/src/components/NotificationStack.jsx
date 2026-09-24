import { memo, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertOctagon, Bell, CarFront, CheckCircle2, CircleAlert, ShieldAlert, UserRoundX, X } from "lucide-react";

import PlateChip from "./PlateChip.jsx";
import {
  clearNotifications,
  dismissNotification,
  splitVisible,
  useNotifications,
  useSoundBlocked,
} from "../lib/notifications.js";

const KIND = {
  sighting: { icon: CarFront, label: "ANPR sighting", tone: "signal" },
  "sighting-group": { icon: CarFront, label: "ANPR sightings", tone: "signal" },
  watchlist: { icon: ShieldAlert, label: "Watchlist match", tone: "critical" },
  suspicious: { icon: UserRoundX, label: "Suspicious activity", tone: "critical" },
  worker: { icon: AlertOctagon, label: "AI worker", tone: "critical" },
  system: { icon: Bell, label: "", tone: "neutral" },
};

function fmtClock(value) {
  if (!value) return "";
  return new Date(value).toLocaleTimeString([], { hour12: false });
}

/** Auto-dismiss that pauses while hovered, focused or the tab is hidden, and resumes where it left off. */
function useDismissTimer(item, paused, onDone) {
  const remaining = useRef(item.ttl);
  const startedAt = useRef(null);
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  });

  useEffect(() => {
    if (paused) return undefined;
    startedAt.current = Date.now();
    const id = setTimeout(() => onDoneRef.current(), remaining.current);
    return () => {
      clearTimeout(id);
      remaining.current = Math.max(0, remaining.current - (Date.now() - startedAt.current));
    };
  }, [paused]);
}

const NotificationCard = memo(function NotificationCard({ item, paused }) {
  const navigate = useNavigate();
  const [hover, setHover] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const meta = KIND[item.kind] ?? KIND.system;
  const isSystem = item.kind === "system";
  const tone = isSystem ? item.tone ?? "neutral" : meta.tone;
  const Icon = isSystem && tone === "critical" ? CircleAlert : isSystem && tone === "live" ? CheckCircle2 : meta.icon;
  useDismissTimer(item, paused || hover, () => dismissNotification(item.id));

  const title =
    item.kind === "sighting-group" ? `${item.count} new plates` : item.kind === "sighting" ? "New plate read" : item.title;

  const open = () => {
    if (!item.href) return;
    navigate(item.href);
    dismissNotification(item.id);
  };

  return (
    <div
      className="note-card"
      data-tone={tone}
      data-system={isSystem || undefined}
      role={tone === "critical" && !isSystem ? "alert" : "status"}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
    >
      <div className="note-icon" aria-hidden="true">
        <Icon size={isSystem ? 15 : 18} strokeWidth={2} />
      </div>
      <div className="note-content">
        {!isSystem && (
          <p className="note-overline">
            <span>{meta.label}</span>
            {item.cameraName && <span className="note-dot">·</span>}
            {item.cameraName && <span className="note-camera">{item.cameraName}</span>}
            {item.time && <time className="note-time">{fmtClock(item.time)}</time>}
          </p>
        )}
        {item.href ? (
          <button type="button" className="note-title" onClick={open}>
            {title}
          </button>
        ) : (
          <p className="note-title">{title}</p>
        )}
        {(item.plate || item.plates) && (
          <div className="note-plates">
            {(item.plates ?? [item.plate]).map((plate, index) => (
              <PlateChip key={`${plate}-${index}`} plate={plate} />
            ))}
            {item.kind === "sighting-group" && item.count > (item.plates?.length ?? 0) && (
              <span className="note-more">+{item.count - item.plates.length}</span>
            )}
          </div>
        )}
        {item.detail && <p className="note-detail">{item.detail}</p>}
      </div>
      {item.image && !imageFailed && (
        <img className="note-image" src={item.image} alt="" loading="lazy" onError={() => setImageFailed(true)} />
      )}
      <button type="button" className="note-close" onClick={() => dismissNotification(item.id)} aria-label="Dismiss notification">
        <X size={14} strokeWidth={2.25} />
      </button>
      <span
        className="note-timer"
        style={{ animationDuration: `${item.ttl}ms`, animationPlayState: paused || hover ? "paused" : "running" }}
        aria-hidden="true"
      />
    </div>
  );
});

/**
 * Bottom-right, above the Copilot and Logs buttons: newest nearest them, three
 * at most, the rest summarised. Cards never take focus. Same placement and
 * anatomy as frontend-v5's NotificationStack.
 */
export default function NotificationStack() {
  const items = useNotifications();
  const soundBlocked = useSoundBlocked();
  const [hidden, setHidden] = useState(() => document.visibilityState !== "visible");

  useEffect(() => {
    const handle = () => setHidden(document.visibilityState !== "visible");
    document.addEventListener("visibilitychange", handle);
    return () => document.removeEventListener("visibilitychange", handle);
  }, []);

  const { visible, overflow } = splitVisible(items);

  return (
    <section className="note-region" aria-label="Notifications" aria-live="polite">
      {overflow > 0 && (
        <div className="note-overflow">
          <span>
            +{overflow} earlier notification{overflow === 1 ? "" : "s"}
          </span>
          <button type="button" onClick={clearNotifications}>
            Clear all
          </button>
        </div>
      )}
      {soundBlocked && (
        <div className="note-overflow">
          <span>Alert sound is blocked until you click anywhere on the page.</span>
        </div>
      )}
      {visible.map((item) => (
        <NotificationCard key={item.id} item={item} paused={hidden} />
      ))}
    </section>
  );
}
