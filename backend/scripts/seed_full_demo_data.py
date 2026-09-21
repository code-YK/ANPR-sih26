#!/usr/bin/env python3
"""Load synthetic rows that make the operator console's data views usable.

This command is deliberately database-only. It never contacts a camera,
starts a worker, or creates a recording whose media file does not exist.

Run from ``backend`` after migrations::

    .venv\Scripts\python.exe scripts\seed_full_demo_data.py          # Windows
    .venv/bin/python scripts/seed_full_demo_data.py                    # Linux

Use ``--reset`` to remove only rows managed by this script. Re-running the
normal command first replaces its own rows, so it is safe for local demos.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import async_session  # noqa: E402
from app.models.alert import Alert  # noqa: E402
from app.models.analytics_count import AnalyticsCount  # noqa: E402
from app.models.auth import AuditEvent  # noqa: E402
from app.models.camera import (  # noqa: E402
    CameraHealthObservation,
    CameraMaintenanceEvent,
    CameraMaintenanceWorkOrder,
    Sighting,
)
from app.models.watchlist import WatchlistEntry  # noqa: E402
from app.plate_format import normalise  # noqa: E402
from scripts.seed_synthetic_demo import _load_fixture, seed_fixture  # noqa: E402


_MARKER = "sentinel-full-demo-v1"
_DEMO_CAMERA_IDS = ("demo-cam-001", "demo-cam-002", "demo-cam-003", "demo-cam-004", "demo-cam-005")
_WATCHLIST_PLATE = "SYNTH-TEST-0001"


async def reset_demo_data() -> None:
    """Remove only rows identified by this command's immutable marker."""
    async with async_session() as session:
        await session.execute(delete(Alert).where(Alert.dedup_key.like(f"{_MARKER}:%")))
        await session.execute(delete(Sighting).where(Sighting.model_version == _MARKER))
        await session.execute(
            delete(AnalyticsCount).where(
                AnalyticsCount.camera_id.in_(_DEMO_CAMERA_IDS),
                AnalyticsCount.mode == _MARKER,
            )
        )
        order_ids = list((await session.execute(
            select(CameraMaintenanceWorkOrder.id).where(CameraMaintenanceWorkOrder.summary.like("Synthetic demo:%"))
        )).scalars())
        if order_ids:
            await session.execute(delete(CameraMaintenanceEvent).where(CameraMaintenanceEvent.work_order_id.in_(order_ids)))
            await session.execute(delete(CameraMaintenanceWorkOrder).where(CameraMaintenanceWorkOrder.id.in_(order_ids)))
        await session.execute(delete(CameraHealthObservation).where(CameraHealthObservation.source == _MARKER))
        await session.execute(delete(AuditEvent).where(AuditEvent.action == f"{_MARKER}.loaded"))
        await session.commit()


def _sighting(camera_id: str, seen_at: datetime, plate: str, confidence: float, frame_pts_ms: int) -> Sighting:
    return Sighting(
        camera_id=camera_id, seen_at=seen_at, plate=normalise(plate), vehicle_type="car",
        vehicle_colour="synthetic blue", confidence=confidence, frame_pts_ms=frame_pts_ms,
        epoch_id=1, raw_ocr_text=plate,
        bbox={"x": 0.25, "y": 0.38, "width": 0.22, "height": 0.10}, model_version=_MARKER,
    )


