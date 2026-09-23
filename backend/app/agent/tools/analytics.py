"""Live analytics tools: worker status and start/stop.

Two different mechanisms live here, and conflating them is the easiest
mistake to make in this codebase:

* **ANPR** is backend mode `vehicle_finetuned`. Its on/off intent is a
  persistent *camera column* (`analytics_finetuned_enabled`) that a
  supervisor reconciles roughly every 10 seconds. Setting it goes through
  camera administration rights, not operator clearance, and the worker does
  not exist the instant the call returns -- it may be queued.
* **Person / Suspicious** are plain start/stop subprocesses via
  POST /analytics/{start,stop}, gated on operator clearance for the camera's
  department.

The console calls `vehicle_finetuned` "ANPR"; these tools speak the console's
vocabulary outward and translate inward, so the model never has to.
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.agent.registry import RENDER_WORKER_LIST, ToolContext, tool
from app.auth_service import add_audit_event, get_authorised_camera
from app.config import get_settings
from app.models.camera import Camera
from app.routers import analytics as analytics_router
from app.routers.cameras import _apply_operator_update
from app.schemas import CameraOperatorUpdate

# Console vocabulary -> backend worker mode.
MANUAL_MODES = {"person": "person", "suspicious": "suspicious"}
ANPR_BACKEND_MODE = "vehicle_finetuned"

_MODE_LABEL = {
    "vehicle_finetuned": "ANPR",
    "vehicle": "ANPR (baseline model)",
    "person": "Person",
    "suspicious": "Suspicious",
}


def _worker_brief(row: dict) -> dict:
    return {
        "camera_id": row.get("camera_id"),
        "mode": _MODE_LABEL.get(row.get("mode"), row.get("mode")),
        "backend_mode": row.get("mode"),
        "state": row.get("state"),
        "running": row.get("running"),
        "queue_position": row.get("queue_position"),
        "started_at": row["started_at"].isoformat() if row.get("started_at") else None,
        "last_error": row.get("last_error"),
    }


async def _require_camera_admin(camera_id: str, ctx: ToolContext) -> Camera:
    """The camera-administration rule from routers/cameras.py's PUT handler.

    ANPR intent lives on the camera row, so turning it on is a camera edit,
    not an analytics operation -- a department_user with operator clearance
    can start Person analytics but cannot start ANPR.
    """
    camera = await ctx.session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id!r} not found")
    if ctx.auth.is_super_admin:
        return camera
    if ctx.auth.is_department_admin and camera.department == ctx.auth.user.home_department:
        return camera
    raise HTTPException(
        status_code=403,
        detail="Starting or stopping ANPR requires camera administration rights for that camera's department",
    )


class NoParams(BaseModel):
    pass


@tool(
    name="list_workers",
    description=(
        "Every analytics worker that is running, queued or backing off, across all cameras the "
        "user may see. Use this for 'what's running', 'list workers', 'is ANPR on anywhere'. "
        "The result renders as a list with a Stop button on each row, so do not also ask the "
        "user which one they want to stop -- they can click. Needs no navigation."
    ),
    params=NoParams,
    render=RENDER_WORKER_LIST,
)
async def list_workers(_params: NoParams, ctx: ToolContext) -> dict:
    rows = await analytics_router.analytics_status(auth=ctx.auth, session=ctx.session)
    briefs = [_worker_brief(row) for row in rows]
    settings = get_settings()
    return {
        "count": len(briefs),
        "running": sum(1 for b in briefs if b["running"]),
        "workers": briefs,
        "capacity": {
            "ANPR": settings.max_concurrent_vehicle_finetuned_workers,
            "Person": settings.max_concurrent_person_workers,
            "Suspicious": settings.max_concurrent_suspicious_workers,
        },
    }


@tool(
    name="get_capacity",
    description=(
        "The configured maximum number of concurrent workers per analytics mode. Use it to "
        "explain a 'at capacity' failure, or when the user asks how many cameras can run at once."
    ),
    params=NoParams,
)
async def get_capacity(_params: NoParams, _ctx: ToolContext) -> dict:
    settings = get_settings()
    return {
        "ANPR": settings.max_concurrent_vehicle_finetuned_workers,
        "ANPR_baseline": settings.max_concurrent_vehicle_workers,
        "Person": settings.max_concurrent_person_workers,
        "Suspicious": settings.max_concurrent_suspicious_workers,
    }


class AnprParams(BaseModel):
    camera_id: str = Field(
        description="Exact camera id. Never guess this -- use find_cameras_near if the user named "
        "a place instead of an id."
    )


async def _set_anpr(camera_id: str, enabled: bool, ctx: ToolContext) -> dict:
    camera = await _require_camera_admin(camera_id, ctx)
    _apply_operator_update(camera, CameraOperatorUpdate(analytics_finetuned_enabled=enabled))
    add_audit_event(
        ctx.session,
        actor=ctx.auth.user,
        action="camera.updated",
        target_type="camera",
        target_id=camera.camera_id,
        department=camera.department,
        result="success",
        details={"fields": ["analytics_finetuned_enabled"], "via": "copilot"},
    )
    await ctx.session.commit()

    # Report what is actually true now, not what was requested. The
    # supervisor reconciles on its own ~10s cycle, so a just-enabled camera
    # is typically "queued", and claiming it is running would be a lie the
    # operator acts on.
    states = await analytics_router.analytics_status_one(
        camera_id=camera_id, auth=ctx.auth, session=ctx.session
    )
    current = next((s for s in states if s.get("mode") == ANPR_BACKEND_MODE), None)
    return {
        "camera_id": camera_id,
        "camera_name": camera.name,
        "anpr_enabled": enabled,
        "state": (current or {}).get("state", "starting" if enabled else "stopped"),
        "queue_position": (current or {}).get("queue_position"),
        "note": (
            "Intent recorded. A supervisor picks it up within about 10 seconds; "
            "the worker is not running until its state says so."
            if enabled
            else "ANPR intent cleared for this camera."
        ),
    }


@tool(
    name="start_anpr",
    description=(
        "Turn on number-plate recognition for one camera. Requires camera administration rights. "
        "This records intent -- a supervisor starts the worker within about 10 seconds, and the "
        "camera may be queued if all ANPR slots are busy. Report the returned state honestly; do "
        "not say it is running unless the state says running. Pair with "
        "navigate_to(page='live_camera', camera_id=...)."
    ),
    params=AnprParams,
    mutating=True,
)
async def start_anpr(params: AnprParams, ctx: ToolContext) -> dict:
    return await _set_anpr(params.camera_id, True, ctx)


@tool(
    name="stop_anpr",
    description=(
        "Turn off number-plate recognition for one camera. Requires camera administration rights. "
        "Reversible -- it can be started again at any time."
    ),
    params=AnprParams,
    mutating=True,
)
async def stop_anpr(params: AnprParams, ctx: ToolContext) -> dict:
    return await _set_anpr(params.camera_id, False, ctx)


class ManualWorkerParams(BaseModel):
    camera_id: str = Field(description="Exact camera id.")
    mode: str = Field(description="Either 'person' or 'suspicious'. ANPR uses start_anpr instead.")


def _check_mode(mode: str) -> str:
    backend_mode = MANUAL_MODES.get(mode.strip().lower())
    if backend_mode is None:
        raise HTTPException(
            status_code=422,
            detail="mode must be 'person' or 'suspicious'. For number-plate recognition use start_anpr.",
        )
    return backend_mode


@tool(
    name="start_worker",
    description=(
        "Start Person-counting or Suspicious-activity analytics on one camera. Requires operator "
        "clearance for that camera's department. Not for ANPR -- use start_anpr. If this returns "
        "a capacity error, tell the user which cameras hold the slots and offer to stop one."
    ),
    params=ManualWorkerParams,
    mutating=True,
)
async def start_worker(params: ManualWorkerParams, ctx: ToolContext) -> dict:
    backend_mode = _check_mode(params.mode)
    await get_authorised_camera(ctx.session, ctx.auth, params.camera_id, "operator")
    try:
        status = await analytics_router.start_analytics(
            camera_id=params.camera_id, mode=backend_mode, model=None,
            auth=ctx.auth, session=ctx.session,
        )
    except HTTPException as exc:
        if exc.status_code == 429:
            running = await analytics_router.analytics_status(auth=ctx.auth, session=ctx.session)
            holders = [r["camera_id"] for r in running if r.get("mode") == backend_mode and r.get("running")]
            raise HTTPException(
                status_code=429,
                detail=f"At capacity for {_MODE_LABEL[backend_mode]} analytics. "
                f"Slots are held by: {', '.join(holders) or 'unknown'}. Stop one first.",
            ) from exc
        raise
    return _worker_brief(status)


@tool(
    name="stop_worker",
    description=(
        "Stop Person-counting or Suspicious-activity analytics on one camera. Requires operator "
        "clearance. Not for ANPR -- use stop_anpr. Reversible."
    ),
    params=ManualWorkerParams,
    mutating=True,
)
async def stop_worker(params: ManualWorkerParams, ctx: ToolContext) -> dict:
    backend_mode = _check_mode(params.mode)
    status = await analytics_router.stop_analytics(
        camera_id=params.camera_id, mode=backend_mode, auth=ctx.auth, session=ctx.session
    )
    return _worker_brief(status)


__all__ = [
    "get_capacity",
    "list_workers",
    "start_anpr",
    "start_worker",
    "stop_anpr",
    "stop_worker",
]
