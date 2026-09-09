#!/usr/bin/env python3
"""
Deterministic tests for the traffic-analytics derivation
(app/services/traffic_analytics.py).

The service is pure -- it takes already-loaded, already-department-scoped
rows and returns dataclasses -- so this needs no running backend and no
database. Every case below is a claim the UI and the export make, and the
point of testing them here is that each one is a statement about real
vehicles that must not be overstated:

    - Bearing and minimum speed are computed for a well-separated leg.
    - Speed is a LOWER bound (straight-line), never presented as the speed.
    - A leg touching an `approximate`-geocoded camera is suppressed, counted.
    - A leg below the separation floor is suppressed, counted.
    - An idle gap starts a new trip.
    - An epoch_id decrease at one camera starts a new trip (worker restart).
    - A same-camera repeat ACROSS epochs is NOT dwell (looping footage).
    - A same-camera repeat WITHIN one epoch above the threshold IS dwell.
    - Revisiting an earlier camera on one trip is a loop.
    - An impossible transit is flagged as a data fault, not a speeding find.
    - A single-sighting trip yields no leg and is counted as excluded.

Usage (from backend/, using the backend's own .venv):
    <venv>/bin/python scripts/traffic_analytics_test.py
"""

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.traffic_analytics import (  # noqa: E402
    annotate_journey,
    build_traffic_report,
)

RESULTS = []
T0 = datetime(2026, 9, 10, 8, 0, 0, tzinfo=timezone.utc)


@dataclass
class Row:
    """Stands in for the Core row tuple the router selects."""

    plate: str
    camera_id: str
    seen_at: datetime
    epoch_id: int = 0
    vehicle_type: str | None = "car"


@dataclass
class FakeCamera:
    """The four Camera attributes the service actually reads. Kept as a
    stand-in rather than the ORM model so this runs with no database and no
    installed backend dependencies."""

    camera_id: str
    name: str
    latitude: float | None
    longitude: float | None
    geocode_confidence: str | None
    department: str = "traffic"


def camera(camera_id, name, lat, lon, confidence="exact"):
    return FakeCamera(
        camera_id=camera_id,
        name=name,
        latitude=lat,
        longitude=lon,
        geocode_confidence=confidence,
    )


# Roughly 3.9 km apart on the Ahmedabad ring, and one 60 m apart so the
# separation floor has something real to reject.
CAMERAS = {
    "cam-a": camera("cam-a", "Ring Road North", 23.0225, 72.5714),
    "cam-b": camera("cam-b", "Ring Road East", 23.0225, 72.6100),
    "cam-c": camera("cam-c", "Ring Road South", 22.9900, 72.6100),
    "cam-approx": camera("cam-approx", "Bus Stand", 23.0500, 72.6000, "approximate"),
    "cam-near": camera("cam-near", "Ring Road North Gate", 23.0225, 72.5720),
}


def report(rows, **kwargs):
    return build_traffic_report(
        rows=rows,
        cameras=CAMERAS,
        window_start=T0,
        window_end=T0 + timedelta(hours=6),
        **kwargs,
    )


def check(name):
    def wrap(fn):
        def runner():
            try:
                ok, detail = fn()
            except Exception as exc:  # noqa: BLE001 - a crash is a failure
                ok, detail = False, f"raised {type(exc).__name__}: {exc}"
            RESULTS.append((name, ok, detail))
            print(f"  [{'PASS' if ok else 'FAIL'}] {name} - {detail}")
            return ok
        return runner
    return wrap


@check("well-separated leg yields an eastward bearing and a minimum speed")
def test_bearing_and_speed():
    # cam-a -> cam-b is due east, 3.95 km, in 5 minutes -> ~47 km/h minimum.
    out = report([
        Row("GJ01AB1234", "cam-a", T0),
        Row("GJ01AB1234", "cam-b", T0 + timedelta(minutes=5)),
    ])
    leg = out.legs[0]
    ok = (
        leg.compass == "E"
        and 85.0 < leg.bearing_deg < 95.0
        and 40.0 < leg.min_avg_speed_kmh < 55.0
        and leg.distance_km > 3.0
        and not leg.implausible
    )
    return ok, f"{leg.compass} {leg.bearing_deg}deg, >={leg.min_avg_speed_kmh} km/h over {leg.distance_km} km"


