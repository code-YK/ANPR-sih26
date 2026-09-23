"""Camera lookup tools."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.registry import (
    RENDER_CAMERA_PICKER,
    ToolContext,
    tool,
)
from app.auth_service import authorised_departments, get_authorised_camera
from app.models.camera import Camera, CameraHealthObservation
from app.routers.cameras import _camera_list_statement


def camera_brief(camera: Camera) -> dict:
    """The compact projection every camera-returning tool emits.

    Deliberately not CameraOut: a full registry row is ~30 fields, and a
    20-camera answer at that width costs more context than the rest of the
    conversation. Everything an operator would ask about is here; the
    Registry page has the rest.
    """
    return {
        "camera_id": camera.camera_id,
        "name": camera.name,
        "location": camera.location_text,
        "department": camera.department,
        "is_live": camera.is_live,
        "anpr_viable": camera.anpr_viable,
        "anpr_running": camera.analytics_finetuned_enabled,
        "baseline_vehicle_running": camera.analytics_enabled,
        "latitude": float(camera.latitude) if camera.latitude is not None else None,
        "longitude": float(camera.longitude) if camera.longitude is not None else None,
    }


class ListCamerasParams(BaseModel):
    query: str | None = Field(
        default=None,
        description="Free text matched against camera id, name, location and department.",
    )
    only_live: bool | None = Field(default=None, description="Restrict to cameras currently live.")
    only_anpr_viable: bool | None = Field(
        default=None, description="Restrict to cameras marked viable for plate recognition."
    )
    limit: int = Field(default=25, ge=1, le=100)


@tool(
    name="list_cameras",
    description=(
        "List cameras in the registry, optionally filtered by free text, live status or ANPR "
        "viability. Use this for questions like 'which cameras are down' or 'how many cameras "
        "do we have'. Pair with navigate_to(page='registry'). To let the user pick a specific "
        "camera on a map, use find_cameras_near instead."
    ),
    params=ListCamerasParams,
)
async def list_cameras(params: ListCamerasParams, ctx: ToolContext) -> dict:
    stmt = _camera_list_statement(
        auth=ctx.auth,
        department=None,
        camera_type=None,
        anpr_viable=params.only_anpr_viable,
        is_live=params.only_live,
        q=params.query,
    ).limit(params.limit)
    cameras = (await ctx.session.execute(stmt)).scalars().all()
    return {"count": len(cameras), "cameras": [camera_brief(c) for c in cameras]}


class FindCamerasNearParams(BaseModel):
    place: str = Field(
        description="Place, road, landmark or camera name the user mentioned, e.g. 'MG Road'."
    )
    limit: int = Field(default=12, ge=1, le=30)


@tool(
    name="find_cameras_near",
    description=(
        "Find cameras matching a place, road or landmark the user named instead of a camera id. "
        "Returns candidates rendered as a tappable map so the user can choose. Use this whenever "
        "the user refers to a camera by location rather than id -- never guess a camera id."
    ),
    params=FindCamerasNearParams,
    render=RENDER_CAMERA_PICKER,
)
async def find_cameras_near(params: FindCamerasNearParams, ctx: ToolContext) -> dict:
    stmt = _camera_list_statement(
        auth=ctx.auth,
        department=None,
        camera_type=None,
        anpr_viable=None,
        is_live=None,
        q=params.place,
    ).limit(params.limit)
    cameras = (await ctx.session.execute(stmt)).scalars().all()
    briefs = [camera_brief(c) for c in cameras]
    return {
        "query": params.place,
        "count": len(briefs),
        "cameras": briefs,
        # The picker needs coordinates; without them the frontend falls back
        # to a plain list, so say which case this is rather than letting the
        # model guess from the payload.
        "mappable": sum(1 for b in briefs if b["latitude"] is not None),
    }


class CameraIdParams(BaseModel):
    camera_id: str = Field(description="Exact camera id, e.g. 'cam07'.")


@tool(
    name="get_camera",
    description=(
        "Full detail for one camera by its exact id, including whether analytics are running. "
        "Pair with navigate_to(page='live_camera', camera_id=...) when the user wants to watch it."
    ),
    params=CameraIdParams,
)
async def get_camera(params: CameraIdParams, ctx: ToolContext) -> dict:
    camera = await get_authorised_camera(ctx.session, ctx.auth, params.camera_id, "viewer")
    detail = camera_brief(camera)
    detail.update(
        {
            "camera_number": camera.camera_number,
            "camera_type": camera.camera_type,
            "health_reason": camera.health_reason,
            "last_successful_connect": (
                camera.last_successful_connect.isoformat() if camera.last_successful_connect else None
            ),
            "stream_available": camera.stream_available,
            "anpr_notes": camera.anpr_notes,
        }
    )
    return detail


class CameraHealthParams(BaseModel):
    camera_id: str = Field(description="Exact camera id.")
    limit: int = Field(default=10, ge=1, le=50)


@tool(
    name="get_camera_health",
    description=(
        "Recent health observations for one camera -- use when asked why a camera is down or "
        "unreliable. Pair with navigate_to(page='registry')."
    ),
    params=CameraHealthParams,
)
async def get_camera_health(params: CameraHealthParams, ctx: ToolContext) -> dict:
    await get_authorised_camera(ctx.session, ctx.auth, params.camera_id, "viewer")
    stmt = (
        select(CameraHealthObservation)
        .where(CameraHealthObservation.camera_id == params.camera_id)
        .order_by(CameraHealthObservation.observed_at.desc())
        .limit(params.limit)
    )
    rows = (await ctx.session.execute(stmt)).scalars().all()
    return {
        "camera_id": params.camera_id,
        "observations": [
            {
                "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                "status": row.status,
                "transport_ok": row.transport_ok,
                "is_live": row.is_live,
                "reason": row.reason,
            }
            for row in rows
        ],
    }


__all__ = [
    "camera_brief",
    "find_cameras_near",
    "get_camera",
    "get_camera_health",
    "list_cameras",
    "authorised_departments",
]
