import { ArrowLeft, ChevronLeft, ChevronRight, Cpu, Info, ScanLine } from "lucide-react";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Badge, Button, EmptyState, IconButton, PlateChip, Skeleton, StatusDot, Tooltip } from "../../components/ui.jsx";
import { fmtClock } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { canAdminCamera, canOperateCamera } from "../../lib/permissions.js";
import { useCameraSightings } from "../../lib/queries.js";
import { useUiStore } from "../../lib/uiStore.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { toast } from "../notifications/notificationStore.js";
import { dismissWorker, ensureWorker, startWorker } from "../workers/lifecycle.js";
import { BACKEND_LABEL, MODE_KEYS, MODES, workerId } from "../workers/modes.js";
import { useCameraEntries, useHasActiveSessionWorkers, useStatusRows } from "../workers/useWorkers.js";
import { deriveWorkerView, isActivePhase } from "../workers/workerState.js";
import { useWorkerStore } from "../workers/workerStore.js";
import CameraFilmstrip from "./CameraFilmstrip.jsx";
import { InferencePanel } from "./InferencePanel.jsx";
import { RawFeed } from "./LiveVideo.jsx";
import ModeBadge from "./ModeBadge.jsx";
import { useLiveCameras } from "./useLiveCameras.js";
import styles from "./Focused.module.css";

const LAYOUT_TRANSITION = { type: "spring", duration: 0.5, bounce: 0 };

function surveyBadge(camera) {
  if (camera.anpr_viable === true) return <Badge tone="live">Plate-readable</Badge>;
  if (camera.anpr_viable === false) return <Badge>Not plate-readable</Badge>;
  return <Badge outline>Not surveyed</Badge>;
}

function CameraFacts({ camera }) {
  const facts = [
    ["Department", camera.department ?? "—"],
    ["Resolution", camera.width && camera.height ? `${camera.width} × ${camera.height}` : "—"],
    ["Frame rate", camera.fps ? `${Math.round(camera.fps)} fps` : "—"],
    ["Codec", camera.codec ?? "—"],
    ["Type", camera.camera_type ?? "—"],
  ];
  return (
    <section className={`ui-card ${styles.facts}`} aria-label="Camera details">
      <dl>
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <div className={styles.factBadges}>{surveyBadge(camera)}</div>
    </section>
  );
}

function AiInferenceCard({ camera, rowsById, onStart, permission, buttonRef }) {
  const elsewhere = MODE_KEYS.map((modeKey) => rowsById.get(workerId(camera.camera_id, modeKey))).filter(Boolean);
  const baseline = rowsById.get(workerId(camera.camera_id, "anpr-baseline"));
  return (
    <section className={styles.aiCard} aria-labelledby="ai-card-title">
      <div className={styles.aiCardIcon} aria-hidden="true">
        <ScanLine />
      </div>
      <h2 id="ai-card-title">AI Inference</h2>
      <p className={styles.aiCardLead}>
        Run the fine-tuned ANPR model on this feed, then add person and suspicious-activity detection from the tabs.
      </p>
      <ul className={styles.aiModes}>
        {MODE_KEYS.map((modeKey) => {
          const row = rowsById.get(workerId(camera.camera_id, modeKey));
          return (
            <li key={modeKey}>
              <StatusDot tone={row ? (row.state === "queued" ? "pending" : "live") : "idle"} />
              <span className={styles.aiModeName}>{MODES[modeKey].label}</span>
              <span className={styles.aiModeDesc}>{row ? (row.state === "queued" ? "queued" : "running") : MODES[modeKey].title}</span>
            </li>
          );
        })}
      </ul>
      <Tooltip content={permission.allowed ? null : permission.reason}>
        <span className={styles.aiCardAction}>
          <Button ref={buttonRef} variant="primary" size="lg" icon={<Cpu />} onClick={onStart} disabled={!permission.allowed}>
            {elsewhere.length ? "Open AI Inference" : "Start AI Inference"}
          </Button>
        </span>
      </Tooltip>
      <p className={styles.aiCardFoot}>
        {baseline
          ? `${BACKEND_LABEL.vehicle} is running here; starting ANPR replaces it.`
          : "Workers keep running until you stop them in Workspace."}
      </p>
    </section>
  );
}

