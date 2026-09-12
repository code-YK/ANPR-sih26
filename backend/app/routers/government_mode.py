from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import AuthContext, get_current_auth, require_super_admin
from app.db import get_session
from app.schemas import GovernmentModeStatus, GovernmentModeToggle
from app.services import government_mode as government_mode_service

router = APIRouter()


@router.get("/admin/government-mode", response_model=GovernmentModeStatus)
async def get_government_mode_status(
    _auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Any authenticated user may read this -- not just super admin -- so
    the Live view can safely check whether to curate to catalogue-only
    cameras. Only the toggle itself (below) is super-admin-gated.

    `degraded=True` means the cameras this mode believes it owns no longer
    point at the relay in the database -- detection only, this read never
    writes. Re-POSTing enabled=true repairs it (see enable()'s already-active
    branch)."""
    return await government_mode_service.get_status(session)


@router.post("/admin/government-mode/toggle", response_model=GovernmentModeStatus)
async def toggle_government_mode(
    payload: GovernmentModeToggle,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    require_super_admin(auth)
    try:
        if payload.enabled:
            return await government_mode_service.enable(session, auth)
        return await government_mode_service.disable(session, auth)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
