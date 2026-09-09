"""City-wide traffic-flow analytics over confirmed-plate sightings.

Four read shapes, deliberately kept apart because their queries differ:

* /traffic/movement   per-plate sequence work -- corridors, first/last
                      observed node pairs, dwell/loop/data-fault anomalies.
* /traffic/flow       time-bucketed density per camera.
* /traffic/congestion current throughput against each camera's own recent
                      median. A comparison, never a forecast.
* /traffic/read-yield how much of a camera's traffic actually yields a
                      plate -- the denominator for everything above.

Two rules hold across all of them.

Department scoping is applied INSIDE every aggregate query, before grouping.
Filtering an aggregate afterwards would leak another department's totals
through a count that was computed over rows the caller may not see.

Every window is bounded and every result carries its own exclusions. A
truncated result says so with a count rather than quietly returning less.
"""

import csv
import io
import os
import statistics
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import AuthContext, authorised_departments, get_current_auth
from app.db import get_session
from app.models.analytics_count import AnalyticsCount
from app.models.camera import Camera, Sighting
from app.schemas import (
    CameraCongestion,
    CameraReadYield,
    OriginDestinationOut,
    RouteAnomalyOut,
    TrafficCongestionReport,
    TrafficExclusionsOut,
    TrafficFlowBucket,
    TrafficFlowReport,
    TrafficLegOut,
    TrafficMovementReport,
)
from app.services.traffic_analytics import DEFAULT_THRESHOLDS, build_traffic_report

router = APIRouter()

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=True)

# A sequence analysis has to load every sighting in the window, so the cap is
# the real protection rather than a page size. Hitting it is reported, not
# silently absorbed.
MAX_SIGHTING_ROWS = 50000
MAX_WINDOW_DAYS = 7
DEFAULT_WINDOW_HOURS = 24


def _resolve_window(since: datetime | None, until: datetime | None) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    resolved_until = until or now
    resolved_since = since or (resolved_until - timedelta(hours=DEFAULT_WINDOW_HOURS))
    if resolved_since >= resolved_until:
        raise HTTPException(status_code=422, detail="since must be earlier than until")
    if resolved_until - resolved_since > timedelta(days=MAX_WINDOW_DAYS):
        raise HTTPException(
            status_code=422,
            detail=f"window must not exceed {MAX_WINDOW_DAYS} days",
        )
    return resolved_since, resolved_until


def _scoped(stmt, auth: AuthContext):
    """Apply department scoping to a statement already joined to Camera.

    Called before group_by on every aggregate in this module.
    """
    allowed = authorised_departments(auth)
    if allowed is not None:
        stmt = stmt.where(Camera.department.in_(allowed))
    return stmt


async def _scoped_cameras(session: AsyncSession, auth: AuthContext) -> dict[str, Camera]:
    stmt = _scoped(select(Camera), auth)
    return {camera.camera_id: camera for camera in (await session.execute(stmt)).scalars().all()}


async def _load_movement(
    session: AsyncSession,
    auth: AuthContext,
    since: datetime,
    until: datetime,
    trip_gap_minutes: float,
):
    """Ordered per-plate rows -> the movement report.

    Selects Core columns rather than ORM objects: this walks the whole window
    in one linear pass and has no use for an identity map or lazy loaders.
    """
    stmt = (
        select(
            Sighting.plate,
            Sighting.camera_id,
            Sighting.seen_at,
            Sighting.epoch_id,
            Sighting.vehicle_type,
        )
        .join(Camera, Camera.camera_id == Sighting.camera_id)
        .where(
            Sighting.seen_at >= since,
            Sighting.seen_at <= until,
            Sighting.plate.is_not(None),
        )
    )
    stmt = _scoped(stmt, auth)
    stmt = stmt.order_by(Sighting.plate, Sighting.seen_at).limit(MAX_SIGHTING_ROWS + 1)

    rows = (await session.execute(stmt)).all()
    truncated = 0
    if len(rows) > MAX_SIGHTING_ROWS:
        # Drop the sentinel row and report the cap rather than pretending the
        # window was fully analysed.
        rows = rows[:MAX_SIGHTING_ROWS]
        truncated = 1

    cameras = await _scoped_cameras(session, auth)
    return build_traffic_report(
        rows=list(rows),
        cameras=cameras,
        window_start=since,
        window_end=until,
        thresholds={"trip_gap_minutes": trip_gap_minutes},
        sightings_truncated=truncated,
    )


