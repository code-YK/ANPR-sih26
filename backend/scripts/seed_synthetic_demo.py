#!/usr/bin/env python3
"""Load or remove the committed non-sensitive Model 1 demo dataset.

This is deliberately a local database utility, not an API route: fixture
loading must not make a production-like system expose a bulk-write endpoint.
It contacts no sandbox, media endpoint, or ML worker.

Usage (from backend/):
    .venv/bin/python scripts/seed_synthetic_demo.py
    .venv/bin/python scripts/seed_synthetic_demo.py --reset
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import async_session  # noqa: E402
from app.models.auth import Department  # noqa: E402
from app.models.camera import Camera  # noqa: E402
from app.models.watchlist import WatchlistEntry  # noqa: E402
from app.plate_format import normalise  # noqa: E402

_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_registry.json"
_CAMERA_PREFIX = "demo-cam-"
_WATCHLIST_SOURCE = "sentinel-synthetic-demo-v1"


def _load_fixture() -> dict:
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != 1:
        raise ValueError("unsupported synthetic fixture schema_version")
    cameras = fixture.get("cameras")
    departments = fixture.get("departments")
    watchlist_entries = fixture.get("watchlist_entries")
    if not isinstance(cameras, list) or not isinstance(departments, list) or not isinstance(watchlist_entries, list):
        raise ValueError("fixture must contain departments, cameras, and watchlist_entries lists")
    ids = [camera.get("camera_id") for camera in cameras]
    numbers = [camera.get("camera_number") for camera in cameras]
    if any(not isinstance(camera_id, str) or not camera_id.startswith(_CAMERA_PREFIX) for camera_id in ids):
        raise ValueError(f"fixture camera IDs must use the {_CAMERA_PREFIX!r} namespace")
    if len(ids) != len(set(ids)) or len(numbers) != len(set(numbers)):
        raise ValueError("fixture camera IDs and camera numbers must be unique")
    if any(camera.get("department") not in departments for camera in cameras):
        raise ValueError("every fixture camera department must be declared")
    return fixture


def _camera_values(camera: dict) -> dict:
    values = dict(camera)
    timestamp = values.get("last_successful_connect")
    if timestamp is not None:
        values["last_successful_connect"] = datetime.fromisoformat(timestamp)
    # Raw source endpoints are intentionally omitted from the fixture. The
    # nullable model defaults keep the records metadata-only and safe.
    values.update({"rtsp_url": None, "hls_url": None, "webrtc_url": None})
    if values["latitude"] is not None and values["longitude"] is not None:
        values["geog"] = WKTElement(f"POINT({values['longitude']} {values['latitude']})", srid=4326)
    else:
        values["geog"] = None
    return values


async def reset_fixture() -> None:
    async with async_session() as session:
        camera_result = await session.execute(delete(Camera).where(Camera.camera_id.like(f"{_CAMERA_PREFIX}%")))
        watchlist_result = await session.execute(
            delete(WatchlistEntry).where(WatchlistEntry.source == _WATCHLIST_SOURCE)
        )
        await session.commit()
    print(f"Removed {camera_result.rowcount or 0} synthetic camera(s) and {watchlist_result.rowcount or 0} watchlist entry/entries.")


async def seed_fixture(fixture: dict) -> None:
    async with async_session() as session:
        for name in fixture["departments"]:
            if await session.get(Department, name) is None:
                session.add(Department(name=name))
        await session.flush()

        for camera in fixture["cameras"]:
            values = _camera_values(camera)
            statement = insert(Camera).values(**values)
            update_columns = {key: getattr(statement.excluded, key) for key in values if key != "camera_id"}
            await session.execute(statement.on_conflict_do_update(index_elements=[Camera.camera_id], set_=update_columns))

        existing_entries = {
            entry.normalised_value: entry
            for entry in (
                await session.execute(select(WatchlistEntry).where(WatchlistEntry.source == _WATCHLIST_SOURCE))
            ).scalars()
        }
        for row in fixture["watchlist_entries"]:
            normalised = normalise(row["raw_value"])
            entry = existing_entries.get(normalised)
            values = {
                "raw_value": row["raw_value"],
                "normalised_value": normalised,
                "reason_code": row.get("reason_code"),
                "severity": row["severity"],
                "notes": row.get("notes"),
                "source": _WATCHLIST_SOURCE,
                "active": True,
            }
            if entry is None:
                session.add(WatchlistEntry(**values))
            else:
                for key, value in values.items():
                    setattr(entry, key, value)
        await session.commit()
    print(
        f"Loaded {len(fixture['cameras'])} synthetic camera(s), "
        f"{len(fixture['departments'])} department(s), and {len(fixture['watchlist_entries'])} watchlist entry/entries."
    )


async def verify_fixture(fixture: dict) -> None:
    expected_ids = {camera["camera_id"] for camera in fixture["cameras"]}
    expected_plates = {normalise(row["raw_value"]) for row in fixture["watchlist_entries"]}
    async with async_session() as session:
        cameras = (
            await session.execute(select(Camera).where(Camera.camera_id.like(f"{_CAMERA_PREFIX}%")))
        ).scalars().all()
        watchlist_entries = (
            await session.execute(
                select(WatchlistEntry).where(
                    WatchlistEntry.source == _WATCHLIST_SOURCE,
                )
            )
        ).scalars().all()
    errors = []
    if {camera.camera_id for camera in cameras} != expected_ids:
        errors.append("camera IDs are missing or duplicated")
    if len(watchlist_entries) != len(expected_plates) or {entry.normalised_value for entry in watchlist_entries} != expected_plates:
        errors.append("watchlist values are missing or duplicated")
    if any(camera.rtsp_url or camera.hls_url or camera.webrtc_url for camera in cameras):
        errors.append("fixture camera exposes a source endpoint")
    if errors:
        raise RuntimeError("synthetic fixture verification failed: " + "; ".join(errors))
    print(f"Verified {len(cameras)} synthetic camera(s) and {len(watchlist_entries)} synthetic watchlist entry/entries; no source endpoints.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Load the committed synthetic Sentinel demo dataset")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--reset", action="store_true", help="Remove only the fixture's demo-cam-* and sourced watchlist rows")
    action.add_argument("--verify", action="store_true", help="Check the loaded fixture's rows and safe endpoint invariant")
    args = parser.parse_args()
    fixture = _load_fixture()
    if args.reset:
        asyncio.run(reset_fixture())
    elif args.verify:
        asyncio.run(verify_fixture(fixture))
    else:
        asyncio.run(seed_fixture(fixture))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