@check("speed is a lower bound: a detour cannot lower it below straight-line")
def test_speed_is_lower_bound():
    # Same endpoints, same time: whatever route was actually driven is at
    # least as long as the chord, so the reported figure is a floor.
    out = report([
        Row("GJ01AB1234", "cam-a", T0),
        Row("GJ01AB1234", "cam-b", T0 + timedelta(minutes=5)),
    ])
    leg = out.legs[0]
    straight_line_kmh = leg.distance_km / (leg.gap_seconds / 3600.0)
    ok = abs(leg.min_avg_speed_kmh - straight_line_kmh) < 0.2
    return ok, f"reported {leg.min_avg_speed_kmh} == straight-line {straight_line_kmh:.1f}"


@check("leg touching an approximate geocode is suppressed and counted")
def test_approximate_geocode_suppressed():
    out = report([
        Row("GJ01AB1234", "cam-a", T0),
        Row("GJ01AB1234", "cam-approx", T0 + timedelta(minutes=5)),
    ])
    leg = out.legs[0]
    ok = (
        leg.bearing_deg is None
        and leg.min_avg_speed_kmh is None
        and leg.distance_km is None
        and out.exclusions.legs_unpositioned == 1
    )
    return ok, f"suppressed, legs_unpositioned={out.exclusions.legs_unpositioned}"


@check("leg below the 300 m separation floor is suppressed and counted")
def test_separation_floor():
    out = report([
        Row("GJ01AB1234", "cam-a", T0),
        Row("GJ01AB1234", "cam-near", T0 + timedelta(minutes=5)),
    ])
    leg = out.legs[0]
    ok = leg.min_avg_speed_kmh is None and out.exclusions.legs_below_separation_floor == 1
    return ok, f"suppressed, below_separation={out.exclusions.legs_below_separation_floor}"


@check("idle gap beyond the threshold starts a new trip")
def test_trip_gap_breaks_session():
    out = report([
        Row("GJ01AB1234", "cam-a", T0),
        Row("GJ01AB1234", "cam-b", T0 + timedelta(minutes=5)),
        Row("GJ01AB1234", "cam-c", T0 + timedelta(minutes=90)),
    ])
    # Two trips: (a->b) and (c) alone, so one leg and one excluded singleton.
    ok = (
        out.total_trips == 2
        and len(out.legs) == 1
        and out.exclusions.single_sighting_trips == 1
    )
    return ok, f"{out.total_trips} trips, {len(out.legs)} leg, {out.exclusions.single_sighting_trips} singleton"


@check("epoch_id decrease at one camera starts a new trip")
def test_epoch_restart_breaks_session():
    out = report([
        Row("GJ01AB1234", "cam-a", T0, epoch_id=7),
        Row("GJ01AB1234", "cam-a", T0 + timedelta(minutes=1), epoch_id=0),
    ])
    ok = out.total_trips == 2 and out.exclusions.single_sighting_trips == 2
    return ok, f"{out.total_trips} trips from a worker restart"


@check("same-camera repeat across epochs is replay, not dwell")
def test_cross_epoch_repeat_is_not_dwell():
    # The simulated feed looped: same camera, later time, next epoch. A real
    # 20-minute dwell would be indistinguishable, so it is excluded.
    out = report([
        Row("GJ01AB1234", "cam-a", T0, epoch_id=1),
        Row("GJ01AB1234", "cam-a", T0 + timedelta(minutes=20), epoch_id=2),
    ])
    dwells = [a for a in out.anomalies if a.kind == "dwell"]
    ok = dwells == [] and out.exclusions.cross_epoch_repeats == 1
    return ok, f"no dwell raised, cross_epoch_repeats={out.exclusions.cross_epoch_repeats}"


@check("same-camera repeat within one epoch above threshold is dwell")
def test_within_epoch_dwell():
    out = report([
        Row("GJ01AB1234", "cam-a", T0, epoch_id=3),
        Row("GJ01AB1234", "cam-a", T0 + timedelta(minutes=20), epoch_id=3),
    ])
    dwells = [a for a in out.anomalies if a.kind == "dwell"]
    ok = len(dwells) == 1 and out.exclusions.cross_epoch_repeats == 0
    return ok, dwells[0].detail if dwells else "no dwell raised"


