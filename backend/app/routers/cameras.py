import csv
import io
import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.routers import analytics
from app.auth_service import (
    AuthContext,
    add_audit_event,
    authorised_departments,
    get_authorised_camera,
    get_current_auth,
    require_super_admin,
)
from app.db import get_session
from app.models.auth import Department
from app.models.camera import (
    CAMERA_TYPES,
    Camera,
    CameraHealthObservation,
    CameraMaintenanceEvent,
    CameraMaintenanceWorkOrder,
)
from app.schemas import (
    BulkImportResult,
    BulkImportRowResult,
    CameraCreate,
    CameraHealthObservationOut,
    CameraMaintenanceCreate,
    CameraMaintenanceEventOut,
    CameraMaintenanceUpdate,
    CameraMaintenanceWorkOrderOut,
    CameraOperatorUpdate,
    CameraOut,
)

_MAINTENANCE_TRANSITIONS = {
    "open": {"in_progress", "resolved", "cancelled"},
    "in_progress": {"open", "resolved", "cancelled"},
    "resolved": set(),
    "cancelled": set(),
}


def _apply_operator_update(camera: Camera, update: CameraOperatorUpdate) -> None:
    fields = update.model_dump(exclude_unset=True)

    # Manual lat/lng correction is an authoritative override: mark it
    # exact unless the caller explicitly said otherwise.
    if "latitude" in fields and "longitude" in fields and "geocode_confidence" not in fields:
        fields["geocode_confidence"] = "exact"

    for field, value in fields.items():
        setattr(camera, field, value)

    if "latitude" in fields or "longitude" in fields:
        if camera.latitude is not None and camera.longitude is not None:
            camera.geog = WKTElement(f"POINT({camera.longitude} {camera.latitude})", srid=4326)
        else:
            camera.geog = None

router = APIRouter()

_OPERATOR_CSV_COLUMNS = (
    "camera_id",
    "department",
    "ownership",
    "camera_type",
    "connectivity",
    "storage_location",
    "retention_days",
    "metadata_confidence",
    "latitude",
    "longitude",
    "geocode_confidence",
    "anpr_viable",
    "anpr_notes",
)

# This is intentionally the same safe metadata surface as CameraOut. In
# particular, source endpoints remain server-side and never enter an operator
# download, even for a super admin.
_CAMERA_EXPORT_COLUMNS = (
    "camera_id",
    "camera_number",
    "name",
    "location_text",
    "department",
    "ownership",
    "camera_type",
    "connectivity",
    "storage_location",
    "retention_days",
    "metadata_confidence",
    "latitude",
    "longitude",
    "geocode_confidence",
    "is_live",
    "transport_ok",
    "last_successful_connect",
    "health_reason",
    "anpr_viable",
    "anpr_notes",
    "last_surveyed_at",
    "analytics_enabled",
    "created_at",
    "updated_at",
)


