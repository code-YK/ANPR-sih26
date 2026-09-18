import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useNow } from "../../lib/hooks.js";
import { useAnalyticsStatus, useTelemetry } from "../../lib/queries.js";
import { MODES, rowWorkerId, workerId } from "./modes.js";
import { deriveWorkerView, isActivePhase } from "./workerState.js";
import { selectHasPending, useWorkerStore } from "./workerStore.js";

/** Backend status rows indexed by console worker id. */
export function useStatusRows() {
  const hasPending = useWorkerStore(selectHasPending);
  const status = useAnalyticsStatus({ fast: hasPending });
  const rowsById = useMemo(() => {
    const map = new Map();
    for (const row of status.data ?? []) map.set(rowWorkerId(row), row);
    return map;
  }, [status.data]);
  return { rows: status.data ?? [], rowsById, status };
}

export function useWorkerEntry(cameraId, modeKey) {
  return useWorkerStore((state) => state.entries[workerId(cameraId, modeKey)] ?? null);
}

/** Workspace entries for one camera, in mode order. */
export function useCameraEntries(cameraId) {
  return useWorkerStore(
    useShallow((state) =>
      Object.values(state.entries)
        .filter((entry) => entry.cameraId === cameraId)
        .sort((a, b) => a.addedAt - b.addedAt),
    ),
  );
}

export function useHasActiveSessionWorkers(cameraId) {
  return useWorkerStore((state) =>
    Object.values(state.entries).some((entry) => entry.cameraId === cameraId && isActivePhase(entry.phase)),
  );
}

/**
 * Everything the UI needs to render one worker. Telemetry is polled only when
 * `watchTelemetry` is set -- e.g. for the visible AI viewport -- so a list of
 * workers never turns into one telemetry request per worker per second.
 */
export function useWorkerView(cameraId, modeKey, { watchTelemetry = false, telemetryInterval = 1_000 } = {}) {
  const mode = MODES[modeKey];
  const entry = useWorkerEntry(cameraId, modeKey);
  const { rowsById } = useStatusRows();
  const row = rowsById.get(workerId(cameraId, modeKey)) ?? null;
  const telemetryQuery = useTelemetry(cameraId, mode.backendMode, {
    enabled: watchTelemetry && row?.state === "running",
    interval: telemetryInterval,
  });
  const now = useNow(watchTelemetry ? 1_000 : 5_000);
  const telemetry = watchTelemetry ? (telemetryQuery.data ?? null) : undefined;
  const view = deriveWorkerView(entry, row, telemetry, now);
  return { mode, entry, row, view, now };
}
