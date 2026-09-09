import { Fragment, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../../api.js";
import RouteMap from "../../components/RouteMap.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";

function fmtTime(iso) {
  return new Date(iso).toLocaleString();
}

// The interval between two consecutive sightings is the most
// investigatively interesting number on this screen -- it's what says
// "this vehicle took 40 minutes to cross town" or "these two reads are 3
// seconds apart, so one of them is probably wrong" -- and it was previously
// left for the reader to compute from two wall-clock timestamps.
function fmtGap(fromIso, toIso) {
  const seconds = Math.round((new Date(toIso) - new Date(fromIso)) / 1000);
  if (!Number.isFinite(seconds)) return null;
  if (seconds < 0) return "out of order";
  if (seconds < 60) return `${seconds}s later`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s later`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m later`;
}

// The onward leg departing a stop. Direction is a straight-line bearing
// between two cameras, and the speed is a LOWER bound -- the road distance
// is at least the straight-line distance, so the vehicle cannot have
// averaged less. Rendered with a leading ">=" for exactly that reason: no
// camera here is calibrated, so this must never read as "the speed".
function fmtMovement(movement) {
  if (!movement) return null;
  if (movement.compass == null) return "direction not derivable between these cameras";
  const parts = [`→ ${movement.compass}`];
  if (movement.distance_km != null) parts.push(`${movement.distance_km.toFixed(2)} km`);
  if (movement.min_avg_speed_kmh != null) {
    parts.push(`≥ ${Math.round(movement.min_avg_speed_kmh)} km/h`);
  }
  return parts.join(" · ");
}

const ANOMALY_LABELS = {
  dwell: ["lingered", "Stationary or circling at this camera, within one unbroken stream epoch"],
  loop: ["returned", "Came back to a camera already passed on this trip"],
  implausible_speed: [
    "check data",
    "Transit too fast to be real — likely one plate string misread across two vehicles, or a clock fault",
  ],
};

function anomalyChips(flags) {
  return flags.map((flag) => {
    const [label, title] = ANOMALY_LABELS[flag] ?? [flag, flag];
    return (
      <span key={flag} className="badge badge-warn" title={title}>
        {label}
      </span>
    );
  });
}

function toCsv(journey) {
  const header = [
    "seq", "seen_at", "camera_id", "camera_name", "location_text", "department",
    "confidence", "vehicle_type", "latitude", "longitude", "geocode_confidence",
    "onward_compass", "onward_bearing_deg", "onward_distance_km",
    "onward_min_avg_speed_kmh", "anomaly_flags",
  ];
  const rows = journey.stops.map((s, i) => [
    i + 1, s.seen_at, s.camera_id, s.camera_name, s.location_text, s.department ?? "",
    s.confidence ?? "", s.vehicle_type ?? "", s.latitude ?? "", s.longitude ?? "", s.geocode_confidence ?? "",
    s.movement?.compass ?? "", s.movement?.bearing_deg ?? "", s.movement?.distance_km ?? "",
    s.movement?.min_avg_speed_kmh ?? "", (s.anomaly_flags ?? []).join(" "),
  ]);
  return [header, ...rows]
    .map((row) => row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","))
    .join("\n");
}

