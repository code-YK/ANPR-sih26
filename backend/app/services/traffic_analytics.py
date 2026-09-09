"""Traffic-flow analytics derived from confirmed-plate sightings.

Reconstructs per-plate trips from ordered sightings and derives the movement
quantities the traffic-analytics requirement asks for: onward direction,
corridor transit speed, first/last observed node pairs, and dwell/loop
anomalies.

What this can and cannot honestly say
-------------------------------------
No camera in this registry carries calibration -- no homography, no
pixels-per-metre, no mounting height, no field of view -- and some are PTZ,
so the view itself can move. Every quantity here is therefore derived from
two things only: a camera's geocoded point and a sighting's anchored
timestamp. That bounds the claims:

* Speed AT a camera is not derivable and is not attempted.
* Speed ALONG a corridor is derivable only as a LOWER BOUND. Road distance
  is always >= great-circle distance, so `haversine(A,B) / dt` is a sound
  minimum average -- the vehicle cannot have averaged less. It is named
  `min_avg_speed_kmh` everywhere for that reason and must never be
  presented as "the speed".
* Heading AT a camera is not derivable. What is derivable is the chord
  bearing of net displacement from one camera to the next, which is the
  onward direction of travel between two observations, not a heading.
* Both are suppressed entirely unless BOTH endpoints are `exact`-geocoded.
  An approximate geocode is a place-name lookup that can be a kilometre out,
  which would dominate a short leg. Suppressed legs are counted, never
  silently dropped.

Sightings are also a biased sample of traffic: one is written per track and
only once its plate is CONFIRMED, so vehicles whose plate was never readable
never appear. Anything here describes plate-readable trips. `analytics_counts`
with `mode="vehicle"` is the unbiased denominator; see `read_yield`.

The sandbox serves looping simulated footage, and `camera_feeds` bumps
`epoch_id` on both loop restart and reconnect. A vehicle reappearing on the
next loop is the same recorded vehicle, not a returning one, so dwell is
counted only within a single `(camera_id, epoch_id)`. Cross-epoch repeats
are excluded and counted. This under-reports rather than inventing traffic.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.services.districts import _haversine_km

if TYPE_CHECKING:  # pragma: no cover
    # Only ever used as an annotation. Importing the ORM model at runtime
    # would drag SQLAlchemy into a module that is otherwise pure arithmetic,
    # and would stop scripts/traffic_analytics_test.py running against a
    # checkout with no backend dependencies installed.
    from app.models.camera import Camera

# Every tunable lives here so a request can override one and, later, an
# `alert_rules` row can supply the same dict without this module changing.
DEFAULT_THRESHOLDS = {
    # Gap after which a plate's next sighting starts a new trip rather than
    # continuing the current one. No value is objectively correct; it is
    # echoed in every response and export so it is never an invisible choice.
    "trip_gap_minutes": 30.0,
    # Below this separation, geocode error dominates the distance and any
    # derived speed is noise rather than measurement.
    "min_leg_separation_m": 300.0,
    # Below this interval, timestamp granularity dominates the same way.
    "min_leg_seconds": 5.0,
    # Above this, the leg is a data-quality signal (a misread plate shared
    # between two vehicles, or a clock/anchor fault) -- never a speeding
    # finding, which this system has no calibrated basis to make.
    "impossible_speed_kmh": 200.0,
    # Time at one camera, within one stream epoch, above which the vehicle
    # is considered to have lingered rather than passed through.
    "dwell_minutes": 10.0,
}

_COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


@dataclass
class Leg:
    """One movement between two consecutive observations of the same plate."""

    plate: str
    from_camera_id: str
    to_camera_id: str
    from_name: str
    to_name: str
    departed_at: datetime
    arrived_at: datetime
    gap_seconds: float
    # All four are None unless both endpoints are exact-geocoded and the leg
    # clears the separation and time floors.
    distance_km: float | None
    bearing_deg: float | None
    compass: str | None
    min_avg_speed_kmh: float | None
    implausible: bool = False


@dataclass
class OriginDestinationPair:
    first_camera_id: str
    last_camera_id: str
    first_name: str
    last_name: str
    trip_count: int


@dataclass
class RouteAnomaly:
    """A movement pattern worth an operator's attention, or a data fault."""

    kind: str  # "dwell" | "loop" | "implausible_speed"
    plate: str
    camera_id: str
    camera_name: str
    detail: str
    observed_at: datetime


