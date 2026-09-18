/**
 * Pure worker-state logic: reconciling this browser's Workspace entries with
 * what the backend reports, and deriving what to show for one worker.
 *
 * The backend is the truth about processes. A Workspace entry is this
 * session's record that the operator asked for a worker; it never claims a
 * worker is running unless a status poll said so.
 */

/** A queued ANPR entry only appears after the supervisor's next tick (<=10s). */
export const START_GRACE_MS = 15_000;
/** Consecutive polls a worker must be missing before it is declared gone. */
export const MISSING_POLLS_TO_FAIL = 3;
/** A worker that ran at least this long ended, rather than failed to start. */
export const HEALTHY_RUN_MS = 20_000;
/** Telemetry older than this means the detector stopped producing frames. */
export const STALE_TELEMETRY_S = 15;
/** Running this long with no first frame is worth telling the operator about. */
export const FIRST_FRAME_WARN_MS = 75_000;

const ACTIVE_PHASES = new Set(["starting", "running", "queued", "stopping"]);

export function isActivePhase(phase) {
  return ACTIVE_PHASES.has(phase);
}

/**
 * @param {Record<string, object>} entries  Workspace entries keyed by id
 * @param {Map<string, object>} rowsById   backend status rows keyed by worker id
 * @param {number} now                     epoch ms
 * @returns {Record<string, object>}       next entries (same object if unchanged)
 */
export function reconcileEntries(entries, rowsById, now) {
  let changed = false;
  const next = {};

  for (const [id, entry] of Object.entries(entries)) {
    if (entry.inFlight) {
      next[id] = entry;
      continue;
    }
    const row = rowsById.get(id);
    const updated = reconcileOne(entry, row, now);
    if (updated === null) {
      changed = true;
      continue;
    }
    if (updated !== entry) changed = true;
    next[id] = updated;
  }

  return changed ? next : entries;
}

function reconcileOne(entry, row, now) {
  switch (entry.phase) {
    case "stopping":
      return row ? entry : null;

    case "starting":
    case "running":
    case "queued": {
      if (row?.state === "running") {
        const startedMs = Date.parse(row.started_at);
        const seenRunning = entry.seenRunning || (Number.isFinite(startedMs) && now - startedMs >= HEALTHY_RUN_MS);
        if (
          entry.phase === "running" &&
          entry.backendStartedAt === row.started_at &&
          entry.seenRunning === seenRunning &&
          entry.missingPolls === 0 &&
          !entry.error
        ) {
          return entry;
        }
        return {
          ...entry,
          phase: "running",
          backendStartedAt: row.started_at,
          pid: row.pid,
          seenRunning,
          missingPolls: 0,
          queuePosition: null,
          lastError: null,
          error: null,
        };
      }
      if (row?.state === "queued") {
        if (
          entry.phase === "queued" &&
          entry.queuePosition === row.queue_position &&
          entry.lastError === (row.last_error ?? null) &&
          entry.missingPolls === 0
        ) {
          return entry;
        }
        return {
          ...entry,
          phase: "queued",
          queuePosition: row.queue_position ?? null,
          lastError: row.last_error ?? null,
          missingPolls: 0,
        };
      }
      // Absent from the backend's view.
      const missingPolls = (entry.missingPolls ?? 0) + 1;
      const withinGrace = entry.phase !== "running" && now - (entry.requestedAt ?? 0) < START_GRACE_MS;
      if (withinGrace || missingPolls < MISSING_POLLS_TO_FAIL) {
        return { ...entry, missingPolls };
      }
      if (entry.seenRunning) {
        return {
          ...entry,
          phase: "ended",
          missingPolls,
          endedAt: now,
          error: "Stopped unexpectedly. The worker process is no longer running.",
        };
      }
      return {
        ...entry,
        phase: "failed",
        missingPolls,
        endedAt: now,
        error: "The worker exited while starting. Check the AI worker log for this camera.",
      };
    }

    case "failed":
    case "ended":
      // A supervisor restart (ANPR) can bring it back on its own.
      if (row?.state === "running" || row?.state === "queued") {
        return reconcileOne({ ...entry, phase: row.state, error: null, missingPolls: 0 }, row, now);
      }
      return entry;

    default:
      return entry;
  }
}

/**
 * What to show for one worker.
 *
 * @param {object|null} entry      Workspace entry, if this session has one
 * @param {object|null} row        backend status row, if any
 * @param {object|null|undefined} telemetry  null = fetched, none published;
 *                                 undefined = not being watched
 * @param {number} now             epoch ms
 */
export function deriveWorkerView(entry, row, telemetry, now) {
  if (entry?.phase === "stopping") {
    return view("stopping", "pending", "Stopping", "Terminating the worker process");
  }

  if (!row && entry && entry.phase === "failed") {
    return view("failed", "critical", "Failed to start", entry.error);
  }
  if (!row && entry && entry.phase === "ended") {
    return view("ended", "critical", "Stopped", entry.error);
  }

  if (row?.state === "queued" || (!row && entry?.phase === "queued")) {
    const position = row?.queue_position ?? entry?.queuePosition;
    const lastError = row?.last_error ?? entry?.lastError;
    return view(
      "queued",
      "pending",
      position ? `Queued · #${position}` : "Queued",
      lastError ? `Retrying after a failed start: ${lastError}` : "Waiting for a free worker slot",
    );
  }

  if (row?.state === "running") {
    const startedMs = Date.parse(row.started_at);
    const uptime = Number.isFinite(startedMs) ? Math.max(0, (now - startedMs) / 1000) : null;
    if (telemetry === undefined) {
      return { ...view("running", "live", "Running", null), uptime };
    }
    const updatedMs = telemetry ? telemetry.updated_at * 1000 : null;
    // Ignore a status file left behind by an earlier run of this worker
    // (a killed process on Windows never cleans its telemetry up).
    const fresh = updatedMs != null && Number.isFinite(startedMs) && updatedMs >= startedMs - 1_000;
    if (!fresh) {
      const slow = Number.isFinite(startedMs) && now - startedMs > FIRST_FRAME_WARN_MS;
      return {
        ...view(
          "warming",
          "pending",
          "Starting",
          slow ? "No frames yet. The stream may be unreachable." : "Loading the model and connecting to the stream",
        ),
        uptime,
      };
    }
    const age = Math.max(0, now / 1000 - telemetry.updated_at);
    if (age > STALE_TELEMETRY_S) {
      return { ...view("stalled", "pending", "Stalled", `No new frames for ${Math.round(age)}s`), uptime, telemetry };
    }
    return {
      ...view("live", "live", "Live", null),
      pulse: true,
      uptime,
      fps: telemetry.fps ?? null,
      lag: telemetry.stream_lag_seconds ?? null,
      telemetry,
    };
  }

  if (entry?.phase === "starting" || entry?.phase === "running") {
    return view("starting", "pending", "Starting", "Launching the worker");
  }

  return view("idle", "idle", "Off", null);
}

function view(state, tone, label, detail) {
  return { state, tone, label, detail, pulse: false, uptime: null, fps: null, lag: null, telemetry: null };
}

/** States in which a worker counts as present in the Workspace. */
export function isPresent(viewState) {
  return viewState !== "idle";
}
