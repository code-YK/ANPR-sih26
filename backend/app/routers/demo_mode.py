import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import AuthContext, get_current_auth, require_super_admin
from app.config import get_settings
from app.db import get_session
from app.schemas import DemoModeStatus, DemoModeToggle
from app.services import demo_mode as demo_mode_service

router = APIRouter()


@router.get("/admin/demo-mode", response_model=DemoModeStatus)
async def get_demo_mode_status(_auth: AuthContext = Depends(get_current_auth)):
    """Any authenticated user may read this -- not just super admin -- so the
    Live view can safely check whether to render decorative filler tiles.
    Only the toggle itself (below) is super-admin-gated."""
    return await demo_mode_service.get_status()


@router.post("/admin/demo-mode/toggle", response_model=DemoModeStatus)
async def toggle_demo_mode(
    payload: DemoModeToggle,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    require_super_admin(auth)
    try:
        if payload.enabled:
            return await demo_mode_service.enable(session, auth)
        return await demo_mode_service.disable(session, auth)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/demo/filler-image/{index}")
async def demo_filler_image(index: int, _auth: AuthContext = Depends(get_current_auth)):
    """Background imagery for LiveView's decorative wall-filler tiles
    (DecorativeCameraTile.jsx) -- reuses the same onboarding-survey stills
    already served, per-camera, by GET /survey/{camera_id}/frame (see
    pipeline.py) rather than shipping separate placeholder assets. `index`
    is whatever the tile itself is (0..N-1); taken modulo however many
    stills currently exist so every tile gets *a* real photo without the
    frontend needing to know the count in advance."""
    settings = get_settings()
    survey_dir = settings.survey_dir
    files = sorted(f for f in os.listdir(survey_dir) if f.lower().endswith(".jpg")) if os.path.isdir(survey_dir) else []
    if not files:
        raise HTTPException(status_code=404, detail="No survey imagery available on this machine")
    return FileResponse(os.path.join(survey_dir, files[index % len(files)]), media_type="image/jpeg")
