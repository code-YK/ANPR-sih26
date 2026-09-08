"""Named, credentialed catalogue sources for multi-source camera onboarding.

Every route here is super-admin-only -- registering a source (its URL and
credential) and triggering a sync against it are both privileged actions,
same trust level as creating a department or approving an admin. See
app/pipeline/catalogue_sources.py for the adapter registry, SSRF hardening,
and the actual sync logic; this router is thin by design.
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import AuthContext, add_audit_event, get_current_auth, require_super_admin
from app.db import get_session
from app.models.catalogue_source import CatalogueSource
from app.pipeline.catalogue_sources import ADAPTERS, InvalidSourceUrl, run_source_sync, validate_base_url
from app.schemas import CatalogueSourceCreate, CatalogueSourceOut, CatalogueSourceUpdate, SyncResult

router = APIRouter()


def _validate_adapter(adapter: str) -> None:
    if adapter not in ADAPTERS:
        raise HTTPException(status_code=422, detail=f"adapter must be one of {sorted(ADAPTERS)}")


async def _get_source(session: AsyncSession, source_id: int) -> CatalogueSource:
    source = await session.get(CatalogueSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Catalogue source not found")
    return source


@router.post("/catalogue-sources", response_model=CatalogueSourceOut, status_code=201)
async def create_catalogue_source(
    payload: CatalogueSourceCreate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    require_super_admin(auth)
    _validate_adapter(payload.adapter)
    try:
        validate_base_url(payload.base_url, payload.allow_private_host)
    except InvalidSourceUrl as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing = (
        await session.execute(select(CatalogueSource).where(func.lower(CatalogueSource.name) == payload.name.lower()))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A catalogue source with this name already exists")

    source = CatalogueSource(
        name=payload.name,
        adapter=payload.adapter,
        base_url=payload.base_url,
        browser_base_url=payload.browser_base_url,
        auth_header_name=payload.auth_header_name,
        auth_secret=payload.auth_secret,
        allow_private_host=payload.allow_private_host,
        created_by=auth.user.id,
    )
    session.add(source)
    add_audit_event(
        session,
        actor=auth.user,
        action="catalogue_source.created",
        target_type="catalogue_source",
        target_id=payload.name,
        result="success",
        details={"adapter": payload.adapter, "has_credential": bool(payload.auth_secret)},
    )
    await session.commit()
    await session.refresh(source)
    return source


@router.get("/catalogue-sources", response_model=list[CatalogueSourceOut])
async def list_catalogue_sources(
    auth: AuthContext = Depends(get_current_auth), session: AsyncSession = Depends(get_session)
):
    require_super_admin(auth)
    return (await session.execute(select(CatalogueSource).order_by(CatalogueSource.name))).scalars().all()


@router.get("/catalogue-sources/{source_id}", response_model=CatalogueSourceOut)
async def get_catalogue_source(
    source_id: int, auth: AuthContext = Depends(get_current_auth), session: AsyncSession = Depends(get_session)
):
    require_super_admin(auth)
    return await _get_source(session, source_id)


@router.put("/catalogue-sources/{source_id}", response_model=CatalogueSourceOut)
async def update_catalogue_source(
    source_id: int,
    payload: CatalogueSourceUpdate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    require_super_admin(auth)
    source = await _get_source(session, source_id)
    fields = payload.model_dump(exclude_unset=True)

    if "adapter" in fields:
        _validate_adapter(fields["adapter"])
    if "base_url" in fields or "allow_private_host" in fields:
        validate_base_url(
            fields.get("base_url", source.base_url),
            fields.get("allow_private_host", source.allow_private_host),
        )
    if "name" in fields:
        clash = (
            await session.execute(
                select(CatalogueSource).where(
                    func.lower(CatalogueSource.name) == fields["name"].lower(), CatalogueSource.id != source_id
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(status_code=409, detail="A catalogue source with this name already exists")

    for field, value in fields.items():
        setattr(source, field, value)

    add_audit_event(
        session,
        actor=auth.user,
        action="catalogue_source.updated",
        target_type="catalogue_source",
        target_id=source.name,
        result="success",
        details={"fields": sorted(k for k in fields if k != "auth_secret")},
    )
    await session.commit()
    await session.refresh(source)
    return source


@router.delete("/catalogue-sources/{source_id}", status_code=204)
async def delete_catalogue_source(
    source_id: int, auth: AuthContext = Depends(get_current_auth), session: AsyncSession = Depends(get_session)
):
    require_super_admin(auth)
    source = await _get_source(session, source_id)
    name = source.name
    await session.delete(source)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Cameras still reference this source -- deactivate it instead of deleting, "
            "or remove those cameras first",
        ) from exc

    add_audit_event(
        session,
        actor=auth.user,
        action="catalogue_source.deleted",
        target_type="catalogue_source",
        target_id=name,
        result="success",
    )
    await session.commit()


@router.post("/catalogue-sources/{source_id}/sync", response_model=SyncResult)
async def sync_catalogue_source(
    source_id: int, auth: AuthContext = Depends(get_current_auth), session: AsyncSession = Depends(get_session)
):
    require_super_admin(auth)
    source = await _get_source(session, source_id)
    if not source.active:
        raise HTTPException(status_code=409, detail="Source is deactivated -- reactivate it before syncing")

    try:
        result = await run_source_sync(session, source)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Catalogue source unreachable: {exc}") from exc

    add_audit_event(
        session,
        actor=auth.user,
        action="catalogue_source.synced",
        target_type="catalogue_source",
        target_id=source.name,
        result="success",
        details=result.model_dump(),
    )
    await session.commit()
    return result
