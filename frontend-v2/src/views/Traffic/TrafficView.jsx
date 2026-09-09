import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, API } from "../../api.js";
import { Sparkline, VolumeBar } from "../../components/Charts.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";

const WINDOW_OPTIONS = [
  { label: "Last 6 hours", hours: 6 },
  { label: "Last 24 hours", hours: 24 },
  { label: "Last 7 days", hours: 168 },
];

function fmtTime(iso) {
  return new Date(iso).toLocaleString();
}

function fmtPct(ratio) {
  return ratio == null ? "—" : `${Math.round(ratio * 100)}%`;
}

// Flow rows arrive one per (bucket, camera). The operator's question is
// "what is this camera doing over time", so they are folded back into one
// series per camera before anything is drawn.
function seriesByCamera(buckets) {
  const byCamera = new Map();
  for (const bucket of buckets) {
    if (!byCamera.has(bucket.camera_id)) {
      byCamera.set(bucket.camera_id, {
        camera_id: bucket.camera_id,
        camera_name: bucket.camera_name,
        department: bucket.department,
        reads: [],
        tracked: [],
      });
    }
    const entry = byCamera.get(bucket.camera_id);
    entry.reads.push(bucket.plate_reads);
    if (bucket.vehicles_tracked != null) entry.tracked.push(bucket.vehicles_tracked);
  }
  return [...byCamera.values()]
    .map((entry) => ({
      ...entry,
      totalReads: entry.reads.reduce((a, b) => a + b, 0),
      totalTracked: entry.tracked.length ? entry.tracked.reduce((a, b) => a + b, 0) : null,
    }))
    .sort((a, b) => b.totalReads - a.totalReads);
}