@check("returning to an earlier camera on one trip is a loop")
def test_loop_detection():
    out = report([
        Row("GJ01AB1234", "cam-a", T0),
        Row("GJ01AB1234", "cam-b", T0 + timedelta(minutes=5)),
        Row("GJ01AB1234", "cam-a", T0 + timedelta(minutes=10)),
    ])
    loops = [a for a in out.anomalies if a.kind == "loop"]
    ok = len(loops) == 1 and loops[0].camera_id == "cam-a"
    return ok, loops[0].detail if loops else "no loop raised"


@check("impossible transit is flagged as a data fault")
def test_implausible_speed():
    # 3.95 km in 4 seconds is ~3500 km/h: one plate string on two vehicles,
    # or a clock fault. Never a speeding finding.
    out = report([
        Row("GJ01AB1234", "cam-a", T0),
        Row("GJ01AB1234", "cam-b", T0 + timedelta(seconds=6)),
    ])
    faults = [a for a in out.anomalies if a.kind == "implausible_speed"]
    ok = len(faults) == 1 and "misread" in faults[0].detail
    return ok, faults[0].detail if faults else "no fault raised"


@check("origin/destination pairs count trips, not sightings")
def test_od_pairs():
    rows = []
    for n in range(3):
        plate = f"GJ01AB000{n}"
        rows += [
            Row(plate, "cam-a", T0 + timedelta(minutes=n)),
            Row(plate, "cam-b", T0 + timedelta(minutes=n + 5)),
            Row(plate, "cam-c", T0 + timedelta(minutes=n + 9)),
        ]
    out = report(rows)
    pair = out.od_pairs[0]
    ok = (
        len(out.od_pairs) == 1
        and pair.first_camera_id == "cam-a"
        and pair.last_camera_id == "cam-c"
        and pair.trip_count == 3
    )
    return ok, f"{pair.first_name} -> {pair.last_name}, {pair.trip_count} trips"


@check("the trip-gap threshold is echoed back in the report")
def test_threshold_is_echoed():
    out = report([Row("GJ01AB1234", "cam-a", T0)], thresholds={"trip_gap_minutes": 12.0})
    ok = out.trip_gap_minutes == 12.0
    return ok, f"trip_gap_minutes={out.trip_gap_minutes} travels with the result"


@check("journey annotation aligns onward movement to the departing stop")
def test_journey_annotation_alignment():
    rows = [
        Row("GJ01AB1234", "cam-a", T0),
        Row("GJ01AB1234", "cam-b", T0 + timedelta(minutes=5)),
        Row("GJ01AB1234", "cam-c", T0 + timedelta(minutes=9)),
    ]
    annotations, _ = annotate_journey(rows, CAMERAS)
    ok = (
        len(annotations) == 3
        and annotations[0].compass == "E"          # a -> b, due east
        and annotations[1].compass == "S"          # b -> c, due south
        and annotations[2].min_avg_speed_kmh is None  # last stop has no onward leg
    )
    return ok, f"{annotations[0].compass}, {annotations[1].compass}, last={annotations[2].compass}"


@check("journey annotation and the aggregate report agree on one leg")
def test_journey_matches_aggregate():
    rows = [
        Row("GJ01AB1234", "cam-a", T0),
        Row("GJ01AB1234", "cam-b", T0 + timedelta(minutes=5)),
    ]
    annotations, _ = annotate_journey(rows, CAMERAS)
    leg = report(rows).legs[0]
    ok = (
        annotations[0].bearing_deg == leg.bearing_deg
        and annotations[0].min_avg_speed_kmh == leg.min_avg_speed_kmh
    )
    return ok, f"both report {leg.bearing_deg}deg at >={leg.min_avg_speed_kmh} km/h"


@check("journey annotation flags dwell and loop on the arriving stop")
def test_journey_flags():
    rows = [
        Row("GJ01AB1234", "cam-a", T0, epoch_id=1),
        Row("GJ01AB1234", "cam-b", T0 + timedelta(minutes=5), epoch_id=1),
        Row("GJ01AB1234", "cam-a", T0 + timedelta(minutes=10), epoch_id=1),
        Row("GJ01AB1234", "cam-a", T0 + timedelta(minutes=35), epoch_id=1),
    ]
    annotations, _ = annotate_journey(rows, CAMERAS)
    ok = "loop" in annotations[2].flags and "dwell" in annotations[3].flags
    return ok, f"stop 3 {annotations[2].flags}, stop 4 {annotations[3].flags}"


def main():
    print("Traffic analytics derivation tests")
    print("-" * 60)
    for name, value in list(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("-" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"{passed}/{len(RESULTS)} passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
