"""Stage 4 -- geocoding.

Forward-geocodes location_text -> lat/lng once at onboarding, via Nominatim.
Respects the 1 req/sec usage policy. On failure, leaves lat/lng null and
sets geocode_confidence='failed' so the map honestly shows the camera as
unplaced rather than silently wrong.
"""

import asyncio
import logging
import re

import httpx
from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.camera import Camera
from app.schemas import GeocodeResult, GeocodeRunResult

logger = logging.getLogger("sentinel.pipeline.geocode")

# Gujarat's approximate bounding box, used only to bias results toward the
# right part of India -- Nominatim's viewbox is a hint, not a hard filter.
GUJARAT_VIEWBOX = "68.1,24.7,74.5,20.1"

_NOMINATIM_MIN_INTERVAL = 1.05  # seconds; stay under the 1 req/sec policy


def _fallback_query(location_text: str) -> str | None:
    """Strip a leading numeric label (e.g. "36 bilimora" -> "bilimora") and
    add an explicit state qualifier. Many sandbox location strings are a
    site-survey number plus a real town/landmark name; Nominatim often can't
    resolve the numbered label but can resolve the bare name once qualified.
    Returns None when there's nothing left to try (no leading number, or the
    remainder is empty).
    """
    stripped = re.sub(r"^\d+\s*", "", location_text).strip()
    if not stripped or stripped == location_text:
        return None
    return f"{stripped}, Gujarat, India"


async def _nominatim_search(client: httpx.AsyncClient, query: str) -> dict | None:
    settings = get_settings()
    params = {
        "q": query,
        "format": "json",
        "countrycodes": "in",
        "viewbox": GUJARAT_VIEWBOX,
        "bounded": 1,  # hard-bound to Gujarat: an ambiguous name like "Janpath" must
                        # not silently resolve to its Delhi namesake instead of failing.
        "limit": 1,
    }
    headers = {"User-Agent": settings.nominatim_user_agent}

    try:
        resp = await client.get(settings.nominatim_url, params=params, headers=headers, timeout=15.0)
        resp.raise_for_status()
        results = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("geocode request failed for %r: %s", query, exc)
        return None

    return results[0] if results else None


async def search_locations(query: str, limit: int = 5) -> list[dict]:
    """Interactive free-text search for the registry's map-picker search box.

    Unlike `_nominatim_search` (single top hit, hard-bounded to Gujarat for
    the automated onboarding pipeline), this is soft-biased only -- an
    operator manually correcting a pin needs to be able to search for a
    real place just outside the bounding box without it being silently
    dropped. No rate-limit sleep here: this is one interactive request, not
    a batch loop: the frontend debounces keystrokes so it naturally stays
    well under the 1 req/sec policy.
    """
    settings = get_settings()
    params = {
        "q": query,
        "format": "json",
        "countrycodes": "in",
        "viewbox": GUJARAT_VIEWBOX,
        "limit": limit,
    }
    headers = {"User-Agent": settings.nominatim_user_agent}

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(settings.nominatim_url, params=params, headers=headers, timeout=15.0)
            resp.raise_for_status()
            results = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("location search failed for %r: %s", query, exc)
            return []

    return [
        {"display_name": r["display_name"], "latitude": float(r["lat"]), "longitude": float(r["lon"])}
        for r in results
    ]


async def _geocode_one(client: httpx.AsyncClient, location_text: str) -> tuple[float, float, str] | None:
    top = await _nominatim_search(client, location_text)
    confidence = "approximate"

    if top is None:
        fallback = _fallback_query(location_text)
        if fallback is None:
            return None
        await asyncio.sleep(_NOMINATIM_MIN_INTERVAL)
        top = await _nominatim_search(client, fallback)
        if top is None:
            return None
        # A cleaned-up query matching a real place is a weaker signal than
        # the raw sandbox string matching directly -- still not "exact"
        # (manual correction owns that tier), but flagged distinctly in logs.
        logger.info("geocoded %r via fallback query %r", location_text, fallback)

    try:
        lat = float(top["lat"])
        lon = float(top["lon"])
    except (KeyError, ValueError):
        return None

    # Sandbox location strings are landmark/site labels, not postal
    # addresses -- even a confident Nominatim match is never treated as
    # 'exact'. Only a manual operator correction earns that tier.
    return lat, lon, confidence


async def run_geocoding(session: AsyncSession, camera_id: str | None = None, force: bool = False) -> GeocodeRunResult:
    stmt = select(Camera)
    if camera_id is not None:
        stmt = stmt.where(Camera.camera_id == camera_id)
    # A manual operator correction (geocode_confidence='exact') is an
    # authoritative override, not an automated guess -- never silently
    # clobber it with a re-run, even under force. Clearing it is a
    # deliberate operator action via PUT, not this pipeline stage.
    if force:
        stmt = stmt.where(Camera.geocode_confidence.is_distinct_from("exact"))
    else:
        stmt = stmt.where(Camera.geocode_confidence.is_(None))
    cameras = (await session.execute(stmt)).scalars().all()
    if camera_id is not None and not cameras and force:
        raise ValueError(f"Camera {camera_id!r} not found, or its geocode is a manual 'exact' correction")

    results: list[GeocodeResult] = []
    async with httpx.AsyncClient() as client:
        for camera in cameras:
            geocoded = await _geocode_one(client, camera.location_text)
            if geocoded is None:
                camera.latitude = None
                camera.longitude = None
                camera.geocode_confidence = "failed"
                results.append(
                    GeocodeResult(camera_id=camera.camera_id, latitude=None, longitude=None, geocode_confidence="failed")
                )
            else:
                lat, lon, confidence = geocoded
                camera.latitude = lat
                camera.longitude = lon
                camera.geocode_confidence = confidence
                camera.geog = WKTElement(f"POINT({lon} {lat})", srid=4326)
                results.append(
                    GeocodeResult(
                        camera_id=camera.camera_id, latitude=lat, longitude=lon, geocode_confidence=confidence
                    )
                )
            await asyncio.sleep(_NOMINATIM_MIN_INTERVAL)

    await session.commit()

    return GeocodeRunResult(geocoded=len(results), results=results)
