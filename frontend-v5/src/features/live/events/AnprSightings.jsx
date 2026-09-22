import { Car, ShieldAlert } from "lucide-react";
import { memo, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, Dialog, EmptyState, PlateChip, Skeleton } from "../../../components/ui.jsx";
import { evidenceUrl } from "../../../lib/api/media.js";
import { fmtClock, fmtConfidence, fmtDateTime, humanize } from "../../../lib/format.js";
import { useCameraSightings, useOpenAlerts } from "../../../lib/queries.js";
import { EventsHeader, ExportMenu, useFreshIds, useRegisterPanel } from "./shared.jsx";
import styles from "./Events.module.css";

function Evidence({ sighting, className }) {
  const [failed, setFailed] = useState(false);
  if (!sighting.has_evidence || failed) {
    return (
      <span className={`${styles.thumb} ${styles.thumbEmpty} ${className ?? ""}`} aria-hidden="true">
        <Car />
      </span>
    );
  }
  return (
    <img
      className={`${styles.thumb} ${className ?? ""}`}
      src={evidenceUrl(sighting.id)}
      alt=""
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
    />
  );
}

export function SightingDialog({ sighting, alert, cameraName, onClose }) {
  return (
    <Dialog
      open={Boolean(sighting)}
      onClose={onClose}
      title="Plate sighting"
      description={sighting ? `${cameraName} · ${fmtDateTime(sighting.seen_at)}` : undefined}
      wide
      footer={
        sighting?.plate && (
          <Link to={`/journeys/${encodeURIComponent(sighting.plate)}`} className="ui-btn ui-btn--primary" onClick={onClose}>
            View journey
          </Link>
        )
      }
    >
      {sighting && (
        <div className={styles.detail}>
          {sighting.has_evidence ? (
            <img className={styles.detailImage} src={evidenceUrl(sighting.id)} alt={`Evidence crop for ${sighting.plate}`} />
          ) : (
            <div className={`${styles.detailImage} ${styles.thumbEmpty}`}>No evidence image recorded</div>
          )}
          <div className={styles.detailFacts}>
            <PlateChip plate={sighting.plate} size="lg" />
            {alert && (
              <Badge tone="critical" icon={<ShieldAlert aria-hidden="true" />}>
                Watchlist match{alert.reason_code ? ` · ${humanize(alert.reason_code)}` : ""}
              </Badge>
            )}
            <dl className={styles.facts}>
              <div>
                <dt>Confidence</dt>
                <dd className="data">{fmtConfidence(sighting.confidence)}</dd>
              </div>
              <div>
                <dt>Vehicle</dt>
                <dd>{humanize(sighting.vehicle_type) || "—"}</dd>
              </div>
              <div>
                <dt>Seen (source time)</dt>
                <dd className="data">{fmtDateTime(sighting.seen_at)}</dd>
              </div>
              <div>
                <dt>Raw OCR</dt>
                <dd className="data">{sighting.raw_ocr_text || "—"}</dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd className="data">{sighting.model_version?.split(/[\\/]/).pop() || "—"}</dd>
              </div>
            </dl>
            <p className="faint" style={{ fontSize: "var(--fs-caption)" }}>
              Recorded only after the per-vehicle reading vote confirmed the plate. Evidence images expire after the retention window.
            </p>
          </div>
        </div>
      )}
    </Dialog>
  );
}

function AnprSightings({ camera, variant }) {
  useRegisterPanel(`${camera.camera_id}::anpr`);
  const sightings = useCameraSightings(camera.camera_id);
  const openAlerts = useOpenAlerts();
  const [selected, setSelected] = useState(null);

  const alertsBySighting = useMemo(() => {
    const map = new Map();
    for (const alert of openAlerts.data ?? []) {
      if (alert.sighting_id != null) map.set(alert.sighting_id, alert);
    }
    return map;
  }, [openAlerts.data]);

  const rows = sightings.data ?? null;
  const fresh = useFreshIds(rows);

  return (
    <>
      <EventsHeader title="Sightings" count={rows?.length}>
        <ExportMenu path={`/cameras/${encodeURIComponent(camera.camera_id)}/sightings/export`} />
      </EventsHeader>

      {sightings.isPending ? (
        <div className={styles.list}>
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} height={52} />
          ))}
        </div>
      ) : !rows?.length ? (
        <EmptyState compact icon={<Car />} title="No plates confirmed yet">
          Plates appear here once three frames agree on every character, usually a few seconds after a vehicle passes. Reads still in progress stay on the detector view above, in amber with a “?”, and are never recorded.
        </EmptyState>
      ) : (
        <ul className={styles.list} data-variant={variant}>
            {rows.map((sighting) => {
              const alert = alertsBySighting.get(sighting.id);
              return (
                <li key={sighting.id}>
                  <button
                    type="button"
                    className={styles.row}
                    data-fresh={fresh.has(sighting.id) || undefined}
                    data-alert={alert ? "true" : undefined}
                    onClick={() => setSelected(sighting)}
                  >
                    <Evidence sighting={sighting} />
                    <span className={styles.rowMain}>
                      <PlateChip plate={sighting.plate} />
                      <span className={styles.rowMeta}>
                        {humanize(sighting.vehicle_type) || "vehicle"}
                        <span aria-hidden="true"> · </span>
                        <span className="tabular">{fmtConfidence(sighting.confidence)}</span>
                      </span>
                    </span>
                    {alert && (
                      <Badge tone="critical" icon={<ShieldAlert aria-hidden="true" />}>
                        Watchlist
                      </Badge>
                    )}
                    <time className={styles.time} dateTime={sighting.seen_at}>
                      {fmtClock(sighting.seen_at)}
                    </time>
                  </button>
                </li>
              );
            })}
        </ul>
      )}

      <SightingDialog
        sighting={selected}
        alert={selected ? alertsBySighting.get(selected.id) : null}
        cameraName={camera.name}
        onClose={() => setSelected(null)}
      />
      {sightings.isError && (
        <p className={styles.error}>
          Couldn't refresh sightings.{" "}
          <Button variant="ghost" size="sm" onClick={() => sightings.refetch()}>
            Retry
          </Button>
        </p>
      )}
    </>
  );
}

export default memo(AnprSightings);
