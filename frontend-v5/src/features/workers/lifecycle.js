import { api, isStatus } from "../../lib/api/client.js";
import { keys, queryClient } from "../../lib/queries.js";
import { useUiStore } from "../../lib/uiStore.js";
import { toast } from "../notifications/notificationStore.js";
import { BACKEND_LABEL, MODES, workerId } from "./modes.js";
import { useWorkerStore } from "./workerStore.js";

/**
 * Worker start/stop sequences. Every operation holds a per-worker lock so a
 * double click, a tab switch racing the AI Inference button, or a Workspace
 * stop racing a start can never send overlapping requests for one worker.
 */
const locks = new Map();

function withLock(id, fn) {
  const existing = locks.get(id);
  if (existing) return existing;
  const promise = Promise.resolve()
    .then(fn)
    .finally(() => locks.delete(id));
  locks.set(id, promise);
  return promise;
}

export function isBusy(id) {
  return locks.has(id);
}

function cameraPath(cameraId) {
  return `/cameras/${encodeURIComponent(cameraId)}`;
}

function analyticsPath(action, cameraId, backendMode) {
  return `/analytics/${action}?camera_id=${encodeURIComponent(cameraId)}&mode=${backendMode}`;
}

function patchCamera(updated) {
  if (!updated?.camera_id) return;
  queryClient.setQueryData(keys.cameras, (cameras) =>
    Array.isArray(cameras) ? cameras.map((camera) => (camera.camera_id === updated.camera_id ? updated : camera)) : cameras,
  );
}

async function setIntent(cameraId, column, value) {
  patchCamera(await api(cameraPath(cameraId), { method: "PUT", json: { [column]: value } }));
}

function describeStartError(error, mode) {
  if (isStatus(error, 403)) {
    return mode.requiresCameraAdmin
      ? "Starting ANPR changes this camera's settings, which needs camera administrator access."
      : "Starting this worker needs operator clearance for the camera's department.";
  }
  if (isStatus(error, 429)) {
    const capacity = queryClient.getQueryData(keys.capacity)?.[mode.backendMode];
    return `${mode.label} is at capacity${capacity ? ` (${capacity} workers)` : ""}. Stop one in Workspace first.`;
  }
  return error?.message || "The worker could not be started.";
}

/**
 * Start (or join) one worker. Resolves when the backend has accepted the
 * request; the worker then moves through starting -> live via status polls.
 */
export function startWorker(camera, modeKey) {
  const mode = MODES[modeKey];
  const cameraId = camera.camera_id;
  const id = workerId(cameraId, modeKey);

  return withLock(id, async () => {
    const store = useWorkerStore.getState();
    const wasPresent = Boolean(store.entries[id]);
    store.upsert(id, {
      cameraId,
      mode: modeKey,
      phase: "starting",
      requestedAt: Date.now(),
      error: null,
      inFlight: true,
      missingPolls: 0,
      seenRunning: false,
      backendStartedAt: null,
    });
    if (!wasPresent) useUiStore.getState().flagRecentlyAdded(id);

    try {
      if (mode.intentColumn) {
        // The supervisor reconciles this column; set it before launching or
        // the next tick would stop the worker as unwanted.
        await setIntent(cameraId, mode.intentColumn, true);
        if (mode.conflictBackendMode) {
          // The PUT cleared the baseline model's intent; stop its process now
          // rather than leaving two yolo11x-class workers on one GPU for a tick.
          await api(analyticsPath("stop", cameraId, mode.conflictBackendMode), { method: "POST" }).catch(() => {});
        }
      }

      try {
        const row = await api(analyticsPath("start", cameraId, mode.backendMode), { method: "POST" });
        useWorkerStore.getState().upsert(id, {
          phase: "starting",
          backendStartedAt: row?.started_at ?? null,
          pid: row?.pid ?? null,
          inFlight: false,
        });
      } catch (error) {
        if (isStatus(error, 409)) {
          useWorkerStore.getState().upsert(id, { phase: "starting", inFlight: false });
        } else if (isStatus(error, 429) && mode.queueable) {
          // The intent stays set; the supervisor starts it when a slot frees.
          useWorkerStore.getState().upsert(id, { phase: "queued", inFlight: false, requestedAt: Date.now() });
        } else {
          if (mode.intentColumn) await setIntent(cameraId, mode.intentColumn, false).catch(() => {});
          throw error;
        }
      }
    } catch (error) {
      useWorkerStore.getState().upsert(id, {
        phase: "failed",
        error: describeStartError(error, mode),
        inFlight: false,
        endedAt: Date.now(),
      });
    } finally {
      queryClient.invalidateQueries({ queryKey: keys.status });
    }
  });
}