@dataclass
class StopAnnotation:
    """Onward movement departing one journey stop. Every field stays None
    when the movement could not be derived -- an unpositioned camera, a
    too-short leg, a trip break, or the final stop."""

    bearing_deg: float | None = None
    compass: str | None = None
    min_avg_speed_kmh: float | None = None
    distance_km: float | None = None
    gap_seconds: float | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class Exclusions:
    """What was left out and why. Every field is surfaced in the UI and the
    export -- a filtered set that does not state its own filtering is the
    thing this console exists not to do."""

    legs_unpositioned: int = 0
    legs_below_separation_floor: int = 0
    legs_below_time_floor: int = 0
    single_sighting_trips: int = 0
    cross_epoch_repeats: int = 0
    sightings_truncated: int = 0


@dataclass
class TrafficReport:
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    trip_gap_minutes: float
    total_sightings: int
    total_plates: int
    total_trips: int
    legs: list[Leg] = field(default_factory=list)
    od_pairs: list[OriginDestinationPair] = field(default_factory=list)
    anomalies: list[RouteAnomaly] = field(default_factory=list)
    exclusions: Exclusions = field(default_factory=Exclusions)


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing A->B, degrees clockwise from true north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _compass_point(bearing: float) -> str:
    return _COMPASS[int((bearing / 22.5) + 0.5) % 16]


def _is_positioned(camera: Camera | None) -> bool:
    """A camera can anchor a bearing/speed only if its coordinate was
    surveyed or geocoded exactly. `approximate` is a place-name lookup."""
    return (
        camera is not None
        and camera.latitude is not None
        and camera.longitude is not None
        and camera.geocode_confidence == "exact"
    )


def _breaks_trip(previous, row, gap_minutes: float) -> bool:
    """Whether `row` starts a new trip rather than continuing `previous`.

    Breaks on an idle gap, and on an `epoch_id` decrease at the same camera.
    Epoch is assigned per camera per worker process, so a decrease means the
    worker restarted and prior timing state is not continuous with what
    follows. Epochs from different cameras are not comparable at all and are
    never compared here.
    """
    elapsed = (row.seen_at - previous.seen_at).total_seconds()
    restarted = (
        row.camera_id == previous.camera_id
        and row.epoch_id is not None
        and previous.epoch_id is not None
        and row.epoch_id < previous.epoch_id
    )
    return elapsed > gap_minutes * 60.0 or restarted


def _sessionise(rows: list, gap_minutes: float) -> list[list]:
    """Split one plate's time-ordered sightings into trips."""
    trips: list[list] = []
    current: list = []
    for row in rows:
        if current and _breaks_trip(current[-1], row, gap_minutes):
            trips.append(current)
            current = []
        current.append(row)
    if current:
        trips.append(current)
    return trips


