import { useQuery } from "@tanstack/react-query";
import { MapPinOff, Route as RouteIcon, Search } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, Polyline, Popup, useMap } from "react-leaflet";
import { useNavigate, useParams } from "react-router-dom";

import { DarkTileLayer, DEFAULT_CENTER, MAP_COLORS, numberedIcon } from "../../components/map/MapBase.jsx";
import { Page, PageHeader } from "../../components/Page.jsx";
import { Button, EmptyState, Input, Notice, PlateChip, Skeleton } from "../../components/ui.jsx";
import { api, isStatus } from "../../lib/api/client.js";
import { evidenceUrl } from "../../lib/api/media.js";
import { fmtConfidence, fmtDateTime, fmtDuration, humanize } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { useCameras } from "../../lib/queries.js";
import { ExportMenu } from "../live/events/shared.jsx";
import styles from "./Journey.module.css";

function gapLabel(fromIso, toIso) {
  const seconds = (new Date(toIso) - new Date(fromIso)) / 1000;
  if (!Number.isFinite(seconds)) return null;
  if (seconds < 0) return "out of order";
  return `${fmtDuration(seconds)} later`;
}

function FitBounds({ positions }) {
  const map = useMap();
  const key = JSON.stringify(positions);
  useEffect(() => {
    if (positions.length === 0) return;
    if (positions.length === 1) map.setView(positions[0], 15);
    else map.fitBounds(positions, { padding: [40, 40] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return null;
}

function RouteMap({ stops, hovered, onHover }) {
  const placed = stops.map((stop, index) => ({ ...stop, index })).filter((stop) => stop.latitude != null && stop.longitude != null);
  const positions = placed.map((stop) => [stop.latitude, stop.longitude]);
  return (
    <MapContainer center={DEFAULT_CENTER} zoom={7} className={styles.map} scrollWheelZoom>
      <DarkTileLayer />
      <FitBounds positions={positions} />
      {positions.length > 1 && <Polyline positions={positions} pathOptions={{ color: MAP_COLORS.signal, weight: 3, opacity: 0.85 }} />}
      {placed.map((stop) => (
        <Marker
          key={stop.sighting_id}
          position={[stop.latitude, stop.longitude]}
          icon={numberedIcon(stop.index + 1, hovered === stop.index)}
          eventHandlers={{ mouseover: () => onHover(stop.index), mouseout: () => onHover(null) }}
        >
          <Popup>
            <strong>
              {stop.index + 1}. {stop.camera_name}
            </strong>
            {stop.location_text}
            <br />
            {fmtDateTime(stop.seen_at)}
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}

export default function JourneyView() {
  const { plate } = useParams();
  usePageTitle(plate ? `Journey · ${plate}` : "Journeys");
  const navigate = useNavigate();
  const [value, setValue] = useState(plate ?? "");
  const [hovered, setHovered] = useState(null);
  const cameras = useCameras();

  useEffect(() => setValue(plate ?? ""), [plate]);

  const journey = useQuery({
    queryKey: ["journey", plate],
    queryFn: () => api(`/vehicles/${encodeURIComponent(plate)}/journey`),
    enabled: Boolean(plate),
    refetchInterval: 15_000,
  });

  const coverage = useMemo(() => {
    const list = cameras.data ?? [];
    return { viable: list.filter((camera) => camera.anpr_viable === true).length, total: list.length };
  }, [cameras.data]);

  const data = journey.data;
  const stops = data?.stops ?? [];
  const span = data?.first_seen && data?.last_seen ? (new Date(data.last_seen) - new Date(data.first_seen)) / 1000 : null;

  return (
    <Page>
      <PageHeader
        overline="Trajectory"
        title={plate ? <PlateChip plate={plate} size="lg" /> : "Journeys"}
        description={coverage.total ? `Built from confirmed reads · ${coverage.viable} of ${coverage.total} cameras can read plates.` : "Built from confirmed plate reads."}
        actions={plate && stops.length > 0 && <ExportMenu path={`/vehicles/${encodeURIComponent(plate)}/journey/export`} />}
      />

      <form
        className={styles.search}
        onSubmit={(event) => {
          event.preventDefault();
          const next = value.trim().toUpperCase().replace(/\s+/g, "");
          if (next) navigate(`/journeys/${encodeURIComponent(next)}`);
        }}
      >
        <div className="ui-search">
          <Search aria-hidden="true" />
          <Input value={value} onChange={(event) => setValue(event.target.value)} placeholder="Plate number, e.g. GJ01AB1234" aria-label="Plate number" autoCapitalize="characters" />
        </div>
        <Button type="submit" variant="primary">
          Trace
        </Button>
      </form>

      {!plate ? (
        <div className="ui-card">
          <EmptyState icon={<RouteIcon />} title="Trace a vehicle across cameras">
            Enter a plate to see every camera that confirmed it, in order, with the time between each stop and the route on a map.
          </EmptyState>
        </div>
      ) : journey.isPending ? (
        <Skeleton height={420} />
      ) : journey.isError ? (
        <Notice tone="critical">{isStatus(journey.error, 404) ? "No journey data." : journey.error.message}</Notice>
      ) : stops.length === 0 ? (
        <div className="ui-card">
          <EmptyState icon={<RouteIcon />} title="No confirmed sightings for this plate">
            It hasn't been read with confidence by any camera you can view. Check the plate, or start ANPR on more cameras.
          </EmptyState>
        </div>
      ) : (
        <>
          <dl className={styles.stats}>
            <div>
              <dt>Sightings</dt>
              <dd>{data.sighting_count}</dd>
            </div>
            <div>
              <dt>Cameras</dt>
              <dd>{data.camera_count}</dd>
            </div>
            <div>
              <dt>First seen</dt>
              <dd className={styles.statSmall}>{fmtDateTime(data.first_seen)}</dd>
            </div>
            <div>
              <dt>Last seen</dt>
              <dd className={styles.statSmall}>{fmtDateTime(data.last_seen)}</dd>
            </div>
            <div>
              <dt>Span</dt>
              <dd className={styles.statSmall}>{fmtDuration(span)}</dd>
            </div>
          </dl>

          {data.restricted_stops > 0 && (
            <Notice tone="pending">
              {data.restricted_stops} more stop{data.restricted_stops === 1 ? " is" : "s are"} hidden because {data.restricted_stops === 1 ? "its department is" : "their departments are"} outside your access.
            </Notice>
          )}

          <div className={styles.layout}>
            <ol className={styles.timeline}>
              {stops.map((stop, index) => (
                <Fragment key={stop.sighting_id}>
                  {index > 0 && (
                    <li className={styles.gap} aria-hidden="true">
                      {gapLabel(stops[index - 1].seen_at, stop.seen_at)}
                    </li>
                  )}
                  <li className={styles.stop} data-active={hovered === index || undefined} onMouseEnter={() => setHovered(index)} onMouseLeave={() => setHovered(null)}>
                    <span className={styles.stopNumber}>{index + 1}</span>
                    <div className={styles.stopBody}>
                      <div className={styles.stopHead}>
                        <span className={styles.stopCamera}>{stop.camera_name}</span>
                        <time className="data faint">{fmtDateTime(stop.seen_at)}</time>
                      </div>
                      <span className="faint">{stop.location_text}</span>
                      <span className={styles.stopMeta}>
                        {stop.department ?? "—"} · {humanize(stop.vehicle_type) || "vehicle"} · confidence <span className="tabular">{fmtConfidence(stop.confidence)}</span>
                        {(stop.latitude == null || stop.longitude == null) && (
                          <span className={styles.unplaced}>
                            <MapPinOff aria-hidden="true" /> not on map
                          </span>
                        )}
                      </span>
                    </div>
                    {stop.has_evidence && <img className={styles.evidence} src={evidenceUrl(stop.sighting_id)} alt="" loading="lazy" onError={(event) => (event.currentTarget.style.display = "none")} />}
                  </li>
                </Fragment>
              ))}
            </ol>
            <div className={styles.mapWrap}>
              <RouteMap stops={stops} hovered={hovered} onHover={setHovered} />
              {data.unplaced_stops > 0 && (
                <p className={styles.mapNote}>
                  {data.unplaced_stops} stop{data.unplaced_stops === 1 ? "" : "s"} not shown — camera location unknown.
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </Page>
  );
}