/** Stop a worker this session is tracking. Removes it once really stopped. */
export function stopWorker(cameraId, modeKey) {
  const mode = MODES[modeKey];
  const id = workerId(cameraId, modeKey);

  return withLock(id, async () => {
    const store = useWorkerStore.getState();
    const previous = store.entries[id];
    store.upsert(id, { cameraId, mode: modeKey, phase: "stopping", inFlight: true, error: null });

    try {
      if (mode.intentColumn) {
        // Clear the intent first: stopping the process alone would be undone
        // by the supervisor's next tick.
        await setIntent(cameraId, mode.intentColumn, false);
      }
      try {
        await api(analyticsPath("stop", cameraId, mode.backendMode), { method: "POST" });
      } catch (error) {
        if (!isStatus(error, 404)) throw error; // 404: already not running
      }
      useWorkerStore.getState().remove(id);
    } catch (error) {
      useWorkerStore.getState().upsert(id, {
        phase: previous && previous.phase !== "stopping" ? previous.phase : "running",
        inFlight: false,
        error: null,
      });
      toast(`Couldn't stop ${mode.label}`, {
        tone: "critical",
        detail: isStatus(error, 403) ? "Stopping ANPR needs camera administrator access." : error.message,
      });
    } finally {
      queryClient.invalidateQueries({ queryKey: keys.status });
    }
  });
}

/**
 * Stop a worker reported by the backend that this session didn't start
 * (another tab, another operator, the legacy baseline model).
 */
export function stopBackendWorker(row) {
  const id = `${row.camera_id}::backend::${row.mode}`;
  return withLock(id, async () => {
    const column =
      row.mode === "vehicle" ? "analytics_enabled" : row.mode === "vehicle_finetuned" ? "analytics_finetuned_enabled" : null;
    try {
      if (column) await setIntent(row.camera_id, column, false);
      await api(analyticsPath("stop", row.camera_id, row.mode), { method: "POST" }).catch((error) => {
        if (!isStatus(error, 404)) throw error;
      });
      toast(`${BACKEND_LABEL[row.mode] ?? row.mode} stopped on ${row.camera_id}`);
    } catch (error) {
      toast(`Couldn't stop ${BACKEND_LABEL[row.mode] ?? row.mode}`, { tone: "critical", detail: error.message });
    } finally {
      queryClient.invalidateQueries({ queryKey: keys.status });
    }
  });
}

/** Track a worker that is already running (started elsewhere) in this Workspace. */
export function adoptWorker(cameraId, modeKey, row) {
  const id = workerId(cameraId, modeKey);
  const store = useWorkerStore.getState();
  if (store.entries[id]) return;
  store.upsert(id, {
    cameraId,
    mode: modeKey,
    phase: row.state === "queued" ? "queued" : "running",
    requestedAt: Date.now(),
    backendStartedAt: row.started_at ?? null,
    pid: row.pid ?? null,
    queuePosition: row.queue_position ?? null,
    seenRunning: true,
    missingPolls: 0,
  });
  useUiStore.getState().flagRecentlyAdded(id);
}

/**
 * The one entry point for "the operator wants this mode on this camera":
 * adopt a worker already running, leave an active one alone, otherwise start.
 */
export function ensureWorker(camera, modeKey, rowsById) {
  const id = workerId(camera.camera_id, modeKey);
  const entry = useWorkerStore.getState().entries[id];
  if (entry && ["starting", "running", "queued", "stopping"].includes(entry.phase)) return Promise.resolve();
  const row = rowsById?.get(id);
  if (row && !entry) {
    adoptWorker(camera.camera_id, modeKey, row);
    return Promise.resolve();
  }
  return startWorker(camera, modeKey);
}

export function dismissWorker(cameraId, modeKey) {
  useWorkerStore.getState().remove(workerId(cameraId, modeKey));
}
