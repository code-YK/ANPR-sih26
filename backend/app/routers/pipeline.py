import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import AuthContext, add_audit_event, get_authorised_camera, get_current_auth, require_super_admin
from app.config import get_settings
from app.db import get_session
from app.models.camera import Camera
from app.pipeline.capture import capture_survey_frame
from app.pipeline.geocode import run_geocoding, search_locations
from app.pipeline.probe import run_stream_probe
from app.pipeline.sync import run_catalogue_sync
from app.schemas import GeocodeRunResult, GeocodeSearchResult, ProbeRunResult, SyncResult

router = APIRouter()


@router.post("/sync", response_model=SyncResult)
async def sync_catalogue(
    auth: AuthContext = Depends(get_current_auth), session: AsyncSession = Depends(get_session)
):
    require_super_admin(auth)
    try:
        return await run_catalogue_sync(session)
    except httpx.HTTPError as exc:
        # The sandbox catalogue being down is an upstream dependency
        # failure, not a fault in this service. Reporting it as our own
        # opaque 500 sent an operator looking for a bug on our side; 502
        # with the upstream status says where the problem actually is.
        raise HTTPException(
            status_code=502,
            detail=f"Sandbox catalogue API unavailable: {exc}",
        ) from exc


@router.post("/probe", response_model=ProbeRunResult)
async def probe_streams(
    camera_id: str | None = None,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    if camera_id is None:
        require_super_admin(auth)
    else:
        await get_authorised_camera(session, auth, camera_id, "operator")
    try:
        result = await run_stream_probe(session, camera_id=camera_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    add_audit_event(
        session,
        actor=auth.user,
        action="camera.probed",
        target_type="camera" if camera_id else "camera_registry",
        target_id=camera_id,
        result="success" if all(item.transport_ok != "none" for item in result.results) else "partial",
        details={"probed": result.probed, "offline": sum(item.transport_ok == "none" for item in result.results)},
    )
    await session.commit()
    return result


@router.post("/geocode", response_model=GeocodeRunResult)
async def geocode_cameras(
    camera_id: str | None = None,
    force: bool = False,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    if camera_id is None:
        require_super_admin(auth)
    else:
        await get_authorised_camera(session, auth, camera_id, "operator")
    try:
        return await run_geocoding(session, camera_id=camera_id, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/geocode/search", response_model=list[GeocodeSearchResult])
async def geocode_search(q: str, _auth: AuthContext = Depends(get_current_auth)):
    """Free-text place search for the registry's map-picker search box (not
    part of the onboarding pipeline -- see search_locations's docstring)."""
    if not q.strip():
        return []
    return await search_locations(q)


@router.post("/survey/capture")
async def capture_survey(
    camera_id: str | None = None,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    if camera_id is None:
        require_super_admin(auth)
    else:
        await get_authorised_camera(session, auth, camera_id, "operator")
    stmt = select(Camera)
    if camera_id is not None:
        stmt = stmt.where(Camera.camera_id == camera_id)
    cameras = (await session.execute(stmt)).scalars().all()
    if camera_id is not None and not cameras:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id!r} not found")

    captured = {}
    for camera in cameras:
        path = await capture_survey_frame(camera)
        captured[camera.camera_id] = path is not None
    return {"attempted": len(cameras), "captured": captured}


@router.get("/survey/{camera_id}/frame")
async def get_survey_frame(
    camera_id: str,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    await get_authorised_camera(session, auth, camera_id, "viewer")
    settings = get_settings()
    path = os.path.join(settings.survey_dir, f"cam{camera_id}.jpg")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No survey frame captured for this camera yet")
    return FileResponse(path, media_type="image/jpeg")