async def seed_demo_data() -> None:
    # The base fixture owns the safe camera/watchlist rows. Calling it here
    # makes this command self-contained while preserving its endpoint-free
    # safety invariant.
    await seed_fixture(_load_fixture())
    await reset_demo_data()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    route_times = [now - timedelta(minutes=72), now - timedelta(minutes=41), now - timedelta(minutes=12)]
    async with async_session() as session:
        sightings = [
            _sighting("demo-cam-001", route_times[0], _WATCHLIST_PLATE, 0.98, 1000),
            _sighting("demo-cam-003", route_times[1], _WATCHLIST_PLATE, 0.96, 2000),
            _sighting("demo-cam-004", route_times[2], _WATCHLIST_PLATE, 0.94, 3000),
            _sighting("demo-cam-002", now - timedelta(minutes=28), "SYNTH-DEMO-0003", 0.91, 4100),
            _sighting("demo-cam-005", now - timedelta(minutes=8), "SYNTH-DEMO-0004", 0.89, 5200),
        ]
        session.add_all(sightings)
        await session.flush()

        entry = (await session.execute(select(WatchlistEntry).where(
            WatchlistEntry.source == "sentinel-synthetic-demo-v1",
            WatchlistEntry.normalised_value == normalise(_WATCHLIST_PLATE),
        ))).scalar_one()
        session.add_all([
            Alert(sighting_id=sightings[2].id, watchlist_entry_id=entry.id, camera_id="demo-cam-004", event_time=route_times[2], match_confidence=0.94, dedup_key=f"{_MARKER}:watchlist:open", status="open"),
            Alert(sighting_id=sightings[1].id, watchlist_entry_id=entry.id, camera_id="demo-cam-003", event_time=route_times[1], match_confidence=0.96, dedup_key=f"{_MARKER}:watchlist:acknowledged", status="acknowledged", acknowledged_at=now - timedelta(minutes=35)),
            Alert(sighting_id=sightings[0].id, watchlist_entry_id=entry.id, camera_id="demo-cam-001", event_time=route_times[0], match_confidence=0.98, dedup_key=f"{_MARKER}:watchlist:resolved", status="resolved", resolved_at=now - timedelta(minutes=65)),
            Alert(camera_id="demo-cam-002", alert_type="suspicious", label="Synthetic safety review", severity="medium", event_time=now - timedelta(minutes=19), match_confidence=0.82, dedup_key=f"{_MARKER}:suspicious:open", status="open"),
        ])
        session.add_all([
            AnalyticsCount(camera_id="demo-cam-001", mode=_MARKER, window_start=now - timedelta(minutes=30), window_end=now - timedelta(minutes=25), unique_tracks=14, peak_concurrent=6),
            AnalyticsCount(camera_id="demo-cam-003", mode=_MARKER, window_start=now - timedelta(minutes=20), window_end=now - timedelta(minutes=15), unique_tracks=21, peak_concurrent=9),
            CameraHealthObservation(camera_id="demo-cam-001", observed_at=now - timedelta(minutes=3), status="healthy", source=_MARKER, transport_ok="hls", is_live=True, reason="Synthetic health check: stream available"),
            CameraHealthObservation(camera_id="demo-cam-002", observed_at=now - timedelta(minutes=6), status="offline", source=_MARKER, transport_ok="none", is_live=False, reason="Synthetic health check: endpoint unavailable"),
            CameraHealthObservation(camera_id="demo-cam-003", observed_at=now - timedelta(minutes=2), status="healthy", source=_MARKER, transport_ok="rtsp", is_live=True, reason="Synthetic health check: inference source available"),
        ])
        work_order = CameraMaintenanceWorkOrder(camera_id="demo-cam-002", summary="Synthetic demo: inspect low-light camera coverage", status="in_progress", opened_at=now - timedelta(days=1))
        session.add(work_order)
        await session.flush()
        session.add_all([
            CameraMaintenanceEvent(work_order_id=work_order.id, occurred_at=now - timedelta(days=1), event_type="created", status="open", note="Synthetic fixture work order created."),
            CameraMaintenanceEvent(work_order_id=work_order.id, occurred_at=now - timedelta(hours=3), event_type="status_changed", status="in_progress", note="Synthetic fixture inspection assigned."),
            AuditEvent(action=f"{_MARKER}.loaded", target_type="demo_dataset", target_id=_MARKER, result="success", details={"sightings": len(sightings), "alerts": 4}, occurred_at=now),
        ])
        await session.commit()
    print("Loaded full synthetic demo data: 5 cameras, 5 sightings, 4 alerts, health history, maintenance, and analytics counts.")
    print(f"Journey search plate: {normalise(_WATCHLIST_PLATE)}")


async def verify_demo_data() -> None:
    async with async_session() as session:
        sightings = (await session.execute(select(Sighting).where(Sighting.model_version == _MARKER))).scalars().all()
        alerts = (await session.execute(select(Alert).where(Alert.dedup_key.like(f"{_MARKER}:%")))).scalars().all()
        statuses = {alert.status for alert in alerts}
        health = (await session.execute(select(CameraHealthObservation).where(CameraHealthObservation.source == _MARKER))).scalars().all()
    if len(sightings) != 5 or len(alerts) != 4 or statuses != {"open", "acknowledged", "resolved"} or len(health) != 3:
        raise RuntimeError("full synthetic demo dataset is incomplete; run the seed command again")
    print("Verified full synthetic demo data: 5 sightings, 4 alerts across all statuses, and 3 health observations.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Load synthetic rows for every data-backed operator-console view")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--reset", action="store_true", help="Remove only rows managed by this full-demo seed")
    action.add_argument("--verify", action="store_true", help="Verify the full-demo seed rows")
    args = parser.parse_args()
    if args.reset:
        asyncio.run(reset_demo_data())
        print("Removed full synthetic demo data; base synthetic cameras and watchlist entries remain.")
    elif args.verify:
        asyncio.run(verify_demo_data())
    else:
        asyncio.run(seed_demo_data())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