export default function TrafficView() {
  usePageTitle("Traffic");
  const [hours, setHours] = useState(24);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const since = new Date(Date.now() - hours * 3600 * 1000).toISOString();
    const bucketMinutes = hours <= 6 ? 15 : hours <= 24 ? 60 : 360;
    const q = `since=${encodeURIComponent(since)}`;

    Promise.all([
      api(`/traffic/flow?${q}&bucket_minutes=${bucketMinutes}`),
      api(`/traffic/movement?${q}`),
      api(`/traffic/congestion`),
      api(`/traffic/read-yield?${q}`),
    ])
      .then(([flow, movement, congestion, readYield]) => {
        if (!cancelled) setData({ flow, movement, congestion, readYield });
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [hours]);

  const cameras = data ? seriesByCamera(data.flow.buckets) : [];
  const maxReads = Math.max(1, ...cameras.map((c) => c.totalReads));
  const yieldByCamera = new Map((data?.readYield ?? []).map((r) => [r.camera_id, r]));
  const legs = data?.movement.legs ?? [];
  const maxTrips = Math.max(1, ...(data?.movement.od_pairs ?? []).map((p) => p.trip_count));
  const busier = (data?.congestion.cameras ?? []).filter((c) => c.state === "busier");

  return (
    <section className="view active">
      <h1>Traffic</h1>

      <div className="toolbar">
        <label htmlFor="traffic-window">Window</label>
        <select
          id="traffic-window"
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
          style={{ maxWidth: 180 }}
        >
          {WINDOW_OPTIONS.map((option) => (
            <option key={option.hours} value={option.hours}>{option.label}</option>
          ))}
        </select>
        <button
          className="secondary"
          onClick={() => {
            const since = new Date(Date.now() - hours * 3600 * 1000).toISOString();
            window.open(`${API}/traffic/export?since=${encodeURIComponent(since)}&format=pdf`, "_blank");
          }}
        >
          Download report
        </button>
      </div>

      {loading && <p className="hint">Loading…</p>}
      {error && <p className="hint hint-warn">Could not load traffic analytics: {error}</p>}

      {data && !loading && (
        <>
          <p className="hint">
            Built from confirmed plate reads between {fmtTime(data.movement.window_start)} and{" "}
            {fmtTime(data.movement.window_end)}. A vehicle only appears once its plate is read, so
            every count here is a floor on real traffic — the read rate per camera is in the
            first table.
          </p>

          {/* Corridors lead: a directed movement between two cameras is the
              thing this whole feature exists to show, and it is the one
              section an operator cannot get anywhere else in the console. */}
          <h2>Corridors</h2>
          {legs.length === 0 ? (
            <p className="hint">
              No vehicle was seen at two different cameras in this window. Widen the window, or
              start analytics on more cameras in Live.
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Route</th>
                  <th>Plate</th>
                  <th>Departed</th>
                  <th>Took</th>
                  <th>Distance</th>
                  <th>Min avg speed</th>
                </tr>
              </thead>
              <tbody>
                {legs.slice(0, 40).map((leg, i) => (
                  <tr key={`${leg.plate}-${leg.departed_at}-${i}`}>
                    <td className="corridor-route">
                      {leg.from_name}
                      <span className="corridor-arrow" aria-label="to">
                        {leg.compass ? `→ ${leg.compass}` : "→"}
                      </span>
                      {leg.to_name}
                    </td>
                    <td className="plate-cell"><Link to={`/journey/${leg.plate}`}>{leg.plate}</Link></td>
                    <td>{fmtTime(leg.departed_at)}</td>
                    <td>{Math.round(leg.gap_seconds)}s</td>
                    <td>
                      {leg.distance_km != null
                        ? `${leg.distance_km.toFixed(2)} km`
                        : <span className="muted-value">not derivable</span>}
                    </td>
                    <td>
                      {leg.min_avg_speed_kmh != null ? (
                        <>
                          ≥ {Math.round(leg.min_avg_speed_kmh)} km/h
                          {leg.implausible && (
                            <span
                              className="badge badge-warn"
                              title="Too fast to be real — likely one plate misread across two vehicles, or a clock fault"
                            >
                              check data
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="muted-value">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {legs.length > 40 && (
            <p className="hint">Showing the 40 earliest of {legs.length} legs. The downloaded report has all of them.</p>
          )}

          <h2>Flow by camera</h2>
          {cameras.length === 0 ? (
            <p className="hint">No plate reads in this window.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Camera</th>
                  <th>Department</th>
                  <th>Over time</th>
                  <th>Plate reads</th>
                  <th>Vehicles tracked</th>
                  <th>Read rate</th>
                </tr>
              </thead>
              <tbody>
                {cameras.map((camera) => {
                  const yieldRow = yieldByCamera.get(camera.camera_id);
                  return (
                    <tr key={camera.camera_id}>
                      <td>{camera.camera_name}</td>
                      <td>{camera.department ?? "—"}</td>
                      <td>
                        <Sparkline
                          values={camera.reads}
                          title={`${camera.camera_name}: plate reads per bucket`}
                        />
                      </td>
                      <td>
                        <VolumeBar value={camera.totalReads} max={maxReads} />
                        {" "}{camera.totalReads}
                      </td>
                      <td>
                        {camera.totalTracked != null
                          ? camera.totalTracked
                          : <span className="muted-value">not counted</span>}
                      </td>
                      <td>
                        {yieldRow?.read_yield != null ? (
                          fmtPct(yieldRow.read_yield)
                        ) : (
                          <span className="muted-value" title="No vehicle counter ran on this camera in this window">
                            unmeasured
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          <h2>Compared with recent hours</h2>
          {busier.length === 0 ? (
            <p className="hint">
              No camera is busier than its own recent median. This compares each camera against its
              own history, not against other cameras — a slip road and a ring-road junction share no scale.
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Camera</th>
                  <th>This hour</th>
                  <th>Median hour</th>
                  <th>Change</th>
                </tr>
              </thead>
              <tbody>
                {busier.map((camera) => (
                  <tr key={camera.camera_id}>
                    <td>{camera.camera_name}</td>
                    <td>{camera.current_vehicles}</td>
                    <td>{camera.baseline_median}</td>
                    <td><span className="badge badge-warn">{camera.ratio}× busier</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h2>Route anomalies</h2>
          {data.movement.anomalies.length === 0 ? (
            <p className="hint">No vehicle lingered, doubled back, or produced an impossible transit in this window.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Seen</th>
                  <th>Plate</th>
                  <th>Camera</th>
                  <th>What happened</th>
                </tr>
              </thead>
              <tbody>
                {data.movement.anomalies.slice(0, 30).map((anomaly, i) => (
                  <tr key={`${anomaly.plate}-${anomaly.observed_at}-${i}`}>
                    <td>{fmtTime(anomaly.observed_at)}</td>
                    <td className="plate-cell"><Link to={`/journey/${anomaly.plate}`}>{anomaly.plate}</Link></td>
                    <td>{anomaly.camera_name}</td>
                    <td>{anomaly.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h2>First and last observed nodes</h2>
          {data.movement.od_pairs.length === 0 ? (
            <p className="hint">No completed trips in this window.</p>
          ) : (
            <table>
              <thead>
                <tr><th>Entered at</th><th>Last seen at</th><th>Trips</th></tr>
              </thead>
              <tbody>
                {data.movement.od_pairs.slice(0, 20).map((pair) => (
                  <tr key={`${pair.first_camera_id}-${pair.last_camera_id}`}>
                    <td>{pair.first_name}</td>
                    <td>{pair.last_name}</td>
                    <td>
                      <VolumeBar value={pair.trip_count} max={maxTrips} />
                      {" "}{pair.trip_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="hint">
            These are the ends of the observed part of each trip, not true origins and destinations —
            a trip begins and ends wherever cameras happen to be.
          </p>

          <h2>What these figures leave out</h2>
          <ul className="exclusion-list">
            <li>
              {data.movement.exclusions.legs_unpositioned} leg(s) between cameras without an exact
              coordinate, so direction and speed could not be derived.
            </li>
            <li>
              {data.movement.exclusions.cross_epoch_repeats} repeat sighting(s) at one camera across a
              stream restart, treated as replay rather than a vehicle waiting.
            </li>
            <li>
              {data.movement.exclusions.single_sighting_trips} trip(s) with only one sighting, which
              have no movement to measure.
            </li>
            <li>
              {data.movement.exclusions.legs_below_separation_floor} leg(s) between cameras too close
              together to measure, and {data.movement.exclusions.legs_below_time_floor} too brief.
            </li>
            {data.movement.exclusions.sightings_truncated > 0 && (
              <li>
                This window hit the row limit, so the figures above cover part of it. Narrow the
                window for a complete result.
              </li>
            )}
          </ul>
          <p className="hint">
            Speeds are lower bounds. Two cameras are joined here by a straight line, and the road
            between them is at least that long, so a vehicle cannot have averaged less than the
            figure shown — it is not the vehicle's speed. No camera here is calibrated, so speed at
            a single camera is not derivable at all.
          </p>
        </>
      )}
    </section>
  );
}
