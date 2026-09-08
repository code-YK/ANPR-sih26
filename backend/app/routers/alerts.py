from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import (
    AuthContext,
    add_audit_event,
    authorised_departments,
    get_current_auth,
    require_department_access,
    require_worker_token,
)
from app.db import get_session
from app.models.alert import Alert
from app.models.camera import Camera, Sighting
from app.models.watchlist import WatchlistEntry
from app.schemas import AlertOut, SuspiciousAlertCreate

router = APIRouter()

# One open suspicious alert per (camera, track) suppresses further ones for
# this long -- same idea as the ANPR ALERT_DEDUP_WINDOW, so a person who
# lingers in frame raises one alert, not one per frame. A track id is only
# unique within a single worker run, which is exactly the scope we want:
# a genuinely new detection after a restart should re-alert.
SUSPICIOUS_DEDUP_WINDOW = timedelta(minutes=15)


def _detail_stmt():
    """Alert joined to the plate/camera/watchlist context the UI needs to
    show anything meaningful. The sighting and watchlist joins are OUTER:
    a "suspicious" alert has neither, and carries its own label/severity on
    the alert row instead. The camera join stays inner -- camera_id is
    non-nullable, so a camera always resolves."""
    return (
        select(Alert, Sighting.plate, Sighting.evidence_path, Camera.name, Camera.location_text,
               Camera.department, WatchlistEntry.reason_code, WatchlistEntry.severity)
        .outerjoin(Sighting, Sighting.id == Alert.sighting_id)
        .join(Camera, Camera.camera_id == Alert.camera_id)
        .outerjoin(WatchlistEntry, WatchlistEntry.id == Alert.watchlist_entry_id)
    )


def _to_out(row) -> AlertOut:
    alert, plate, evidence_path, camera_name, location_text, department, reason_code, severity = row
    return AlertOut(
        id=alert.id,
        sighting_id=alert.sighting_id,
        watchlist_entry_id=alert.watchlist_entry_id,
        camera_id=alert.camera_id,
        alert_type=alert.alert_type,
        event_time=alert.event_time,
        match_confidence=float(alert.match_confidence) if alert.match_confidence is not None else None,
        dedup_key=alert.dedup_key,
        status=alert.status,
        acknowledged_at=alert.acknowledged_at,
        resolved_at=alert.resolved_at,
        created_at=alert.created_at,
        plate=plate,
        label=alert.label,
        has_evidence=bool(evidence_path),
        camera_name=camera_name,
        location_text=location_text,
        department=department,
        reason_code=reason_code,
        # A watchlist alert takes severity from its entry; a suspicious alert
        # carries its own on the row.
        severity=severity if severity is not None else alert.severity,
    )


@router.post("/alerts/suspicious", response_model=AlertOut, status_code=201)
async def create_suspicious_alert(
    payload: SuspiciousAlertCreate,
    _worker: None = Depends(require_worker_token),
    session: AsyncSession = Depends(get_session),
):
    """Raise a standalone alert for a person classified as potentially
    dangerous by the suspicious-activity worker (best.pt).

    No sighting, no watchlist entry, no journey -- there is no plate or
    identity here. Deduplicated per (camera, track) within
    SUSPICIOUS_DEDUP_WINDOW so a lingering person raises one alert, not one
    per frame. An acknowledged/resolved alert never suppresses a fresh one.
    """
    camera = await session.get(Camera, payload.camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera {payload.camera_id!r} not found")

    event_time = payload.event_time or datetime.now(timezone.utc)
    dedup_key = f"suspicious:{payload.camera_id}:{payload.track_id}"
    recent_cutoff = event_time - SUSPICIOUS_DEDUP_WINDOW
    existing_open = (
        await session.execute(
            select(Alert)
            .where(
                Alert.dedup_key == dedup_key,
                Alert.status == "open",
                Alert.event_time >= recent_cutoff,
            )
            .order_by(Alert.event_time.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing_open is not None:
        return _to_out(await _get_detail(session, existing_open.id))

    alert = Alert(
        sighting_id=None,
        watchlist_entry_id=None,
        camera_id=payload.camera_id,
        alert_type="suspicious",
        label=payload.label,
        severity=payload.severity,
        event_time=event_time,
        match_confidence=payload.confidence,
        dedup_key=dedup_key,
        status="open",
    )
    session.add(alert)
    await session.commit()
    return _to_out(await _get_detail(session, alert.id))


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    status: str | None = None,
    camera_id: str | None = None,
    limit: int = 200,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    stmt = _detail_stmt()
    allowed = authorised_departments(auth)
    if allowed is not None:
        stmt = stmt.where(Camera.department.in_(allowed))
    if status is not None:
        stmt = stmt.where(Alert.status == status)
    if camera_id is not None:
        stmt = stmt.where(Alert.camera_id == camera_id)
    stmt = stmt.order_by(Alert.event_time.desc()).limit(min(limit, 1000))
    rows = (await session.execute(stmt)).all()
    return [_to_out(row) for row in rows]


async def _get_detail(session: AsyncSession, alert_id: int):
    stmt = _detail_stmt().where(Alert.id == alert_id)
    row = (await session.execute(stmt)).first()
    return row


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    if alert.status == "resolved":
        raise HTTPException(status_code=409, detail="Alert is already resolved")
    camera = await session.get(Camera, alert.camera_id)
    require_department_access(auth, camera.department if camera else None, "operator")
    alert.status = "acknowledged"
    alert.acknowledged_at = datetime.now(timezone.utc)
    add_audit_event(
        session,
        actor=auth.user,
        action="alert.acknowledged",
        target_type="alert",
        target_id=alert.id,
        department=camera.department,
        result="success",
    )
    await session.commit()
    return _to_out(await _get_detail(session, alert_id))


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
async def resolve_alert(
    alert_id: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    camera = await session.get(Camera, alert.camera_id)
    require_department_access(auth, camera.department if camera else None, "operator")
    alert.status = "resolved"
    alert.resolved_at = datetime.now(timezone.utc)
    add_audit_event(
        session,
        actor=auth.user,
        action="alert.resolved",
        target_type="alert",
        target_id=alert.id,
        department=camera.department,
        result="success",
    )
    await session.commit()
    return _to_out(await _get_detail(session, alert_id))
