import { useEffect, useRef } from "react";

import { useCameras } from "../../lib/queries.js";
import { notify } from "../notifications/notificationStore.js";
import { MODES } from "./modes.js";
import { useStatusRows } from "./useWorkers.js";
import { useWorkerStore } from "./workerStore.js";

/**
 * Invisible: after every status poll, reconcile this session's Workspace with
 * what is actually running, and tell the operator when a worker they started
 * fails or stops on its own.
 */
export default function WorkerStatusSync() {
  const { rowsById, status } = useStatusRows();
  const cameras = useCameras();
  const cameraNames = useRef(new Map());
  cameraNames.current = new Map((cameras.data ?? []).map((camera) => [camera.camera_id, camera.name]));

  useEffect(() => {
    if (!status.isSuccess) return;
    useWorkerStore.getState().reconcile(rowsById, Date.now());
  }, [status.dataUpdatedAt, status.isSuccess, rowsById]);

  useEffect(() => {
    return useWorkerStore.subscribe((state, previous) => {
      for (const [id, entry] of Object.entries(state.entries)) {
        const before = previous.entries[id];
        if (!before || before.phase === entry.phase) continue;
        if (entry.phase !== "failed" && entry.phase !== "ended") continue;
        const mode = MODES[entry.mode];
        const cameraName = cameraNames.current.get(entry.cameraId) ?? entry.cameraId;
        notify(
          {
            kind: "worker",
            key: `worker:${id}:${entry.endedAt ?? Date.now()}`,
            tone: "critical",
            title: entry.phase === "failed" ? `${mode?.label ?? entry.mode} couldn't start` : `${mode?.label ?? entry.mode} stopped`,
            cameraId: entry.cameraId,
            cameraName,
            detail: entry.error,
            href: `/live/${encodeURIComponent(entry.cameraId)}?ai=${entry.mode}`,
          },
          { silent: true },
        );
      }
    });
  }, []);

  return null;
}
