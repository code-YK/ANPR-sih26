"""Vehicle investigation tools: journey tracing, plate search, sightings."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.registry import ToolContext, tool
from app.routers.investigate import search_by_plate
from app.routers.sightings import list_sightings as _list_sightings
from app.routers.sightings import vehicle_journey
from app.schemas import PlateSearchQuery


class PlateParams(BaseModel):
    plate: str = Field(description="Registration number, full or partial, as the user said it.")


@tool(
    name="trace_vehicle",
    description=(
        "Full movement history for one plate: every sighting, in order, with camera and location. "
        "This is the tool for 'trace', 'track', 'where has this car been', 'show me its route'. "
        "Always pair with navigate_to(page='journeys_plate', plate=...) so the operator gets the "
        "map and timeline. Returns an empty journey rather than an error when the plate is unknown."
    ),
    params=PlateParams,
)
async def trace_vehicle(params: PlateParams, ctx: ToolContext) -> dict:
    journey = await vehicle_journey(plate=params.plate, auth=ctx.auth, session=ctx.session)

    # Only the first and last few stops go to the model. A 200-stop journey
    # would dominate the context window and slow every later turn, and the
    # operator is about to see the whole thing on the Journey page anyway.
    stops = journey.stops
    sample = stops if len(stops) <= 8 else stops[:4] + stops[-4:]
    return {
        "plate": journey.plate,
        "sighting_count": journey.sighting_count,
        "camera_count": journey.camera_count,
        "first_seen": journey.first_seen.isoformat() if journey.first_seen else None,
        "last_seen": journey.last_seen.isoformat() if journey.last_seen else None,
        "restricted_stops": journey.restricted_stops,
        "stops_shown": len(sample),
        "stops": [
            {
                "camera_id": stop.camera_id,
                "camera_name": stop.camera_name,
                "location": stop.location_text,
                "seen_at": stop.seen_at.isoformat(),
                "confidence": stop.confidence,
                "vehicle_type": stop.vehicle_type,
            }
            for stop in sample
        ],
    }


class SearchPlateParams(BaseModel):
    plate: str = Field(description="Registration number, full or partial.")
    fuzzy: bool = Field(
        default=True,
        description="Fuzzy matching tolerates OCR errors and partial plates. Keep true unless the "
        "user insists on an exact match.",
    )
    limit: int = Field(default=20, ge=1, le=50)


@tool(
    name="search_plate",
    description=(
        "Search uploaded recordings for a plate and return matching vehicle tracks. This searches "
        "*investigation footage*, not live sightings. Use it for 'find this car in the footage' or "
        "'which recordings show this plate'. For where a vehicle has physically been, use "
        "trace_vehicle instead. Pair with navigate_to(page='investigate')."
    ),
    params=SearchPlateParams,
)
async def search_plate(params: SearchPlateParams, ctx: ToolContext) -> dict:
    hits = await search_by_plate(
        payload=PlateSearchQuery(plate=params.plate, fuzzy=params.fuzzy, limit=params.limit),
        auth=ctx.auth,
        session=ctx.session,
    )
    return {
        "query": params.plate,
        "count": len(hits),
        "hits": [
            {
                "matched_plate": hit.matched_plate,
                "match_kind": hit.match_kind,
                "recording_id": hit.recording.id,
                "recording_filename": hit.recording.original_filename,
                "recording_location": hit.recording.location_text,
                "run_id": hit.track.run_id,
                "track_ref": hit.track.track_ref,
                "vehicle_type": hit.track.kind,
                "plate_confidence": hit.track.plate_confidence,
            }
            for hit in hits
        ],
    }


class ListSightingsParams(BaseModel):
    plate: str | None = Field(default=None, description="Filter to one plate.")
    camera_id: str | None = Field(default=None, description="Filter to one camera.")
    limit: int = Field(default=25, ge=1, le=100)


@tool(
    name="list_sightings",
    description=(
        "Live ANPR sightings, newest first, filtered by plate and/or camera. At least one filter "
        "is required -- if the user gives neither, ask which plate or camera they mean rather "
        "than listing everything. Pair with navigate_to(page='investigate')."
    ),
    params=ListSightingsParams,
)
async def list_sightings(params: ListSightingsParams, ctx: ToolContext) -> dict:
    if not params.plate and not params.camera_id:
        return {
            "error": "Needs a plate or a camera to filter by. Ask the user which one they mean.",
            "sightings": [],
        }
    rows = await _list_sightings(
        plate=params.plate,
        camera_id=params.camera_id,
        since=None,
        until=None,
        limit=params.limit,
        auth=ctx.auth,
        session=ctx.session,
    )
    return {
        "count": len(rows),
        "sightings": [
            {
                "sighting_id": row.id,
                "plate": row.plate,
                "camera_id": row.camera_id,
                "seen_at": row.seen_at.isoformat() if row.seen_at else None,
                "confidence": float(row.confidence) if row.confidence is not None else None,
            }
            for row in rows
        ],
    }


__all__ = ["list_sightings", "search_plate", "trace_vehicle"]