function EarlierSightings({ camera }) {
  const sightings = useCameraSightings(camera.camera_id, { interval: 20_000, limit: 6 });
  const rows = sightings.data ?? [];
  if (!rows.length) return null;
  return (
    <section className={`ui-card ${styles.earlier}`} aria-label="Recent sightings">
      <h3>Recent sightings</h3>
      <ul>
        {rows.map((sighting) => (
          <li key={sighting.id}>
            <PlateChip plate={sighting.plate} />
            <time className="data faint">{fmtClock(sighting.seen_at)}</time>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function FocusedCameraView() {
  const { cameraId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { cameras, allCameras, isLoading, governmentMode, demoMode } = useLiveCameras();
  const camera = allCameras.find((item) => item.camera_id === cameraId) ?? null;
  usePageTitle(camera?.name ?? "Camera");

  const { rows, rowsById } = useStatusRows();
  const entries = useCameraEntries(cameraId);
  const hasActive = useHasActiveSessionWorkers(cameraId);
  const sheetOpen = useUiStore((state) => state.sheetCameraId === cameraId);
  const storedTab = useUiStore((state) => state.activeTab[cameraId]);
  const openSheet = useUiStore((state) => state.openSheet);
  const closeSheet = useUiStore((state) => state.closeSheet);
  const setActiveTab = useUiStore((state) => state.setActiveTab);

  const urlTab = searchParams.get("ai");
  const activeMode = MODE_KEYS.includes(storedTab)
    ? storedTab
    : MODE_KEYS.includes(urlTab)
      ? urlTab
      : (entries.find((entry) => isActivePhase(entry.phase))?.mode ?? "anpr");

  const layout = sheetOpen ? "sheet" : hasActive ? "docked" : "plain";

  const triggerRef = useRef(null);
  const headingRef = useRef(null);
  const aiButtonRef = useRef(null);

  const aiCameraIds = useMemo(() => new Set(rows.map((row) => row.camera_id)), [rows]);
  const index = cameras.findIndex((item) => item.camera_id === cameraId);
  const previous = index > 0 ? cameras[index - 1] : null;
  const next = index >= 0 && index < cameras.length - 1 ? cameras[index + 1] : null;

  const canStartMode = useCallback(
    (modeKey) => {
      if (!camera) return { allowed: false, reason: "Camera not found" };
      if (!camera.analytics_stream_available) {
        return { allowed: false, reason: "This camera has no HLS or RTSP source a worker can read." };
      }
      if (MODES[modeKey].requiresCameraAdmin && !canAdminCamera(user, camera)) {
        return { allowed: false, reason: "ANPR is switched on in the camera's settings, which needs camera administrator access." };
      }
      if (!canOperateCamera(user, camera)) {
        return { allowed: false, reason: "Operator clearance for this camera's department is required." };
      }
      return { allowed: true, reason: null };
    },
    [camera, user],
  );

  const setTab = useCallback(
    (modeKey) => {
      setActiveTab(cameraId, modeKey);
      setSearchParams(
        (params) => {
          const nextParams = new URLSearchParams(params);
          nextParams.set("ai", modeKey);
          return nextParams;
        },
        { replace: true },
      );
    },
    [cameraId, setActiveTab, setSearchParams],
  );

  const requestMode = useCallback(
    (modeKey) => {
      if (!camera) return;
      const permission = canStartMode(modeKey);
      const id = workerId(camera.camera_id, modeKey);
      const entry = useWorkerStore.getState().entries[id] ?? null;
      const state = deriveWorkerView(entry, rowsById.get(id) ?? null, undefined, Date.now()).state;
      if (state !== "idle") return;
      if (!permission.allowed) {
        toast(`Can't start ${MODES[modeKey].label}`, { tone: "critical", detail: permission.reason });
        return;
      }
      ensureWorker(camera, modeKey, rowsById);
    },
    [camera, canStartMode, rowsById],
  );

  const selectMode = useCallback(
    (modeKey) => {
      setTab(modeKey);
      // Choosing a mode's tab is the request to run it.
      requestMode(modeKey);
    },
    [setTab, requestMode],
  );

  const startInference = useCallback(() => {
    triggerRef.current = aiButtonRef.current;
    const firstRunning = MODE_KEYS.find((modeKey) => rowsById.get(workerId(cameraId, modeKey)));
    const modeKey = storedTab ?? firstRunning ?? "anpr";
    setTab(modeKey);
    openSheet(cameraId);
    requestMode(modeKey);
  }, [cameraId, openSheet, requestMode, rowsById, setTab, storedTab]);

  const expand = useCallback(() => {
    triggerRef.current = document.activeElement;
    openSheet(cameraId);
  }, [cameraId, openSheet]);

  const close = useCallback(() => {
    closeSheet();
    requestAnimationFrame(() => {
      const target = triggerRef.current;
      if (target && document.contains(target)) target.focus();
    });
  }, [closeSheet]);

  // Focus the sheet when it opens; close it when leaving this camera.
  useEffect(() => {
    if (!sheetOpen) return undefined;
    const id = requestAnimationFrame(() => headingRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [sheetOpen]);

  useEffect(() => {
    return () => {
      if (useUiStore.getState().sheetCameraId === cameraId) useUiStore.getState().closeSheet();
    };
  }, [cameraId]);

  // Keyboard: Esc closes the sheet (never stops a worker); arrows move between cameras.
  useEffect(() => {
    const onKey = (event) => {
      const target = event.target;
      if (target instanceof HTMLElement && (target.isContentEditable || /INPUT|TEXTAREA|SELECT/.test(target.tagName))) return;
      if (document.querySelector("dialog[open]")) return;
      if (event.key === "Escape" && useUiStore.getState().sheetCameraId === cameraId) {
        event.preventDefault();
        close();
        return;
      }
      if (useUiStore.getState().sheetCameraId) return;
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "ArrowLeft" && previous && !target.closest?.('[role="tablist"]')) navigate(`/live/${encodeURIComponent(previous.camera_id)}`);
      if (event.key === "ArrowRight" && next && !target.closest?.('[role="tablist"]')) navigate(`/live/${encodeURIComponent(next.camera_id)}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cameraId, close, navigate, next, previous]);

  if (isLoading) {
    return (
      <div className={styles.page}>
        <Skeleton height={28} width={260} />
        <Skeleton height={480} style={{ marginTop: 24 }} />
      </div>
    );
  }

  if (!camera) {
    return (
      <div className={styles.page}>
        <EmptyState
          icon={<Info />}
          title="Camera not available"
          action={
            <Link to="/live" className="ui-btn ui-btn--secondary">
              Back to cameras
            </Link>
          }
        >
          It may have been removed, or it belongs to a department your account can't view.
        </EmptyState>
      </div>
    );
  }

  const panelProps = {
    camera,
    activeMode,
    onSelectMode: selectMode,
    onStart: requestMode,
    onRetry: (modeKey) => {
      const permission = canStartMode(modeKey);
      if (permission.allowed) startWorker(camera, modeKey);
    },
    onDismiss: (modeKey) => dismissWorker(camera.camera_id, modeKey),
    onClose: close,
    onExpand: expand,
    canStartMode,
  };

  return (
    <div className={styles.page} data-layout={layout}>
      <header className={styles.header}>
        <IconButton label="All cameras" onClick={() => navigate("/live")}>
          <ArrowLeft />
        </IconButton>
        <div className={styles.titleBlock}>
          <p className="overline">
            <span className="data">{camera.camera_id}</span>
            {camera.department && <> · {camera.department}</>}
          </p>
          <h1 className={styles.title}>{camera.name}</h1>
          <p className={styles.location}>{camera.location_text}</p>
        </div>
        <div className={styles.headerAside}>
          <ModeBadge governmentMode={governmentMode} demoMode={demoMode} />
          <div className={styles.pager}>
            <IconButton label="Previous camera (←)" disabled={!previous} onClick={() => previous && navigate(`/live/${encodeURIComponent(previous.camera_id)}`)}>
              <ChevronLeft />
            </IconButton>
            <IconButton label="Next camera (→)" disabled={!next} onClick={() => next && navigate(`/live/${encodeURIComponent(next.camera_id)}`)}>
              <ChevronRight />
            </IconButton>
          </div>
        </div>
      </header>

      <LayoutGroup id={`focus-${cameraId}`}>
        <div className={styles.stage} data-layout={layout}>
          <motion.section layout layoutDependency={layout} transition={LAYOUT_TRANSITION} className={styles.rawCol} aria-label="Camera feed">
            <div className={styles.columnHead}>
              <h2 className={styles.columnTitle}>Camera feed</h2>
              <span className={styles.columnMeta}>
                {camera.width && camera.height ? `${camera.width}×${camera.height}` : ""}
                {camera.fps ? ` · ${Math.round(camera.fps)} fps` : ""}
              </span>
            </div>
            <div className={styles.feed}>
              <RawFeed camera={camera} />
            </div>
            <CameraFilmstrip cameras={cameras} currentId={cameraId} aiCameraIds={aiCameraIds} />
          </motion.section>

          <AnimatePresence mode="popLayout" initial={false}>
            {layout === "plain" ? (
              <motion.aside
                key="side"
                className={styles.side}
                initial={{ opacity: 0, x: 16 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 16, transition: { duration: 0.15 } }}
                transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
              >
                <AiInferenceCard camera={camera} rowsById={rowsById} onStart={startInference} permission={canStartMode("anpr")} buttonRef={aiButtonRef} />
                <CameraFacts camera={camera} />
                <EarlierSightings camera={camera} />
              </motion.aside>
            ) : (
              <motion.section
                key="ai"
                layout
                layoutDependency={layout}
                className={styles.aiCol}
                data-sheet={sheetOpen || undefined}
                role={sheetOpen ? "dialog" : undefined}
                aria-modal={sheetOpen ? "false" : undefined}
                aria-label="AI inference"
                initial={sheetOpen ? { opacity: 0, x: "-18%" } : { opacity: 0 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, transition: { duration: 0.15 } }}
                transition={LAYOUT_TRANSITION}
              >
                <InferencePanel ref={headingRef} variant={sheetOpen ? "sheet" : "docked"} {...panelProps} />
              </motion.section>
            )}
          </AnimatePresence>
        </div>
      </LayoutGroup>

      <AnimatePresence>
        {sheetOpen && (
          <motion.div
            key="scrim"
            className={styles.scrim}
            onClick={close}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
            aria-hidden="true"
          />
        )}
      </AnimatePresence>
    </div>
  );
}