def _build_leg(previous, row, cameras: dict[str, Camera], thresholds: dict,
               exclusions: Exclusions) -> Leg:
    from_cam = cameras.get(previous.camera_id)
    to_cam = cameras.get(row.camera_id)
    gap_seconds = (row.seen_at - previous.seen_at).total_seconds()

    distance_km = bearing = compass = speed = None
    implausible = False

    if not (_is_positioned(from_cam) and _is_positioned(to_cam)):
        exclusions.legs_unpositioned += 1
    else:
        distance_km = _haversine_km(
            float(from_cam.latitude), float(from_cam.longitude),
            float(to_cam.latitude), float(to_cam.longitude),
        )
        if distance_km * 1000.0 < thresholds["min_leg_separation_m"]:
            exclusions.legs_below_separation_floor += 1
            distance_km = None
        elif gap_seconds < thresholds["min_leg_seconds"]:
            exclusions.legs_below_time_floor += 1
            distance_km = None
        else:
            bearing = _bearing_deg(
                float(from_cam.latitude), float(from_cam.longitude),
                float(to_cam.latitude), float(to_cam.longitude),
            )
            compass = _compass_point(bearing)
            speed = distance_km / (gap_seconds / 3600.0)
            implausible = speed > thresholds["impossible_speed_kmh"]

    return Leg(
        plate=previous.plate,
        from_camera_id=previous.camera_id,
        to_camera_id=row.camera_id,
        from_name=from_cam.name if from_cam else previous.camera_id,
        to_name=to_cam.name if to_cam else row.camera_id,
        departed_at=previous.seen_at,
        arrived_at=row.seen_at,
        gap_seconds=gap_seconds,
        distance_km=round(distance_km, 3) if distance_km is not None else None,
        bearing_deg=round(bearing, 1) if bearing is not None else None,
        compass=compass,
        min_avg_speed_kmh=round(speed, 1) if speed is not None else None,
        implausible=implausible,
    )


def _trip_anomalies(trip: list, cameras: dict[str, Camera], thresholds: dict,
                    exclusions: Exclusions) -> list[RouteAnomaly]:
    anomalies: list[RouteAnomaly] = []
    dwell_seconds = thresholds["dwell_minutes"] * 60.0
    visited: set[str] = set()

    for index, row in enumerate(trip):
        name = cameras[row.camera_id].name if row.camera_id in cameras else row.camera_id

        if index > 0:
            previous = trip[index - 1]
            if row.camera_id == previous.camera_id:
                # Same camera twice running. Only a repeat inside one stream
                # epoch is real dwell; across epochs it is the simulated feed
                # looping or the worker reconnecting, which is not a vehicle
                # that stayed put.
                if row.epoch_id != previous.epoch_id:
                    exclusions.cross_epoch_repeats += 1
                else:
                    elapsed = (row.seen_at - previous.seen_at).total_seconds()
                    if elapsed > dwell_seconds:
                        anomalies.append(RouteAnomaly(
                            kind="dwell",
                            plate=row.plate,
                            camera_id=row.camera_id,
                            camera_name=name,
                            detail=f"stationary or circling for {elapsed / 60:.0f} min",
                            observed_at=row.seen_at,
                        ))
            elif row.camera_id in visited:
                anomalies.append(RouteAnomaly(
                    kind="loop",
                    plate=row.plate,
                    camera_id=row.camera_id,
                    camera_name=name,
                    detail="returned to a camera already passed on this trip",
                    observed_at=row.seen_at,
                ))
        visited.add(row.camera_id)

    return anomalies


def annotate_journey(
    rows: list,
    cameras: dict[str, Camera],
    thresholds: dict | None = None,
) -> tuple[list[StopAnnotation], Exclusions]:
    """Per-stop movement annotation for ONE plate's ordered sightings.

    Returns a list aligned index-for-index with `rows`. Each entry describes
    the onward movement departing that stop, so the last stop -- and any stop
    where the trip breaks -- carries no direction or speed. Uses exactly the
    same trip-break, positioning and dwell rules as the aggregate report, so
    the journey screen and the traffic report can never disagree about the
    same two sightings.
    """
    settings = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    exclusions = Exclusions()
    dwell_seconds = settings["dwell_minutes"] * 60.0

    annotations = [StopAnnotation() for _ in rows]
    visited_this_trip: set[str] = set()

    for index, row in enumerate(rows):
        if index > 0:
            previous = rows[index - 1]
            if _breaks_trip(previous, row, settings["trip_gap_minutes"]):
                visited_this_trip = set()
            else:
                leg = _build_leg(previous, row, cameras, settings, exclusions)
                departing = annotations[index - 1]
                departing.bearing_deg = leg.bearing_deg
                departing.compass = leg.compass
                departing.min_avg_speed_kmh = leg.min_avg_speed_kmh
                departing.distance_km = leg.distance_km
                departing.gap_seconds = leg.gap_seconds

                if leg.implausible:
                    annotations[index].flags.append("implausible_speed")
                if row.camera_id == previous.camera_id:
                    if row.epoch_id != previous.epoch_id:
                        exclusions.cross_epoch_repeats += 1
                    elif (row.seen_at - previous.seen_at).total_seconds() > dwell_seconds:
                        annotations[index].flags.append("dwell")
                elif row.camera_id in visited_this_trip:
                    annotations[index].flags.append("loop")

        visited_this_trip.add(row.camera_id)

    return annotations, exclusions