def _camera_list_statement(
    *,
    auth: AuthContext,
    department: str | None,
    camera_type: str | None,
    anpr_viable: bool | None,
    is_live: bool | None,
    q: str | None,
):
    """Build the common, department-scoped registry query for list/export."""
    if camera_type is not None and camera_type not in CAMERA_TYPES:
        raise HTTPException(status_code=422, detail=f"camera_type must be one of {CAMERA_TYPES}")

    stmt = select(Camera)
    allowed = authorised_departments(auth)
    if allowed is not None:
        stmt = stmt.where(Camera.department.in_(allowed))
    if department is not None:
        stmt = stmt.where(Camera.department == department)
    if camera_type is not None:
        stmt = stmt.where(Camera.camera_type == camera_type)
    if anpr_viable is not None:
        stmt = stmt.where(Camera.anpr_viable == anpr_viable)
    if is_live is not None:
        stmt = stmt.where(Camera.is_live == is_live)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Camera.camera_id.ilike(pattern),
                Camera.name.ilike(pattern),
                Camera.location_text.ilike(pattern),
                Camera.department.ilike(pattern),
            )
        )
    return stmt.order_by(Camera.camera_number)


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def _export_value(value):
    """JSON-safe scalar matching the CSV export's public allowlist."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _export_row(camera: Camera) -> dict:
    return {column: _export_value(getattr(camera, column)) for column in _CAMERA_EXPORT_COLUMNS}


def _require_maintenance_admin(auth: AuthContext, camera: Camera) -> None:
    """Maintenance changes follow the existing camera-admin boundary.

    This deliberately does not expand the ADR 0003 `operator` clearance:
    remediation records can change the asset's operational state and remain
    owned by the camera's home department.
    """
    if auth.is_super_admin:
        return
    if auth.is_department_admin and camera.department == auth.user.home_department:
        return
    raise HTTPException(status_code=403, detail="Camera maintenance administration access denied")


def _maintenance_out(
    order: CameraMaintenanceWorkOrder,
    events: list[CameraMaintenanceEvent],
) -> CameraMaintenanceWorkOrderOut:
    return CameraMaintenanceWorkOrderOut(
        id=order.id,
        camera_id=order.camera_id,
        summary=order.summary,
        status=order.status,
        opened_at=order.opened_at,
        closed_at=order.closed_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
        events=[CameraMaintenanceEventOut.model_validate(event) for event in events],
    )


@router.get("/cameras", response_model=list[CameraOut])
async def list_cameras(
    department: str | None = None,
    camera_type: str | None = None,
    anpr_viable: bool | None = None,
    is_live: bool | None = None,
    q: str | None = None,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    stmt = _camera_list_statement(
        auth=auth,
        department=department,
        camera_type=camera_type,
        anpr_viable=anpr_viable,
        is_live=is_live,
        q=q,
    )
    result = await session.execute(stmt)
    return result.scalars().all()


@router.get("/cameras/export")
async def export_cameras(
    department: str | None = None,
    camera_type: str | None = None,
    anpr_viable: bool | None = None,
    is_live: bool | None = None,
    q: str | None = None,
    format: str = "csv",
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Download only the caller's filtered registry metadata as CSV or JSON."""
    if format not in {"csv", "json"}:
        raise HTTPException(status_code=422, detail="format must be csv or json")
    stmt = _camera_list_statement(
        auth=auth,
        department=department,
        camera_type=camera_type,
        anpr_viable=anpr_viable,
        is_live=is_live,
        q=q,
    )
    cameras = (await session.execute(stmt)).scalars().all()

    add_audit_event(
        session,
        actor=auth.user,
        action="camera_registry.exported",
        target_type="camera_registry",
        result="success",
        details={
            "rows": len(cameras),
            "department": department,
            "camera_type": camera_type,
            "anpr_viable": anpr_viable,
            "is_live": is_live,
            "q": q.strip() if q else None,
            "format": format,
        },
    )
    await session.commit()

    date = datetime.now(timezone.utc).date().isoformat()
    if format == "json":
        return Response(
            content=json.dumps([_export_row(camera) for camera in cameras], separators=(",", ":")),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="sentinel-camera-registry-{date}.json"'},
        )

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(_CAMERA_EXPORT_COLUMNS)
    for camera in cameras:
        writer.writerow([_csv_value(getattr(camera, column)) for column in _CAMERA_EXPORT_COLUMNS])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="sentinel-camera-registry-{date}.csv"'},
    )


@router.get("/cameras/{camera_id}", response_model=CameraOut)
async def get_camera(
    camera_id: str,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id!r} not found")
    if not auth.has_department(camera.department):
        raise HTTPException(status_code=403, detail="Department access denied")
    return camera