@router.get("/traffic/movement", response_model=TrafficMovementReport)
async def traffic_movement(
    since: datetime | None = None,
    until: datetime | None = None,
    trip_gap_minutes: float = Query(
        DEFAULT_THRESHOLDS["trip_gap_minutes"], ge=1.0, le=720.0,
        description="Idle gap after which a plate's next sighting starts a new trip",
    ),
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Corridors, first/last observed node pairs, and route anomalies."""
    window_since, window_until = _resolve_window(since, until)
    report = await _load_movement(session, auth, window_since, window_until, trip_gap_minutes)

    return TrafficMovementReport(
        generated_at=report.generated_at,
        window_start=report.window_start,
        window_end=report.window_end,
        trip_gap_minutes=report.trip_gap_minutes,
        total_sightings=report.total_sightings,
        total_plates=report.total_plates,
        total_trips=report.total_trips,
        legs=[TrafficLegOut(**vars(leg)) for leg in report.legs],
        od_pairs=[OriginDestinationOut(**vars(pair)) for pair in report.od_pairs],
        anomalies=[RouteAnomalyOut(**vars(anomaly)) for anomaly in report.anomalies],
        exclusions=TrafficExclusionsOut(**vars(report.exclusions)),
    )


@router.get("/traffic/flow", response_model=TrafficFlowReport)
async def traffic_flow(
    since: datetime | None = None,
    until: datetime | None = None,
    bucket_minutes: int = Query(60, ge=5, le=1440),
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Time-bucketed density per camera.

    Two series per bucket, deliberately not merged into one number:
    `plate_reads` is a floor on traffic (only readable plates become
    sightings) and `vehicles_tracked` is every tracked vehicle. Presenting
    only the first would understate traffic; presenting only the second
    would hide which cameras can actually identify anything.
    """
    window_since, window_until = _resolve_window(since, until)
    bucket_seconds = bucket_minutes * 60

    def _bucket(column):
        return func.to_timestamp(
            func.floor(func.extract("epoch", column) / bucket_seconds) * bucket_seconds
        )

    reads_stmt = (
        select(
            _bucket(Sighting.seen_at).label("bucket_start"),
            Sighting.camera_id,
            func.count(func.distinct(Sighting.plate)).label("plate_reads"),
        )
        .join(Camera, Camera.camera_id == Sighting.camera_id)
        .where(
            Sighting.seen_at >= window_since,
            Sighting.seen_at <= window_until,
            Sighting.plate.is_not(None),
        )
    )
    reads_stmt = _scoped(reads_stmt, auth).group_by("bucket_start", Sighting.camera_id)

    tracked_stmt = (
        select(
            _bucket(AnalyticsCount.window_start).label("bucket_start"),
            AnalyticsCount.camera_id,
            func.sum(AnalyticsCount.unique_tracks).label("vehicles_tracked"),
        )
        .join(Camera, Camera.camera_id == AnalyticsCount.camera_id)
        .where(
            AnalyticsCount.mode == "vehicle",
            AnalyticsCount.window_start >= window_since,
            AnalyticsCount.window_start <= window_until,
        )
    )
    tracked_stmt = _scoped(tracked_stmt, auth).group_by("bucket_start", AnalyticsCount.camera_id)

    reads = (await session.execute(reads_stmt)).all()
    tracked = {
        (row.bucket_start, row.camera_id): int(row.vehicles_tracked)
        for row in (await session.execute(tracked_stmt)).all()
    }
    cameras = await _scoped_cameras(session, auth)

    buckets = [
        TrafficFlowBucket(
            bucket_start=row.bucket_start,
            camera_id=row.camera_id,
            camera_name=cameras[row.camera_id].name if row.camera_id in cameras else row.camera_id,
            department=cameras[row.camera_id].department if row.camera_id in cameras else None,
            plate_reads=int(row.plate_reads),
            vehicles_tracked=tracked.get((row.bucket_start, row.camera_id)),
        )
        for row in reads
    ]
    buckets.sort(key=lambda bucket: (bucket.bucket_start, bucket.camera_id))

    return TrafficFlowReport(
        generated_at=datetime.now(timezone.utc),
        window_start=window_since,
        window_end=window_until,
        bucket_minutes=bucket_minutes,
        buckets=buckets,
    )


@router.get("/traffic/read-yield", response_model=list[CameraReadYield])
async def traffic_read_yield(
    since: datetime | None = None,
    until: datetime | None = None,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Plate reads against vehicles actually tracked, per camera.

    A camera reading 20% of its traffic is not broken and is not a full
    picture either; publishing the ratio is what stops every other figure on
    this screen being read as a complete count.
    """
    window_since, window_until = _resolve_window(since, until)

    reads_stmt = (
        select(Sighting.camera_id, func.count(func.distinct(Sighting.plate)).label("plate_reads"))
        .join(Camera, Camera.camera_id == Sighting.camera_id)
        .where(
            Sighting.seen_at >= window_since,
            Sighting.seen_at <= window_until,
            Sighting.plate.is_not(None),
        )
    )
    reads_stmt = _scoped(reads_stmt, auth).group_by(Sighting.camera_id)

    tracked_stmt = (
        select(
            AnalyticsCount.camera_id,
            func.sum(AnalyticsCount.unique_tracks).label("vehicles_tracked"),
        )
        .join(Camera, Camera.camera_id == AnalyticsCount.camera_id)
        .where(
            AnalyticsCount.mode == "vehicle",
            AnalyticsCount.window_start >= window_since,
            AnalyticsCount.window_start <= window_until,
        )
    )
    tracked_stmt = _scoped(tracked_stmt, auth).group_by(AnalyticsCount.camera_id)

    reads = {row.camera_id: int(row.plate_reads) for row in (await session.execute(reads_stmt)).all()}
    tracked = {
        row.camera_id: int(row.vehicles_tracked)
        for row in (await session.execute(tracked_stmt)).all()
    }
    cameras = await _scoped_cameras(session, auth)

    results = []
    for camera_id, camera in cameras.items():
        plate_reads = reads.get(camera_id, 0)
        vehicles = tracked.get(camera_id)
        results.append(
            CameraReadYield(
                camera_id=camera_id,
                camera_name=camera.name,
                department=camera.department,
                plate_reads=plate_reads,
                vehicles_tracked=vehicles,
                # No vehicle counter running is an unmeasured yield, not a
                # zero one, so it stays null rather than becoming 0.0.
                read_yield=(plate_reads / vehicles) if vehicles else None,
            )
        )
    results.sort(key=lambda entry: entry.camera_name)
    return results


@router.get("/traffic/congestion", response_model=TrafficCongestionReport)
async def traffic_congestion(
    baseline_hours: int = Query(24, ge=2, le=168),
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Each camera's most recent hour against its own recent median hour.

    Against ITS OWN median, not against other cameras: a slip road and a
    ring-road junction have no shared scale. This is a comparison with
    recent history and is labelled as one -- predictive forecasting is
    deliberately not attempted, because with a plate-conditioned undercount
    and days of history any forecast here would be unfalsifiable.
    """
    now = datetime.now(timezone.utc)
    window_since = now - timedelta(hours=baseline_hours)

    hour = func.to_timestamp(
        func.floor(func.extract("epoch", AnalyticsCount.window_start) / 3600) * 3600
    ).label("hour_start")
    stmt = (
        select(
            hour,
            AnalyticsCount.camera_id,
            func.sum(AnalyticsCount.unique_tracks).label("vehicles"),
        )
        .join(Camera, Camera.camera_id == AnalyticsCount.camera_id)
        .where(
            AnalyticsCount.mode == "vehicle",
            AnalyticsCount.window_start >= window_since,
        )
    )
    stmt = _scoped(stmt, auth).group_by("hour_start", AnalyticsCount.camera_id)

    per_camera: dict[str, list[tuple[datetime, int]]] = {}
    for row in (await session.execute(stmt)).all():
        per_camera.setdefault(row.camera_id, []).append((row.hour_start, int(row.vehicles)))

    cameras = await _scoped_cameras(session, auth)
    results = []
    for camera_id, camera in cameras.items():
        series = sorted(per_camera.get(camera_id, []))
        current = baseline = ratio = None
        state = "unmeasured"

        # One hour is a current reading with nothing to compare it against;
        # a baseline needs at least two prior hours to be a median rather
        # than a single arbitrary hour.
        if len(series) >= 3:
            current = series[-1][1]
            baseline = statistics.median(value for _hour, value in series[:-1])
            if baseline > 0:
                ratio = current / baseline
                state = "busier" if ratio > 1.25 else "quieter" if ratio < 0.75 else "typical"

        results.append(
            CameraCongestion(
                camera_id=camera_id,
                camera_name=camera.name,
                department=camera.department,
                current_vehicles=current,
                baseline_median=baseline,
                ratio=round(ratio, 2) if ratio is not None else None,
                state=state,
            )
        )
    results.sort(key=lambda entry: (entry.ratio is None, -(entry.ratio or 0)))

    return TrafficCongestionReport(
        generated_at=now,
        window_start=window_since,
        window_end=now,
        baseline_hours=baseline_hours,
        cameras=results,
    )


@router.get("/traffic/export")
async def traffic_export(
    since: datetime | None = None,
    until: datetime | None = None,
    trip_gap_minutes: float = Query(DEFAULT_THRESHOLDS["trip_gap_minutes"], ge=1.0, le=720.0),
    format: str = Query("json", pattern="^(json|csv|html|pdf)$"),
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """One builder feeds all four formats, so they cannot drift apart."""
    window_since, window_until = _resolve_window(since, until)
    report = await _load_movement(session, auth, window_since, window_until, trip_gap_minutes)
    date = datetime.now(timezone.utc).date().isoformat()

    if format == "json":
        payload = TrafficMovementReport(
            generated_at=report.generated_at,
            window_start=report.window_start,
            window_end=report.window_end,
            trip_gap_minutes=report.trip_gap_minutes,
            total_sightings=report.total_sightings,
            total_plates=report.total_plates,
            total_trips=report.total_trips,
            legs=[TrafficLegOut(**vars(leg)) for leg in report.legs],
            od_pairs=[OriginDestinationOut(**vars(pair)) for pair in report.od_pairs],
            anomalies=[RouteAnomalyOut(**vars(anomaly)) for anomaly in report.anomalies],
            exclusions=TrafficExclusionsOut(**vars(report.exclusions)),
        )
        return Response(
            content=payload.model_dump_json(),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="traffic-{date}.json"'},
        )

    if format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow([
            "plate", "departed_at", "arrived_at", "from_camera_id", "from_name",
            "to_camera_id", "to_name", "gap_seconds", "distance_km", "bearing_deg",
            "compass", "min_avg_speed_kmh", "implausible",
        ])
        for leg in report.legs:
            writer.writerow([
                leg.plate,
                leg.departed_at.isoformat().replace("+00:00", "Z"),
                leg.arrived_at.isoformat().replace("+00:00", "Z"),
                leg.from_camera_id, leg.from_name, leg.to_camera_id, leg.to_name,
                round(leg.gap_seconds), leg.distance_km if leg.distance_km is not None else "",
                leg.bearing_deg if leg.bearing_deg is not None else "",
                leg.compass or "",
                leg.min_avg_speed_kmh if leg.min_avg_speed_kmh is not None else "",
                "yes" if leg.implausible else "",
            ])
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="traffic-{date}.csv"'},
        )

    html = _jinja_env.get_template("traffic_report.html").render(report=report)
    if format == "html":
        return HTMLResponse(content=html)

    from weasyprint import HTML

    return Response(
        content=HTML(string=html, base_url=_TEMPLATE_DIR).write_pdf(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="traffic-{date}.pdf"'},
    )