def build_traffic_report(
    rows: list,
    cameras: dict[str, Camera],
    window_start: datetime,
    window_end: datetime,
    thresholds: dict | None = None,
    sightings_truncated: int = 0,
) -> TrafficReport:
    """Build the report from sightings ordered by (plate, seen_at).

    `rows` need only expose `.plate`, `.camera_id`, `.seen_at`, `.epoch_id`
    and `.vehicle_type`, so Core row tuples are passed straight in without
    loading ORM objects. `cameras` maps camera_id to the already
    department-scoped Camera rows -- scoping is the router's job and must
    already have happened before anything reaches here.
    """
    settings = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    exclusions = Exclusions(sightings_truncated=sightings_truncated)

    legs: list[Leg] = []
    anomalies: list[RouteAnomaly] = []
    od_counts: Counter[tuple[str, str]] = Counter()
    plates: set[str] = set()
    trip_count = 0

    # rows arrive ordered by (plate, seen_at); group without itertools so the
    # ordering assumption stays visible at the point it is relied on.
    by_plate: dict[str, list] = {}
    for row in rows:
        if row.plate:
            by_plate.setdefault(row.plate, []).append(row)

    for plate, plate_rows in by_plate.items():
        plates.add(plate)
        for trip in _sessionise(plate_rows, settings["trip_gap_minutes"]):
            trip_count += 1
            if len(trip) < 2:
                # A single observation is a sighting, not a movement: it has
                # no direction, no speed, and no destination to pair with.
                exclusions.single_sighting_trips += 1
                continue

            for index in range(1, len(trip)):
                legs.append(_build_leg(trip[index - 1], trip[index], cameras,
                                       settings, exclusions))

            anomalies.extend(_trip_anomalies(trip, cameras, settings, exclusions))
            od_counts[(trip[0].camera_id, trip[-1].camera_id)] += 1

    for leg in legs:
        if leg.implausible:
            anomalies.append(RouteAnomaly(
                kind="implausible_speed",
                plate=leg.plate,
                camera_id=leg.to_camera_id,
                camera_name=leg.to_name,
                detail=(
                    f"{leg.min_avg_speed_kmh:.0f} km/h minimum between "
                    f"{leg.from_name} and {leg.to_name} -- check for a shared "
                    f"misread plate or a clock fault"
                ),
                observed_at=leg.arrived_at,
            ))

    od_pairs = [
        OriginDestinationPair(
            first_camera_id=first,
            last_camera_id=last,
            first_name=cameras[first].name if first in cameras else first,
            last_name=cameras[last].name if last in cameras else last,
            trip_count=count,
        )
        for (first, last), count in od_counts.most_common()
    ]

    legs.sort(key=lambda leg: leg.departed_at)
    anomalies.sort(key=lambda anomaly: anomaly.observed_at, reverse=True)

    return TrafficReport(
        generated_at=datetime.now(timezone.utc),
        window_start=window_start,
        window_end=window_end,
        trip_gap_minutes=settings["trip_gap_minutes"],
        total_sightings=len(rows),
        total_plates=len(plates),
        total_trips=trip_count,
        legs=legs,
        od_pairs=od_pairs,
        anomalies=anomalies,
        exclusions=exclusions,
    )
