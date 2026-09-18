import { AlertOctagon, Bell, CarFront, CheckCircle2, CircleAlert, ShieldAlert, UserRoundX, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { memo, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { PlateChip } from "../../components/ui.jsx";
import { fmtClock } from "../../lib/format.js";
import { useUiStore } from "../../lib/uiStore.js";
import { useNotificationStore } from "./notificationStore.js";
import { splitVisible } from "./rules.js";
import styles from "./Notifications.module.css";

const KIND = {
  sighting: { icon: CarFront, label: "ANPR sighting", tone: "signal" },
  "sighting-group": { icon: CarFront, label: "ANPR sightings", tone: "signal" },
  watchlist: { icon: ShieldAlert, label: "Watchlist match", tone: "critical" },
  suspicious: { icon: UserRoundX, label: "Suspicious activity", tone: "critical" },
  worker: { icon: AlertOctagon, label: "AI worker", tone: "critical" },
  system: { icon: Bell, label: "", tone: "neutral" },
};

/** Auto-dismiss that pauses while hovered or focused, resuming where it left off. */
function useDismissTimer(item, paused, onDone) {
  const remaining = useRef(item.ttl);
  const startedAt = useRef(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

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
  const dismiss = useNotificationStore((state) => state.dismiss);
  const navigate = useNavigate();
  const [hover, setHover] = useState(false);
  const meta = KIND[item.kind] ?? KIND.system;
  const tone = item.kind === "system" ? item.tone ?? "neutral" : meta.tone;
  const Icon = item.kind === "system" && tone === "critical" ? CircleAlert : item.kind === "system" && tone === "live" ? CheckCircle2 : meta.icon;
  useDismissTimer(item, paused || hover, () => dismiss(item.id));

  const open = () => {
    if (!item.href) return;
    navigate(item.href);
    dismiss(item.id);
  };

  const isSystem = item.kind === "system";
  const title =
    item.kind === "sighting-group"
      ? `${item.count} new plates`
      : item.kind === "sighting"
        ? "New plate read"
        : item.title;

  return (
    <div
      className={styles.card}
      data-tone={tone}
      data-system={isSystem || undefined}
      role={tone === "critical" && !isSystem ? "alert" : "status"}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
    >
      <div className={styles.icon} aria-hidden="true">
        <Icon />
      </div>
      <div className={styles.content}>
        {!isSystem && (
          <p className={styles.overline}>
            <span>{meta.label}</span>
            {item.cameraName && <span className={styles.dot}>·</span>}
            {item.cameraName && <span className={styles.camera}>{item.cameraName}</span>}
            {item.time && <time className={styles.time}>{fmtClock(item.time)}</time>}
          </p>
        )}
        {item.href ? (
          <button type="button" className={styles.title} onClick={open}>
            {title}
          </button>
        ) : (
          <p className={styles.title}>{title}</p>
        )}
        {(item.plate || item.plates) && (
          <div className={styles.plates}>
            {(item.plates ?? [item.plate]).map((plate, index) => (
              <PlateChip key={`${plate}-${index}`} plate={plate} />
            ))}
            {item.kind === "sighting-group" && item.count > (item.plates?.length ?? 0) && (
              <span className={styles.more}>+{item.count - item.plates.length}</span>
            )}
          </div>
        )}
        {item.detail && <p className={styles.detail}>{item.detail}</p>}
      </div>
      {item.image && <img className={styles.image} src={item.image} alt="" loading="lazy" />}
      <button type="button" className={styles.close} onClick={() => dismiss(item.id)} aria-label="Dismiss notification">
        <X />
      </button>
      <span className={styles.timer} style={{ animationDuration: `${item.ttl}ms`, animationPlayState: paused || hover ? "paused" : "running" }} aria-hidden="true" />
    </div>
  );
});

/**
 * Bottom-right, stacked above the Logs button: newest nearest the button,
 * three at most, the rest summarised. Cards never take focus.
 */
export default function NotificationStack() {
  const items = useNotificationStore((state) => state.items);
  const clear = useNotificationStore((state) => state.clear);
  const logsOpen = useUiStore((state) => state.logsOpen);
  const soundBlocked = useUiStore((state) => state.soundBlocked);
  const soundEnabled = useUiStore((state) => state.soundEnabled);
  const reduceMotion = useReducedMotion();
  const [hidden, setHidden] = useState(() => document.visibilityState !== "visible");

  useEffect(() => {
    const handle = () => setHidden(document.visibilityState !== "visible");
    document.addEventListener("visibilitychange", handle);
    return () => document.removeEventListener("visibilitychange", handle);
  }, []);

  const { visible, overflow } = splitVisible(items);

  return (
    <section className={styles.region} data-logs-open={logsOpen || undefined} aria-label="Notifications" aria-live="polite">
      <AnimatePresence initial={false}>
        {overflow > 0 && (
          <motion.div
            key="overflow"
            className={styles.overflow}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
          >
            <span>
              +{overflow} earlier notification{overflow === 1 ? "" : "s"}
            </span>
            <button type="button" onClick={clear}>
              Clear all
            </button>
          </motion.div>
        )}
        {soundEnabled && soundBlocked && (
          <motion.div key="sound" className={styles.overflow} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <span>Sound is blocked until you click anywhere on the page.</span>
          </motion.div>
        )}
        {visible.map((item) => (
          <motion.div
            key={item.id}
            layout={!reduceMotion}
            initial={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 28, scale: 0.98 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 20, transition: { duration: 0.18, ease: [0.7, 0, 0.84, 0] } }}
            transition={{ type: "spring", duration: 0.4, bounce: 0 }}
          >
            <NotificationCard item={item} paused={hidden} />
          </motion.div>
        ))}
      </AnimatePresence>
    </section>
  );
}
