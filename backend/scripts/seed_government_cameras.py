#!/usr/bin/env python3
"""Onboard (or remove) the real government-provided camera registry.

These are the cameras the recorded feeds under `recorded-streams/` actually
came from: government mode (app/services/government_mode.py) matches each
clip's `.json` sidecar `camera_id` against a row in this registry and
temporarily repoints that row's hls_url/rtsp_url at the local relay. Without
these rows the toggle has nothing to swap and refuses to enable.

Deliberately a local database utility, not an API route -- same reasoning as
seed_synthetic_demo.py, which this mirrors: fixture loading must not make a
production-like system expose a bulk-write endpoint. It contacts no sandbox,
media endpoint, or ML worker.

New rows are written metadata-only: `rtsp_url`/`hls_url`/`webrtc_url` start
NULL because the real government endpoints are not reachable from a
development machine, and government mode fills them in at toggle time anyway.

Safe to re-run. It upserts on camera_id, and on an existing row it updates
only the metadata this fixture actually owns -- the three stream-endpoint
columns are deliberately excluded from the conflict update (see seed_fixture),
so re-running while government mode is active does not tear its relay URLs out
from under it, and an operator's own edits to a stream endpoint survive too.

Usage (from backend/):
    Windows:  .venv\\Scripts\\python.exe scripts/seed_government_cameras.py
    Linux:    .venv/bin/python scripts/seed_government_cameras.py

    ... --verify   check what is present without writing
    ... --reset    remove exactly the cameras this fixture declares
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import async_session  # noqa: E402
from app.models.auth import Department  # noqa: E402
from app.models.camera import Camera  # noqa: E402

_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "government_cameras.json"


def _load_fixture() -> dict:
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != 1:
        raise ValueError("unsupported government fixture schema_version")
    cameras = fixture.get("cameras")
    if not isinstance(cameras, list) or not cameras:
        raise ValueError("fixture must contain a non-empty cameras list")
    ids = [camera.get("camera_id") for camera in cameras]
    numbers = [camera.get("camera_number") for camera in cameras]
    if any(not isinstance(camera_id, str) or not camera_id for camera_id in ids):
        raise ValueError("every fixture camera needs a string camera_id")
    if len(ids) != len(set(ids)) or len(numbers) != len(set(numbers)):
        raise ValueError("fixture camera IDs and camera numbers must be unique")
    # A camera with no department is readable only by a super admin
    # (AuthContext.has_department returns False for None), so a department-less
    # fixture silently produces an empty registry for every ordinary operator.
    # Catch that here rather than letting it look like a permissions bug later.
    if any(not camera.get("department") for camera in cameras):
        raise ValueError(
            "every fixture camera must declare a department -- a NULL department is "
            "invisible to every non-super-admin user"
        )
    return fixture


def _camera_values(camera: dict) -> dict:
    values = dict(camera)
    # The real government endpoints are not reachable from a development
    # machine, and government mode overwrites these two columns anyway while
    # it is on (restoring whatever was here on disable). Keeping them NULL
    # makes "no stream" the honest default rather than a dead URL that looks
    # like a broken camera in the Live grid.
    values.update({"rtsp_url": None, "hls_url": None, "webrtc_url": None})
    if values.get("latitude") is not None and values.get("longitude") is not None:
        values["geog"] = WKTElement(f"POINT({values['longitude']} {values['latitude']})", srid=4326)
    else:
        values["geog"] = None
    return values


async def seed_fixture(fixture: dict) -> None:
    async with async_session() as session:
        # Departments are a real table with a foreign key from cameras; a
        # fixture naming one that does not exist yet would fail on insert.
        for name in sorted({camera["department"] for camera in fixture["cameras"]}):
            if await session.get(Department, name) is None:
                session.add(Department(name=name))
        await session.flush()

        for camera in fixture["cameras"]:
            values = _camera_values(camera)
            statement = insert(Camera).values(**values)
            # Stream endpoints are set on INSERT only, never on conflict. They
            # are not this fixture's to own: government mode rewrites them
            # while it is active, and an operator can edit them in the
            # Registry. Re-running this script to refresh metadata used to
            # blank all three, which silently pointed every camera at nothing
            # -- with government mode on, that meant a Live wall that filtered
            # correctly and then played no video, and the mode's own state
            # file still claimed it was active.
            update_columns = {
                key: getattr(statement.excluded, key)
                for key in values
                if key not in ("camera_id", "rtsp_url", "hls_url", "webrtc_url")
            }
            await session.execute(
                statement.on_conflict_do_update(index_elements=[Camera.camera_id], set_=update_columns)
            )
        await session.commit()
    print(f"Onboarded {len(fixture['cameras'])} government camera(s).")


async def reset_fixture(fixture: dict) -> None:
    ids = [camera["camera_id"] for camera in fixture["cameras"]]
    async with async_session() as session:
        # sightings, alerts and analytics_counts all reference cameras with
        # ON DELETE NO ACTION, so deleting a camera that has been observed
        # aborts the whole transaction with a raw ForeignKeyViolation. Check
        # first and refuse with something an operator can act on -- and keep
        # the observation record, which is evidence, rather than offering to
        # cascade it away.
        blocked: dict[str, str] = {}
        for table, column in (("sightings", "camera_id"),
                              ("alerts", "camera_id"),
                              ("analytics_counts", "camera_id")):
            rows = (await session.execute(
                text(f"SELECT {column} AS cid, count(*) AS n FROM {table} "
                     f"WHERE {column} = ANY(:ids) GROUP BY {column}"),
                {"ids": ids},
            )).all()
            for cid, count in rows:
                blocked[cid] = f"{blocked[cid]}, {count} {table}" if cid in blocked else f"{count} {table}"
        if blocked:
            detail = "; ".join(f"{cid} ({what})" for cid, what in sorted(blocked.items()))
            raise SystemExit(
                "Refusing to remove government cameras that have recorded observations: "
                f"{detail}.\nDelete those rows first if you really mean to, or leave the "
                "cameras in place -- re-running this script without --reset re-syncs them."
            )

        # Scoped to exactly the declared IDs rather than a LIKE 'cam%' sweep:
        # an operator may well have onboarded their own camera whose id
        # happens to start with the same letters, and this must never take
        # that with it.
        result = await session.execute(delete(Camera).where(Camera.camera_id.in_(ids)))
        await session.commit()
    print(f"Removed {result.rowcount or 0} government camera(s).")


async def verify_fixture(fixture: dict) -> None:
    expected = {camera["camera_id"] for camera in fixture["cameras"]}
    async with async_session() as session:
        rows = (await session.execute(select(Camera).where(Camera.camera_id.in_(expected)))).scalars().all()
    present = {camera.camera_id for camera in rows}
    missing = sorted(expected - present)
    unplaced = sorted(camera.camera_id for camera in rows if camera.latitude is None or camera.longitude is None)
    print(f"{len(present)}/{len(expected)} government camera(s) present.")
    if missing:
        print(f"  missing: {', '.join(missing)}")
    if unplaced:
        print(f"  present but unplaced (no coordinates): {', '.join(unplaced)}")
    if missing:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--reset", action="store_true", help="remove the fixture's cameras instead of loading them")
    group.add_argument("--verify", action="store_true", help="report what is present without writing")
    args = parser.parse_args()

    fixture = _load_fixture()
    if args.reset:
        asyncio.run(reset_fixture(fixture))
    elif args.verify:
        asyncio.run(verify_fixture(fixture))
    else:
        asyncio.run(seed_fixture(fixture))


if __name__ == "__main__":
    main()
