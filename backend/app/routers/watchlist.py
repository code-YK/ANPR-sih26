import csv
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import plate_format
from app.auth_service import AuthContext, add_audit_event, get_current_auth, require_super_admin
from app.db import get_session
from app.models.watchlist import WatchlistEntry
from app.schemas import (
    WatchlistBulkResult,
    WatchlistBulkRowResult,
    WatchlistEntryCreate,
    WatchlistEntryOut,
    WatchlistEntryUpdate,
)

router = APIRouter()


@router.get("/watchlist", response_model=list[WatchlistEntryOut])
async def list_watchlist(
    active: bool | None = None,
    plate: str | None = None,
    _auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(WatchlistEntry)
    if active is not None:
        stmt = stmt.where(WatchlistEntry.active == active)
    if plate is not None:
        stmt = stmt.where(WatchlistEntry.normalised_value == plate_format.normalise(plate))
    stmt = stmt.order_by(WatchlistEntry.created_at.desc())
    return (await session.execute(stmt)).scalars().all()


@router.post("/watchlist", response_model=WatchlistEntryOut, status_code=201)
async def create_watchlist_entry(
    payload: WatchlistEntryCreate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    require_super_admin(auth)
    errors = payload.validate_choices()
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    entry = WatchlistEntry(
        raw_value=payload.raw_value,
        normalised_value=plate_format.normalise(payload.raw_value),
        reason_code=payload.reason_code,
        severity=payload.severity,
        notes=payload.notes,
        source=payload.source,
        active=payload.active,
    )
    session.add(entry)
    await session.flush()
    add_audit_event(
        session,
        actor=auth.user,
        action="watchlist.created",
        target_type="watchlist_entry",
        target_id=entry.id,
        result="success",
    )
    await session.commit()
    await session.refresh(entry)
    return entry


@router.put("/watchlist/{entry_id}", response_model=WatchlistEntryOut)
async def update_watchlist_entry(
    entry_id: int,
    payload: WatchlistEntryUpdate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    require_super_admin(auth)
    errors = payload.validate_choices()
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    entry = await session.get(WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Watchlist entry {entry_id} not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)

    add_audit_event(
        session,
        actor=auth.user,
        action="watchlist.updated",
        target_type="watchlist_entry",
        target_id=entry.id,
        result="success",
        details={"fields": sorted(payload.model_fields_set)},
    )

    await session.commit()
    await session.refresh(entry)
    return entry


@router.delete("/watchlist/{entry_id}", status_code=204)
async def delete_watchlist_entry(
    entry_id: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    require_super_admin(auth)
    entry = await session.get(WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Watchlist entry {entry_id} not found")
    await session.delete(entry)
    try:
        await session.flush()
    except IntegrityError as exc:
        # An entry that has ever matched keeps its alerts (fk_alerts_
        # watchlist_entry_id is RESTRICT, deliberately -- an alert's history
        # must not silently disappear because someone deleted the watchlist
        # entry that triggered it). Surfaced as a clear, actionable 409
        # instead of an unhandled 500 from the raw FK violation.
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This entry has one or more alerts on record and cannot be deleted -- "
            "resolve or otherwise handle those alerts first, or deactivate the entry instead "
            "(PUT with active: false) to stop new matches without losing the history.",
        ) from exc
    add_audit_event(
        session,
        actor=auth.user,
        action="watchlist.deleted",
        target_type="watchlist_entry",
        target_id=entry_id,
        result="success",
    )
    await session.commit()


@router.post("/watchlist/bulk", response_model=WatchlistBulkResult)
async def bulk_import_watchlist(
    file: UploadFile,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """CSV columns: raw_value (required), reason_code, severity, notes,
    source, active. Always inserts new rows -- unlike cameras/bulk, there is
    no natural existing-row key to update against."""
    require_super_admin(auth)
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))

    if reader.fieldnames is None or "raw_value" not in reader.fieldnames:
        raise HTTPException(status_code=422, detail="CSV must have a raw_value column")

    row_results: list[WatchlistBulkRowResult] = []
    added = 0
    failed = 0
    total = 0

    for row in reader:
        total += 1
        raw_value = (row.get("raw_value") or "").strip()
        if not raw_value:
            failed += 1
            row_results.append(WatchlistBulkRowResult(raw_value="", status="error", errors=["missing raw_value"]))
            continue

        kwargs = {"raw_value": raw_value}
        for col in ("reason_code", "notes", "source"):
            val = row.get(col)
            if val:
                kwargs[col] = val
        if row.get("severity"):
            kwargs["severity"] = row["severity"]
        if row.get("active") is not None and row.get("active") != "":
            kwargs["active"] = row["active"].strip().lower() in ("true", "yes", "1")

        try:
            payload = WatchlistEntryCreate(**kwargs)
        except Exception as exc:
            failed += 1
            row_results.append(WatchlistBulkRowResult(raw_value=raw_value, status="error", errors=[str(exc)]))
            continue

        errors = payload.validate_choices()
        if errors:
            failed += 1
            row_results.append(WatchlistBulkRowResult(raw_value=raw_value, status="error", errors=errors))
            continue

        entry = WatchlistEntry(
            raw_value=payload.raw_value,
            normalised_value=plate_format.normalise(payload.raw_value),
            reason_code=payload.reason_code,
            severity=payload.severity,
            notes=payload.notes,
            source=payload.source,
            active=payload.active,
        )
        session.add(entry)
        added += 1
        row_results.append(WatchlistBulkRowResult(raw_value=raw_value, status="added"))

    add_audit_event(
        session,
        actor=auth.user,
        action="watchlist.bulk_imported",
        target_type="watchlist",
        result="success" if failed == 0 else "partial",
        details={"total_rows": total, "added": added, "failed": failed},
    )
    await session.commit()
    return WatchlistBulkResult(total_rows=total, added=added, failed=failed, results=row_results)