function downloadCsv(journey) {
  const blob = new Blob([toCsv(journey)], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `journey-${journey.plate}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function JourneyView() {
  const { plate: routePlate } = useParams();
  // A tab reading "Journey · GJ01AB1234" is worth more than a bare "Journey"
  // once an operator has several plates open at once.
  usePageTitle(routePlate ? `Journey · ${routePlate}` : "Journey");
  const navigate = useNavigate();
  const [searchValue, setSearchValue] = useState(routePlate ?? "");
  const [journey, setJourney] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [hoveredIndex, setHoveredIndex] = useState(null);
  const [coverage, setCoverage] = useState(null);

  // Honesty requirement (§6): state how many registered cameras can read
  // plates at all, so a short route reads as a coverage finding, not a
  // broken feature.
  useEffect(() => {
    api("/cameras")
      .then((cams) => setCoverage({
        viable: cams.filter((c) => c.anpr_viable === true).length,
        total: cams.length,
      }))
      .catch(() => {});
  }, []);

  useEffect(() => {
    setSearchValue(routePlate ?? "");
    if (!routePlate) {
      setJourney(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api(`/vehicles/${encodeURIComponent(routePlate)}/journey`)
      .then((data) => {
        if (!cancelled) setJourney(data);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [routePlate]);

  function onSearch(e) {
    e.preventDefault();
    const value = searchValue.trim();
    if (value) navigate(`/journey/${encodeURIComponent(value)}`);
  }

  return (
    <section className="view active">
      <form className="toolbar" onSubmit={onSearch}>
        <input
          placeholder="Search plate, e.g. TESTPLATE001"
          value={searchValue}
          onChange={(e) => setSearchValue(e.target.value)}
          style={{ maxWidth: 240 }}
        />
        <button type="submit" className="primary">
          Search
        </button>
        {journey && journey.stops.length > 0 && (
          <button type="button" className="secondary" onClick={() => downloadCsv(journey)}>
            Export CSV
          </button>
        )}
      </form>

      {!routePlate && <p className="hint">Search a plate to see its route across cameras.</p>}
      {loading && <p className="hint">Loading…</p>}
      {error && <p className="hint">Error: {error}</p>}

      {journey && (
        <>
          <p className="hint">
            Route built from confirmed plate reads only
            {coverage && ` — ${coverage.viable} of ${coverage.total} registered cameras can read plates at all`}.
            {journey.stops.length === 0
              ? " No sightings found for this plate yet."
              : ` ${journey.sighting_count} sighting(s) across ${journey.camera_count} camera(s), ${fmtTime(
                  journey.first_seen
                )} to ${fmtTime(journey.last_seen)}.`}
          </p>

          {journey.restricted_stops > 0 && (
            <p className="hint restricted-notice">
              {journey.restricted_stops} additional stop(s) are hidden because their departments are outside your grants.
            </p>
          )}

          {journey.unpositioned_legs > 0 && (
            <p className="hint">
              Direction and speed are shown only between exactly-geocoded cameras.{" "}
              {journey.unpositioned_legs} leg(s) could not be positioned, so the vehicle
              was seen to move but the movement cannot be measured.
            </p>
          )}

          {journey.stops.length > 0 && (
            <>
              <div className="journey-layout">
                <table className="timeline">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Time</th>
                      <th>Camera</th>
                      <th>Location</th>
                      <th>Department</th>
                      <th>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {journey.stops.map((s, i) => (
                      <Fragment key={s.sighting_id}>
                        {i > 0 && (
                          // Not aria-hidden: this connector now carries the
                          // direction and minimum speed of the leg, which is
                          // real content, not a decorative separator.
                          <tr className="timeline-gap">
                            <td />
                            <td colSpan={5}>
                              {fmtGap(journey.stops[i - 1].seen_at, s.seen_at)}
                              {fmtMovement(journey.stops[i - 1].movement) && (
                                <span className="timeline-movement">
                                  {" · "}{fmtMovement(journey.stops[i - 1].movement)}
                                </span>
                              )}
                            </td>
                          </tr>
                        )}
                      <tr
                        className={hoveredIndex === i ? "row-hover" : ""}
                        onMouseEnter={() => setHoveredIndex(i)}
                        onMouseLeave={() => setHoveredIndex(null)}
                      >
                        <td>{i + 1}</td>
                        <td>{fmtTime(s.seen_at)}</td>
                        <td>
                          {s.camera_name}
                          {s.anomaly_flags?.length > 0 && (
                            <span className="anomaly-chips">{anomalyChips(s.anomaly_flags)}</span>
                          )}
                        </td>
                        <td>{s.location_text}</td>
                        <td>{s.department ?? "—"}</td>
                        <td>
                          {s.confidence != null ? (
                            <>
                              <meter
                                className="confidence-meter"
                                min="0"
                                max="1"
                                value={s.confidence}
                                low={0.5}
                                high={0.8}
                                optimum={1}
                              />
                              {" "}{s.confidence.toFixed(2)}
                            </>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                      </Fragment>
                    ))}
                  </tbody>
                </table>
                <div className="route-map-container">
                  <RouteMap stops={journey.stops} hoveredIndex={hoveredIndex} onHover={setHoveredIndex} />
                </div>
              </div>

              {journey.unplaced_stops > 0 && (
                <p className="hint">
                  {journey.unplaced_stops} stop(s) not shown on map — camera location unknown.
                </p>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
