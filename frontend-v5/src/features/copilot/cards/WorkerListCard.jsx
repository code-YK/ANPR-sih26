import { Square } from "lucide-react";
import { useState } from "react";

import { Badge, Button, StatusDot } from "../../../components/ui.jsx";
import { stopBackendWorker } from "../../workers/lifecycle.js";
import styles from "../Copilot.module.css";

/**
 * "List the running workers, with a stop button in place."
 *
 * The Stop button calls the same lifecycle helper the Workspace uses, not
 * the model: clearing the intent column then stopping the process is a
 * sequence that must not be re-derived, and a click is already an explicit
 * operator action, so routing it back through a language model would only
 * add latency and a chance to get it wrong.
 */
export default function WorkerListCard({ data }) {
  const [stopping, setStopping] = useState(() => new Set());
  const workers = data?.workers ?? [];

  if (workers.length === 0) {
    return <p className={styles.cardEmpty}>No analytics workers are running.</p>;
  }

  async function handleStop(worker) {
    const key = `${worker.camera_id}::${worker.backend_mode}`;
    setStopping((previous) => new Set(previous).add(key));
    try {
      await stopBackendWorker({ camera_id: worker.camera_id, mode: worker.backend_mode });
    } finally {
      setStopping((previous) => {
        const next = new Set(previous);
        next.delete(key);
        return next;
      });
    }
  }

  return (
    <ul className={styles.workerList}>
      {workers.map((worker) => {
        const key = `${worker.camera_id}::${worker.backend_mode}`;
        const isStopping = stopping.has(key);
        return (
          <li key={key} className={styles.workerRow}>
            <StatusDot
              tone={worker.running ? "live" : worker.state === "queued" ? "pending" : "idle"}
              pulse={worker.running}
              label={worker.state}
            />
            <div className={styles.workerMeta}>
              <span className={styles.workerCamera}>{worker.camera_id}</span>
              <span className={styles.workerMode}>{worker.mode}</span>
            </div>
            {worker.state === "queued" && worker.queue_position ? (
              <Badge tone="pending" outline>
                queued #{worker.queue_position}
              </Badge>
            ) : null}
            <Button
              size="sm"
              variant="ghost"
              icon={<Square size={14} />}
              disabled={isStopping}
              onClick={() => handleStop(worker)}
            >
              {isStopping ? "Stopping" : "Stop"}
            </Button>
          </li>
        );
      })}
    </ul>
  );
}
