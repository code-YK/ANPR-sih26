import { Fragment, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { MapPinOff, Search } from "lucide-react";

import { api } from "../../api.js";
import ExportMenu from "../../components/ExportMenu.jsx";
import PlateChip from "../../components/PlateChip.jsx";
import RouteMap from "../../components/RouteMap.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";

function fmtDateTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return "—";
  }
}

function fmtDuration(totalSeconds) {
  if (totalSeconds == null || !Number.isFinite(totalSeconds)) return "—";
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, "0")}m`;
}

function fmtGap(fromIso, toIso) {
  const seconds = Math.round((new Date(toIso) - new Date(fromIso)) / 1000);
  if (!Number.isFinite(seconds)) return null;
  if (seconds < 0) return "out of order";
  return `${fmtDuration(seconds)} later`;
}

function humanize(value) {
  if (!value) return "";
  return String(value).replace(/_/g, " ");
}

function PlateTitle({ plate }) {
  if (!plate) return null;
  return <PlateChip plate={plate} className="journey-plate-title" />;
}

export default function JourneyView() {
  const { plate: routePlate } = useParams();
  usePageTitle(routePlate ? `Journey · ${routePlate}` : "Journeys");
  const navigate = useNavigate();
  const [searchValue, setSearchValue] = useState(routePlate ?? "");
  const [journey, setJourney] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hoveredIndex, setHoveredIndex] = useState(null);
  const [coverage, setCoverage] = useState(null);

  useEffect(() => {
    api("/cameras")
      .then((cams) =>
        setCoverage({
          viable: cams.filter((c) => c.anpr_viable === true).length,
          total: cams.length,
        }),
      )
      .catch(() => {});
  }, []);

  useEffect(() => {
    setSearchValue(routePlate ?? "");
    if (!routePlate) {
      setJourney(null);
      setError("");
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    api(`/vehicles/${encodeURIComponent(routePlate)}/journey`)
      .then((data) => {
        if (!cancelled) setJourney(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setJourney(null);
          setError(err.message || "Could not load journey");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [routePlate]);

  function submit(event) {
    event.preventDefault();
    const plate = searchValue.trim().toUpperCase().replace(/\s+/g, "");
    if (!plate) return;
    navigate(`/journey/${encodeURIComponent(plate)}`);
  }

  const stops = journey?.stops ?? [];
  const hasQuery = Boolean(routePlate);
  const hasResults = stops.length > 0;

  const spanSeconds = useMemo(() => {
    if (!journey?.first_seen || !journey?.last_seen) return null;
    return (new Date(journey.last_seen) - new Date(journey.first_seen)) / 1000;
  }, [journey?.first_seen, journey?.last_seen]);

  const cameraCount =
    journey?.camera_count ?? (hasResults ? new Set(stops.map((s) => s.camera_id)).size : 0);
  const sightingCount = journey?.sighting_count ?? stops.length;

  return (
    <section className="journey-page">
      <header className="journey-page-header">
        <div className="journey-page-header-main">
          <p className="journey-eyebrow">Trajectory</p>
          {hasQuery ? (
            <h1 className="journey-page-title">
              <PlateTitle plate={routePlate} />
            </h1>
          ) : (
            <h1 className="journey-page-title-text">Journeys</h1>
          )}
          <p className="journey-lead">
            {hasQuery
              ? `Built from confirmed reads${
                  coverage ? ` · ${coverage.viable} of ${coverage.total} cameras can read plates.` : "."
                }`
              : "Enter a registration mark to rebuild its path from camera reads."}
          </p>
        </div>
        {hasResults && (
          // The backend's own export, in all four formats it serves. This was a
          // CSV assembled here in the browser -- a second implementation that
          // could drift from the one the API and the other formats share.
          <ExportMenu path={`/vehicles/${encodeURIComponent(journey.plate)}/journey/export`} />
        )}
      </header>

      <form className="journey-search" onSubmit={submit}>
        <label className="journey-search-field">
          <Search size={16} strokeWidth={2} aria-hidden="true" />
          <input
            value={searchValue}
            onChange={(e) => setSearchValue(e.target.value.toUpperCase())}
            placeholder="Plate number, e.g. GJ01AB1234"
            aria-label="Number plate"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <button type="submit" className="primary journey-trace-btn" disabled={!searchValue.trim()}>
          Trace
        </button>
      </form>

      {!hasQuery && (
        <div className="journey-idle">
          <p>Trace a vehicle across cameras. Enter a plate to see every confirmed read in order, with gaps and the route on a map.</p>
        </div>
      )}

      {hasQuery && loading && (
        <div className="journey-loading">
          Reconstructing trail for <strong>{routePlate}</strong>…
        </div>
      )}

      {hasQuery && error && (
        <div className="journey-error" role="alert">
          {error}
        </div>
      )}

      {hasQuery && !loading && !error && journey && !hasResults && (
        <div className="journey-none">
          <strong>No confirmed reads for {routePlate}</strong>
          <p>Try another plate or start ANPR on more cameras.</p>
        </div>
      )}

      {hasQuery && hasResults && (
        <>
          <dl className="journey-stats">
            <div>
              <dt>Sightings</dt>
              <dd>{sightingCount}</dd>
            </div>
            <div>
              <dt>Cameras</dt>
              <dd>{cameraCount}</dd>
            </div>
            <div>
              <dt>First seen</dt>
              <dd className="journey-stats-small">{fmtDateTime(journey.first_seen)}</dd>
            </div>
            <div>
              <dt>Last seen</dt>
              <dd className="journey-stats-small">{fmtDateTime(journey.last_seen)}</dd>
            </div>
            <div>
              <dt>Span</dt>
              <dd className="journey-stats-small">{fmtDuration(spanSeconds)}</dd>
            </div>
          </dl>

          {journey.restricted_stops > 0 && (
            <p className="journey-notice">
              {journey.restricted_stops} more stop{journey.restricted_stops === 1 ? " is" : "s are"} hidden
              outside your access grants.
            </p>
          )}

          <div className="journey-layout">
            <ol className="journey-timeline">
              {stops.map((s, i) => (
                <Fragment key={s.sighting_id || `${s.camera_id}-${s.seen_at}-${i}`}>
                  {i > 0 && (
                    <li className="journey-gap" aria-hidden="true">
                      {fmtGap(stops[i - 1].seen_at, s.seen_at)}
                    </li>
                  )}
                  <li
                    className={`journey-stop${hoveredIndex === i ? " is-hot" : ""}`}
                    onMouseEnter={() => setHoveredIndex(i)}
                    onMouseLeave={() => setHoveredIndex(null)}
                  >
                    <span className="journey-stop-seq">{i + 1}</span>
                    <div className="journey-stop-body">
                      <div className="journey-stop-top">
                        <strong>{s.camera_name}</strong>
                        <time dateTime={s.seen_at}>{fmtDateTime(s.seen_at)}</time>
                      </div>
                      <p className="journey-stop-loc">{s.location_text || "Location unknown"}</p>
                      <p className="journey-stop-meta">
                        {s.department ?? "—"}
                        {" · "}
                        {humanize(s.vehicle_type) || "vehicle"}
                        {s.confidence != null && (
                          <>
                            {" · confidence "}
                            <span className="mono">{Number(s.confidence).toFixed(2)}</span>
                          </>
                        )}
                        {(s.latitude == null || s.longitude == null) && (
                          <span className="journey-unplaced">
                            <MapPinOff size={12} strokeWidth={2} /> not on map
                          </span>
                        )}
                      </p>
                    </div>
                  </li>
                </Fragment>
              ))}
            </ol>

            <div className="journey-map-wrap">
              <div className="route-map-container">
                <RouteMap stops={stops} hoveredIndex={hoveredIndex} onHover={setHoveredIndex} />
              </div>
              {journey.unplaced_stops > 0 && (
                <p className="journey-map-note">
                  {journey.unplaced_stops} stop{journey.unplaced_stops === 1 ? "" : "s"} not shown — camera
                  location unknown.
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
