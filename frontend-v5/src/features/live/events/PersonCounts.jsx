import { Users } from "lucide-react";
import { memo, useMemo } from "react";

import { EmptyState, Skeleton } from "../../../components/ui.jsx";
import { fmtClock } from "../../../lib/format.js";
import { useCameraCounts } from "../../../lib/queries.js";
import { EventsHeader, useFreshIds, useRegisterPanel } from "./shared.jsx";
import styles from "./Events.module.css";

function PersonCounts({ camera, variant }) {
  useRegisterPanel(`${camera.camera_id}::person`);
  const counts = useCameraCounts(camera.camera_id);
  const windows = useMemo(() => (counts.data ?? []).filter((row) => row.mode === "person"), [counts.data]);
  const fresh = useFreshIds(counts.data ? windows : null);

  const recent = windows.slice(0, 24).reverse();
  const peak = Math.max(1, ...recent.map((row) => row.unique_tracks));

  return (
    <>
      <EventsHeader title="Counts" count={windows.length || null} />
      {counts.isPending ? (
        <Skeleton height={120} />
      ) : windows.length === 0 ? (
        <EmptyState compact icon={<Users />} title="No count windows yet">
          The person worker records how many distinct people it tracked every 30 seconds.
        </EmptyState>
      ) : (
        <>
          <div
            className={styles.bars}
            role="img"
            aria-label={`People per 30-second window, last ${recent.length} windows, peak ${peak}`}
          >
            {recent.map((row) => (
              <span key={row.id} className={styles.bar} style={{ height: `${Math.max(4, (row.unique_tracks / peak) * 100)}%` }} title={`${fmtClock(row.window_start)} · ${row.unique_tracks} people`} />
            ))}
          </div>
          <ul className={styles.list} data-variant={variant}>
              {windows.map((row) => (
                <li key={row.id}>
                  <div className={styles.row} data-static data-fresh={fresh.has(row.id) || undefined}>
                    <span className={`${styles.thumb} ${styles.thumbEmpty}`} aria-hidden="true">
                      <Users />
                    </span>
                    <span className={styles.rowMain}>
                      <span className={styles.rowTitle}>
                        <span className="tabular">{row.unique_tracks}</span> {row.unique_tracks === 1 ? "person" : "people"}
                      </span>
                      <span className={styles.rowMeta}>
                        Peak <span className="tabular">{row.peak_concurrent}</span> at once
                      </span>
                    </span>
                    <span className={styles.time}>
                      {fmtClock(row.window_start)}–{fmtClock(row.window_end)}
                    </span>
                  </div>
                </li>
              ))}
          </ul>
        </>
      )}
    </>
  );
}

export default memo(PersonCounts);