@router.get("/cameras/{camera_id}/health-history", response_model=list[CameraHealthObservationOut])
async def camera_health_history(
    camera_id: str,
    limit: int = 100,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Return bounded, append-only probe observations for an authorised camera."""
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    await get_authorised_camera(session, auth, camera_id, "viewer")
    stmt = (
        select(CameraHealthObservation)
        .where(CameraHealthObservation.camera_id == camera_id)
        .order_by(CameraHealthObservation.observed_at.desc(), CameraHealthObservation.id.desc())
        .limit(limit)
    )
    return (await session.execute(stmt)).scalars().all()


@router.get(
    "/cameras/{camera_id}/maintenance-work-orders",
    response_model=list[CameraMaintenanceWorkOrderOut],
)
async def camera_maintenance_work_orders(
    camera_id: str,
    limit: int = 100,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Viewer-scoped current work orders with immutable lifecycle history."""
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    await get_authorised_camera(session, auth, camera_id, "viewer")
    orders = (
        await session.execute(
            select(CameraMaintenanceWorkOrder)
            .where(CameraMaintenanceWorkOrder.camera_id == camera_id)
            .order_by(CameraMaintenanceWorkOrder.opened_at.desc(), CameraMaintenanceWorkOrder.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    if not orders:
        return []
    events = (
        await session.execute(
            select(CameraMaintenanceEvent)
            .where(CameraMaintenanceEvent.work_order_id.in_([order.id for order in orders]))
            .order_by(CameraMaintenanceEvent.occurred_at.asc(), CameraMaintenanceEvent.id.asc())
        )
    ).scalars().all()
    by_order: dict[int, list[CameraMaintenanceEvent]] = {order.id: [] for order in orders}
    for event in events:
        by_order[event.work_order_id].append(event)
    return [_maintenance_out(order, by_order[order.id]) for order in orders]


@router.post(
    "/cameras/{camera_id}/maintenance-work-orders",
    response_model=CameraMaintenanceWorkOrderOut,
    status_code=201,
)
async def create_camera_maintenance_work_order(
    camera_id: str,
    payload: CameraMaintenanceCreate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Open a department-owned remediation task for an authorised camera."""
    errors = payload.validate_content()
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    camera = await get_authorised_camera(session, auth, camera_id, "viewer")
    _require_maintenance_admin(auth, camera)
    now = datetime.now(timezone.utc)
    order = CameraMaintenanceWorkOrder(
        camera_id=camera.camera_id,
        summary=payload.summary.strip(),
        status="open",
        opened_at=now,
    )
    session.add(order)
    await session.flush()
    event = CameraMaintenanceEvent(
        work_order_id=order.id,
        occurred_at=now,
        event_type="created",
        status="open",
        note=payload.note.strip() if payload.note else None,
    )
    session.add(event)
    add_audit_event(
        session,
        actor=auth.user,
        action="camera_maintenance.created",
        target_type="camera_maintenance_work_order",
        target_id=order.id,
        department=camera.department,
        result="success",
        details={"camera_id": camera.camera_id, "status": order.status},
    )
    await session.commit()
    await session.refresh(order)
    await session.refresh(event)
    return _maintenance_out(order, [event])


@router.patch(
    "/cameras/{camera_id}/maintenance-work-orders/{work_order_id}",
    response_model=CameraMaintenanceWorkOrderOut,
)
async def update_camera_maintenance_work_order(
    camera_id: str,
    work_order_id: int,
    payload: CameraMaintenanceUpdate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Progress an open work order while retaining each lifecycle event."""
    errors = payload.validate_content()
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    camera = await get_authorised_camera(session, auth, camera_id, "viewer")
    _require_maintenance_admin(auth, camera)
    order = await session.get(CameraMaintenanceWorkOrder, work_order_id)
    if order is None or order.camera_id != camera.camera_id:
        raise HTTPException(status_code=404, detail="Maintenance work order not found for camera")
    if order.status in {"resolved", "cancelled"}:
        raise HTTPException(status_code=409, detail="Resolved or cancelled work orders are immutable")
    if payload.status == order.status and payload.note is None:
        raise HTTPException(status_code=422, detail="Status is already current; provide a note or a valid transition")

    next_status = payload.status or order.status
    if payload.status is not None and payload.status != order.status:
        if payload.status not in _MAINTENANCE_TRANSITIONS[order.status]:
            raise HTTPException(status_code=422, detail=f"Cannot transition {order.status} to {payload.status}")
        event_type = "status_changed"
    else:
        event_type = "note_added"
    now = datetime.now(timezone.utc)
    if payload.status is not None and payload.status != order.status:
        order.status = next_status
        if next_status in {"resolved", "cancelled"}:
            order.closed_at = now
    event = CameraMaintenanceEvent(
        work_order_id=order.id,
        occurred_at=now,
        event_type=event_type,
        status=next_status,
        note=payload.note.strip() if payload.note else None,
    )
    session.add(event)
    add_audit_event(
        session,
        actor=auth.user,
        action="camera_maintenance.updated",
        target_type="camera_maintenance_work_order",
        target_id=order.id,
        department=camera.department,
        result="success",
        details={"camera_id": camera.camera_id, "status": next_status, "event_type": event_type},
    )
    await session.commit()
    await session.refresh(order)
    events = (
        await session.execute(
            select(CameraMaintenanceEvent)
            .where(CameraMaintenanceEvent.work_order_id == order.id)
            .order_by(CameraMaintenanceEvent.occurred_at.asc(), CameraMaintenanceEvent.id.asc())
        )
    ).scalars().all()
    return _maintenance_out(order, events)


async def _next_manual_camera_id(session: AsyncSession) -> str:
    """manual-N, N = 1 past the highest existing manual id.

    Namespaced so a manually-registered camera can never collide with a
    camera_id assigned by a future catalogue sync (which always upserts by
    the catalogue's own numeric-ish id).
    """
    existing = (await session.execute(select(Camera.camera_id).where(Camera.camera_id.like("manual-%")))).scalars().all()
    nums = [int(cid.split("-", 1)[1]) for cid in existing if cid.split("-", 1)[1].isdigit()]
    return f"manual-{(max(nums) + 1) if nums else 1}"


async def _new_manual_camera(
    session: AsyncSession,
    *,
    name: str,
    location_text: str,
    rtsp_url: str | None = None,
    hls_url: str | None = None,
    webrtc_url: str | None = None,
) -> Camera:
    """Allocate a metadata-first camera in the manual-id namespace.

    Both the form and CSV onboarding paths use this helper. Keeping generated
    IDs in the ``manual-N`` namespace prevents an operator spreadsheet from
    colliding with a current or future catalogue-assigned camera id.
    """
    camera_id = await _next_manual_camera_id(session)
    max_number = (await session.execute(select(func.max(Camera.camera_number)))).scalar() or 0
    return Camera(
        camera_id=camera_id,
        camera_number=max_number + 1,
        name=name.strip(),
        location_text=location_text.strip(),
        rtsp_url=rtsp_url,
        hls_url=hls_url,
        webrtc_url=webrtc_url,
        is_live=None,  # unknown for a manually-registered camera; no catalogue signal
    )


@router.post("/cameras", response_model=CameraOut, status_code=201)
async def create_camera(
    payload: CameraCreate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Manual onboarding: register a camera that isn't in the sandbox catalogue.

    Metadata-only registration is allowed -- rtsp_url/hls_url/webrtc_url may
    all be omitted. The stream-probe and frame-capture stages already skip
    cameras with no URL, so an un-wired manual camera just stays unprobed
    until a URL is added later via PUT.
    """
    require_super_admin(auth)
    errors = payload.validate_choices()
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    if payload.department is not None and await session.get(Department, payload.department) is None:
        raise HTTPException(status_code=422, detail="department must reference an existing department")

    camera = await _new_manual_camera(
        session,
        name=payload.name,
        location_text=payload.location_text,
        rtsp_url=payload.rtsp_url,
        hls_url=payload.hls_url,
        webrtc_url=payload.webrtc_url,
    )

    # Reuse the same operator-field application (and manual-lat/lng ->
    # 'exact' default) logic as PUT, only passing fields the caller actually
    # provided so we don't accidentally default geocode_confidence to
    # 'exact' when no coordinates were given at all.
    provided = {
        k: v
        for k, v in {
            "department": payload.department,
            "ownership": payload.ownership,
            "camera_type": payload.camera_type,
            "connectivity": payload.connectivity,
            "storage_location": payload.storage_location,
            "retention_days": payload.retention_days,
            "metadata_confidence": payload.metadata_confidence,
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "geocode_confidence": payload.geocode_confidence,
        }.items()
        if v is not None
    }
    _apply_operator_update(camera, CameraOperatorUpdate(**provided))

    session.add(camera)
    add_audit_event(
        session,
        actor=auth.user,
        action="camera.created",
        target_type="camera",
        target_id=camera.camera_id,
        department=camera.department,
        result="success",
    )
    await session.commit()
    await session.refresh(camera)
    return camera


@router.put("/cameras/{camera_id}", response_model=CameraOut)
async def update_camera(
    camera_id: str,
    update: CameraOperatorUpdate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    errors = update.validate_choices()
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id!r} not found")

    if auth.is_super_admin:
        pass
    elif auth.is_department_admin and camera.department == auth.user.home_department:
        if "department" in update.model_fields_set and update.department != camera.department:
            raise HTTPException(status_code=403, detail="Only the super admin can reassign a camera")
    else:
        raise HTTPException(status_code=403, detail="Camera administration access denied")

    if "department" in update.model_fields_set and update.department is not None:
        if await session.get(Department, update.department) is None:
            raise HTTPException(status_code=422, detail="department must reference an existing department")

    old_department = camera.department
    _apply_operator_update(camera, update)

    add_audit_event(
        session,
        actor=auth.user,
        action="camera.updated",
        target_type="camera",
        target_id=camera.camera_id,
        department=camera.department or old_department,
        result="success",
        details={"fields": sorted(update.model_fields_set)},
    )

    await session.commit()
    await session.refresh(camera)
    return camera


@router.delete("/cameras/{camera_id}", status_code=204)
async def delete_camera(
    camera_id: str,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Delete a camera from the registry.

    Same "registry is durable" philosophy already applied to catalogue
    sources and watchlist entries: a camera with real ANPR history
    (sightings, alerts, or person-mode analytics_counts -- all NO ACTION
    FKs onto cameras.camera_id) can't be deleted, only a camera nobody has
    ever actually observed anything through. Health/maintenance history
    cascades away with it (operational log, not evidence); any recording
    that happened to reference it keeps existing with camera_id set to
    NULL rather than being destroyed. Reserved for cleaning up a
    mistakenly-created or duplicate registry row, not for retiring a
    camera that has been in real use -- deactivate analytics and leave
    the row in place for that instead.
    """
    require_super_admin(auth)
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id!r} not found")

    if any(cid == camera_id for cid, _mode in analytics._workers):
        raise HTTPException(
            status_code=409,
            detail="This camera has an analytics worker running -- disable analytics "
            "(PUT with analytics_enabled: false) before deleting it.",
        )

    department = camera.department
    await session.delete(camera)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This camera has sightings, alerts, or analytics history on record and "
            "cannot be deleted -- the registry keeps that history durable by design. "
            "There is nothing to deactivate on a camera row itself; if it should stop "
            "being monitored, disable its analytics instead.",
        ) from exc

    add_audit_event(
        session,
        actor=auth.user,
        action="camera.deleted",
        target_type="camera",
        target_id=camera_id,
        department=department,
        result="success",
    )
    await session.commit()


def _apply_operator_row(camera: Camera, row: dict) -> list[str]:
    errors = []
    update_kwargs = {}
    for col in _OPERATOR_CSV_COLUMNS[1:]:
        raw = row.get(col)
        if raw is None or raw == "":
            continue
        if col == "retention_days":
            try:
                update_kwargs[col] = int(raw)
            except ValueError:
                errors.append(f"retention_days must be an integer, got {raw!r}")
                continue
        elif col in ("latitude", "longitude"):
            try:
                update_kwargs[col] = float(raw)
            except ValueError:
                errors.append(f"{col} must be a number, got {raw!r}")
                continue
        elif col == "anpr_viable":
            lowered = raw.strip().lower()
            if lowered in ("true", "yes", "1"):
                update_kwargs[col] = True
            elif lowered in ("false", "no", "0"):
                update_kwargs[col] = False
            else:
                errors.append(f"anpr_viable must be true/false, got {raw!r}")
                continue
        else:
            update_kwargs[col] = raw

    try:
        update = CameraOperatorUpdate(**update_kwargs)
    except Exception as exc:  # pydantic validation error
        errors.append(str(exc))
        return errors

    errors.extend(update.validate_choices())
    if errors:
        return errors

    _apply_operator_update(camera, update)
    return []


@router.post("/cameras/bulk", response_model=BulkImportResult)
async def bulk_import(
    file: UploadFile,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    require_super_admin(auth)
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))

    if reader.fieldnames is None or "camera_id" not in reader.fieldnames:
        raise HTTPException(status_code=422, detail="CSV must have a camera_id column")

    valid_departments = set((await session.execute(select(Department.name))).scalars().all())

    row_results: list[BulkImportRowResult] = []
    created = 0
    updated = 0
    failed = 0
    total = 0

    for row in reader:
        total += 1
        camera_id = (row.get("camera_id") or "").strip()
        requested_department = (row.get("department") or "").strip()
        if requested_department and requested_department not in valid_departments:
            failed += 1
            row_results.append(
                BulkImportRowResult(
                    camera_id=camera_id,
                    status="error",
                    errors=["department must reference an existing department"],
                )
            )
            continue

        if not camera_id:
            name = (row.get("name") or "").strip()
            location_text = (row.get("location_text") or "").strip()
            creation_errors = []
            if not name:
                creation_errors.append("name is required when camera_id is blank")
            if not location_text:
                creation_errors.append("location_text is required when camera_id is blank")
            if creation_errors:
                failed += 1
                row_results.append(BulkImportRowResult(camera_id="", status="error", errors=creation_errors))
                continue

            camera = await _new_manual_camera(session, name=name, location_text=location_text)
            errors = _apply_operator_row(camera, row)
            if errors:
                failed += 1
                row_results.append(BulkImportRowResult(camera_id="", status="error", errors=errors))
                continue

            session.add(camera)
            created += 1
            row_results.append(BulkImportRowResult(camera_id=camera.camera_id, status="created"))
            continue

        camera = await session.get(Camera, camera_id)
        if camera is None:
            failed += 1
            row_results.append(
                BulkImportRowResult(
                    camera_id=camera_id,
                    status="error",
                    errors=["camera_id not found in registry; leave camera_id blank to create a manual camera"],
                )
            )
            continue

        errors = _apply_operator_row(camera, row)
        if errors:
            failed += 1
            row_results.append(BulkImportRowResult(camera_id=camera_id, status="error", errors=errors))
        else:
            updated += 1
            row_results.append(BulkImportRowResult(camera_id=camera_id, status="updated"))

    add_audit_event(
        session,
        actor=auth.user,
        action="camera.bulk_updated",
        target_type="camera_registry",
        result="success" if failed == 0 else "partial",
        details={"total_rows": total, "created": created, "updated": updated, "failed": failed},
    )
    await session.commit()

    return BulkImportResult(total_rows=total, created=created, updated=updated, failed=failed, results=row_results)
