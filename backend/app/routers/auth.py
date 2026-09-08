import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_schemas import (
    AuditEventPage,
    AuthMe,
    DepartmentCreate,
    DepartmentOut,
    GrantOut,
    GrantUpdate,
    LoginRequest,
    RegistrationApproval,
    RegistrationCreate,
    RegistrationOut,
    RegistrationRejection,
    RegistrationSubmitted,
    UserOut,
    UserStatusUpdate,
)
from app.auth_service import (
    AuthContext,
    add_audit_event,
    create_user_session,
    get_current_auth,
    require_super_admin,
)
from app.config import get_settings
from app.db import get_session
from app.models.auth import (
    AuditEvent,
    Department,
    RegistrationRequest,
    User,
    UserDepartmentAccess,
    UserSession,
)
from app.security import hash_password, normalise_email, token_digest, verify_password

router = APIRouter()


def _audit_archive_line(event: AuditEvent) -> str:
    """Create a canonical NDJSON record suitable for an external snapshot."""
    occurred_at = event.occurred_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "action": event.action,
        "actor_email": event.actor_email,
        "actor_user_id": event.actor_user_id,
        "department": event.department,
        "details": event.details,
        "id": event.id,
        "occurred_at": occurred_at,
        "result": event.result,
        "target_id": event.target_id,
        "target_type": event.target_type,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _write_external_audit_archive(content: str, digest: str) -> str:
    """Write one snapshot to an administrator-provided external retention mount.

    The target is intentionally configured outside version control and outside
    the application's database.  Exclusive creation prevents this process from
    overwriting a prior archive; WORM/object-lock enforcement remains a
    property of the configured destination, not of ordinary filesystem modes.
    """
    configured_dir = get_settings().audit_archive_dir
    if not configured_dir:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External audit archive destination is not configured",
        )

    archive_dir = Path(configured_dir).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[3]
    try:
        archive_dir.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External audit archive destination must be outside the repository",
        )
    if not archive_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External audit archive destination is unavailable",
        )

    created_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_name = f"sentinel-audit-events-{created_at}-{digest[:12]}.ndjson"
    archive_path = archive_dir / archive_name
    checksum_path = archive_dir / f"{archive_name}.sha256"
    try:
        with archive_path.open("x", encoding="utf-8", newline="\n") as archive_file:
            archive_file.write(content)
            archive_file.flush()
            os.fsync(archive_file.fileno())
        with checksum_path.open("x", encoding="ascii", newline="\n") as checksum_file:
            checksum_file.write(f"{digest}  {archive_name}\n")
            checksum_file.flush()
            os.fsync(checksum_file.fileno())
    except FileExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An audit archive with this immutable name already exists",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External audit archive delivery failed",
        ) from exc

    return archive_name


async def _grants_for(session: AsyncSession, user_ids: list[int]) -> dict[int, list[UserDepartmentAccess]]:
    if not user_ids:
        return {}
    rows = (
        await session.execute(
            select(UserDepartmentAccess)
            .where(UserDepartmentAccess.user_id.in_(user_ids))
            .order_by(UserDepartmentAccess.is_home.desc(), UserDepartmentAccess.department)
        )
    ).scalars().all()
    out: dict[int, list[UserDepartmentAccess]] = {user_id: [] for user_id in user_ids}
    for row in rows:
        out[row.user_id].append(row)
    return out


def _user_out(user: User, grants: list[UserDepartmentAccess]) -> UserOut:
    return UserOut(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        home_department=user.home_department,
        status=user.status,
        grants=[
            GrantOut(
                department=grant.department,
                clearance=grant.clearance,
                is_home=grant.is_home,
                granted_at=grant.granted_at,
            )
            for grant in grants
        ],
        created_at=user.created_at,
    )


@router.post("/auth/login", response_model=AuthMe)
async def login(payload: LoginRequest, response: Response, session: AsyncSession = Depends(get_session)):
    email = normalise_email(payload.email)
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        add_audit_event(
            session,
            actor_email=email,
            action="auth.login",
            target_type="session",
            result="failure",
            details={"reason": "invalid_credentials"},
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if user.status != "active":
        add_audit_event(
            session,
            actor=user,
            action="auth.login",
            target_type="session",
            result="failure",
            details={"reason": "account_disabled"},
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    raw_token, _expires_at = await create_user_session(session, user)
    add_audit_event(session, actor=user, action="auth.login", target_type="session", result="success")
    await session.commit()

    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=raw_token,
        max_age=settings.auth_session_hours * 3600,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    grants = (await _grants_for(session, [user.id]))[user.id]
    return _user_out(user, grants)


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    raw_token = request.cookies.get(settings.auth_cookie_name)
    if raw_token:
        stored = await session.get(UserSession, token_digest(raw_token))
        if stored is not None:
            await session.delete(stored)
    add_audit_event(session, actor=auth.user, action="auth.logout", target_type="session", result="success")
    await session.commit()
    response.delete_cookie(settings.auth_cookie_name, path="/", samesite="lax")


@router.get("/auth/me", response_model=AuthMe)
async def me(auth: AuthContext = Depends(get_current_auth), session: AsyncSession = Depends(get_session)):
    grants = (await _grants_for(session, [auth.user.id]))[auth.user.id]
    return _user_out(auth.user, grants)


@router.get("/auth/registration-options", response_model=list[DepartmentOut])
async def public_registration_options(session: AsyncSession = Depends(get_session)):
    return (
        await session.execute(select(Department).where(Department.active.is_(True)).order_by(Department.name))
    ).scalars().all()


@router.post("/registration-requests", response_model=RegistrationSubmitted, status_code=201)
async def submit_registration(payload: RegistrationCreate, session: AsyncSession = Depends(get_session)):
    department = await session.get(Department, payload.requested_department)
    if department is None or not department.active:
        raise HTTPException(status_code=422, detail="Requested department is not available")
    email = normalise_email(payload.email)
    existing_user = (await session.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(status_code=409, detail="An account or request already exists for this email")
    pending = (
        await session.execute(
            select(RegistrationRequest.id).where(
                func.lower(RegistrationRequest.email) == email,
                RegistrationRequest.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if pending is not None:
        raise HTTPException(status_code=409, detail="An account or request already exists for this email")

    request_row = RegistrationRequest(
        full_name=payload.full_name,
        email=email,
        password_hash=hash_password(payload.password),
        requested_department=department.name,
        requested_role=payload.requested_role,
        status="pending",
    )
    session.add(request_row)
    await session.flush()
    add_audit_event(
        session,
        actor_email=email,
        action="registration.submitted",
        target_type="registration_request",
        target_id=request_row.id,
        department=department.name,
        result="success",
        details={"requested_role": payload.requested_role},
    )
    await session.commit()
    return RegistrationSubmitted(request_id=request_row.id, status="pending")


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(
    auth: AuthContext = Depends(get_current_auth), session: AsyncSession = Depends(get_session)
):
    stmt = select(Department).where(Department.active.is_(True))
    if not auth.is_super_admin:
        stmt = stmt.where(Department.name.in_(auth.grants.keys()))
    return (await session.execute(stmt.order_by(Department.name))).scalars().all()


@router.post("/admin/departments", response_model=DepartmentOut, status_code=201)
async def create_department(
    payload: DepartmentCreate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    require_super_admin(auth)
    existing = (
        await session.execute(select(Department).where(func.lower(Department.name) == payload.name.lower()))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Department already exists")
    department = Department(name=payload.name, active=True, created_by=auth.user.id)
    session.add(department)
    add_audit_event(
        session,
        actor=auth.user,
        action="department.created",
        target_type="department",
        target_id=payload.name,
        department=payload.name,
        result="success",
    )
    await session.commit()
    await session.refresh(department)
    return department


def _can_review(auth: AuthContext, request_row: RegistrationRequest) -> bool:
    if auth.is_super_admin:
        return True
    return (
        auth.is_department_admin
        and request_row.requested_role == "department_user"
        and auth.user.home_department == request_row.requested_department
    )


@router.get("/admin/registration-requests", response_model=list[RegistrationOut])
async def list_registration_requests(
    request_status: Literal["pending", "approved", "rejected"] = "pending",
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    if not (auth.is_super_admin or auth.is_department_admin):
        raise HTTPException(status_code=403, detail="Administrative access required")
    stmt = select(RegistrationRequest).where(RegistrationRequest.status == request_status)
    if auth.is_department_admin:
        stmt = stmt.where(
            RegistrationRequest.requested_department == auth.user.home_department,
            RegistrationRequest.requested_role == "department_user",
        )
    return (await session.execute(stmt.order_by(RegistrationRequest.created_at))).scalars().all()


@router.post("/admin/registration-requests/{request_id}/approve", response_model=UserOut)
async def approve_registration(
    request_id: int,
    payload: RegistrationApproval,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    request_row = await session.get(RegistrationRequest, request_id, with_for_update=True)
    if request_row is None:
        raise HTTPException(status_code=404, detail="Registration request not found")
    if not _can_review(auth, request_row):
        raise HTTPException(status_code=403, detail="Registration request is outside your authority")
    if request_row.status != "pending":
        raise HTTPException(status_code=409, detail="Registration request has already been reviewed")
    if (await session.execute(select(User.id).where(User.email == request_row.email))).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="A user with this email already exists")

    role = request_row.requested_role
    clearance = "operator" if role == "department_admin" else payload.clearance
    user = User(
        full_name=request_row.full_name,
        email=request_row.email,
        password_hash=request_row.password_hash,
        role=role,
        home_department=request_row.requested_department,
        status="active",
    )
    session.add(user)
    await session.flush()
    grant = UserDepartmentAccess(
        user_id=user.id,
        department=request_row.requested_department,
        clearance=clearance,
        is_home=True,
        granted_by=auth.user.id,
    )
    session.add(grant)
    request_row.status = "approved"
    request_row.password_hash = ""
    request_row.reviewed_by = auth.user.id
    request_row.reviewed_at = datetime.now(timezone.utc)
    add_audit_event(
        session,
        actor=auth.user,
        action="registration.approved",
        target_type="user",
        target_id=user.id,
        department=user.home_department,
        result="success",
        details={"role": role, "clearance": clearance, "request_id": request_id},
    )
    await session.commit()
    await session.refresh(user)
    await session.refresh(grant)
    return _user_out(user, [grant])


@router.post("/admin/registration-requests/{request_id}/reject", response_model=RegistrationOut)
async def reject_registration(
    request_id: int,
    payload: RegistrationRejection,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    request_row = await session.get(RegistrationRequest, request_id, with_for_update=True)
    if request_row is None:
        raise HTTPException(status_code=404, detail="Registration request not found")
    if not _can_review(auth, request_row):
        raise HTTPException(status_code=403, detail="Registration request is outside your authority")
    if request_row.status != "pending":
        raise HTTPException(status_code=409, detail="Registration request has already been reviewed")
    request_row.status = "rejected"
    request_row.password_hash = ""
    request_row.reviewed_by = auth.user.id
    request_row.reviewed_at = datetime.now(timezone.utc)
    request_row.rejection_reason = payload.reason.strip()
    add_audit_event(
        session,
        actor=auth.user,
        action="registration.rejected",
        target_type="registration_request",
        target_id=request_id,
        department=request_row.requested_department,
        result="success",
        details={"requested_role": request_row.requested_role},
    )
    await session.commit()
    await session.refresh(request_row)
    return request_row


@router.get("/admin/users", response_model=list[UserOut])
async def list_users(auth: AuthContext = Depends(get_current_auth), session: AsyncSession = Depends(get_session)):
    if not (auth.is_super_admin or auth.is_department_admin):
        raise HTTPException(status_code=403, detail="Administrative access required")
    stmt = select(User)
    if auth.is_department_admin:
        stmt = stmt.where(User.home_department == auth.user.home_department, User.role == "department_user")
    users = (await session.execute(stmt.order_by(User.created_at))).scalars().all()
    grants = await _grants_for(session, [user.id for user in users])
    return [_user_out(user, grants[user.id]) for user in users]


async def _manageable_user(session: AsyncSession, auth: AuthContext, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if auth.is_super_admin:
        return user
    if not (
        auth.is_department_admin
        and user.role == "department_user"
        and user.home_department == auth.user.home_department
    ):
        raise HTTPException(status_code=403, detail="User is outside your authority")
    return user


@router.put("/admin/users/{user_id}/status", response_model=UserOut)
async def update_user_status(
    user_id: int,
    payload: UserStatusUpdate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    user = await _manageable_user(session, auth, user_id)
    if user.id == auth.user.id and payload.status == "disabled":
        raise HTTPException(status_code=409, detail="You cannot disable your own account")
    user.status = payload.status
    if payload.status == "disabled":
        await session.execute(delete(UserSession).where(UserSession.user_id == user.id))
    add_audit_event(
        session,
        actor=auth.user,
        action="user.status_changed",
        target_type="user",
        target_id=user.id,
        department=user.home_department,
        result="success",
        details={"status": payload.status},
    )
    await session.commit()
    await session.refresh(user)
    grants = (await _grants_for(session, [user.id]))[user.id]
    return _user_out(user, grants)


@router.put("/admin/users/{user_id}/grants/{department}", response_model=UserOut)
async def upsert_department_grant(
    user_id: int,
    department: str,
    payload: GrantUpdate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    user = await _manageable_user(session, auth, user_id)
    department_row = await session.get(Department, department)
    if department_row is None or not department_row.active:
        raise HTTPException(status_code=404, detail="Department not found")
    if auth.is_department_admin and department != auth.user.home_department:
        raise HTTPException(status_code=403, detail="Cross-department grants require super-admin access")

    grant = await session.get(UserDepartmentAccess, (user.id, department))
    if grant is None:
        require_super_admin(auth)
        grant = UserDepartmentAccess(
            user_id=user.id,
            department=department,
            clearance=payload.clearance,
            is_home=(department == user.home_department),
            granted_by=auth.user.id,
        )
        session.add(grant)
        action = "department_access.granted"
    else:
        grant.clearance = payload.clearance
        grant.granted_by = auth.user.id
        action = "department_access.clearance_changed"
    add_audit_event(
        session,
        actor=auth.user,
        action=action,
        target_type="user_department_access",
        target_id=f"{user.id}:{department}",
        department=department,
        result="success",
        details={"clearance": payload.clearance},
    )
    await session.commit()
    grants = (await _grants_for(session, [user.id]))[user.id]
    return _user_out(user, grants)


@router.delete("/admin/users/{user_id}/grants/{department}", status_code=204)
async def revoke_department_grant(
    user_id: int,
    department: str,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    require_super_admin(auth)
    user = await _manageable_user(session, auth, user_id)
    grant = await session.get(UserDepartmentAccess, (user.id, department))
    if grant is None:
        raise HTTPException(status_code=404, detail="Department grant not found")
    if grant.is_home:
        raise HTTPException(status_code=409, detail="The automatic home-department grant cannot be revoked")
    await session.delete(grant)
    add_audit_event(
        session,
        actor=auth.user,
        action="department_access.revoked",
        target_type="user_department_access",
        target_id=f"{user.id}:{department}",
        department=department,
        result="success",
    )
    await session.commit()


@router.get("/admin/audit-events", response_model=AuditEventPage)
async def list_audit_events(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Audit history, newest first, paginated.

    A department admin sees events for their own department *or* events they
    performed themselves. The self clause matters because some actions carry
    no department at all -- `auth.login` most importantly -- so a
    department-scoped filter alone hid an admin's own sign-in history from
    them entirely, including their own failed attempts. `GOV-NFR-003` wants
    access history auditable by the people accountable for it; being unable
    to see your own logins works against that. It is not a widening of scope:
    every extra row is one the caller themselves generated.
    """
    if not (auth.is_super_admin or auth.is_department_admin):
        raise HTTPException(status_code=403, detail="Administrative access required")

    scope = None
    if auth.is_department_admin:
        scope = or_(
            AuditEvent.department == auth.user.home_department,
            AuditEvent.actor_user_id == auth.user.id,
        )

    count_stmt = select(func.count()).select_from(AuditEvent)
    stmt = select(AuditEvent)
    if scope is not None:
        count_stmt = count_stmt.where(scope)
        stmt = stmt.where(scope)

    total = (await session.execute(count_stmt)).scalar_one()
    events = (
        await session.execute(
            stmt.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return AuditEventPage(total=total, limit=limit, offset=offset, events=events)


@router.get("/admin/audit-events/export")
async def export_audit_events(
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Download a canonical, digest-verifiable snapshot for external retention.

    Only a super admin may export the complete cross-department audit history.
    The caller must place both the archive and its SHA-256 digest in the
    team's approved immutable retention destination; this endpoint does not
    claim that a browser download alone is immutable storage.
    """
    require_super_admin(auth)
    events = (
        await session.execute(select(AuditEvent).order_by(AuditEvent.occurred_at.asc(), AuditEvent.id.asc()))
    ).scalars().all()
    content = "".join(f"{_audit_archive_line(event)}\n" for event in events)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # The export action is intentionally committed after its archive is
    # materialised, so the reported count and digest identify exactly the
    # downloadable snapshot rather than a moving target that includes itself.
    add_audit_event(
        session,
        actor=auth.user,
        action="audit.exported",
        target_type="audit_events",
        result="success",
        details={"event_count": len(events), "format": "ndjson", "sha256": digest},
    )
    await session.commit()

    date = datetime.now(timezone.utc).date().isoformat()
    return Response(
        content=content,
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="sentinel-audit-events-{date}.ndjson"',
            "X-Content-Type-Options": "nosniff",
            "X-Sentinel-Audit-Event-Count": str(len(events)),
            "X-Sentinel-Audit-SHA256": digest,
        },
    )


@router.post("/admin/audit-events/archive", status_code=status.HTTP_201_CREATED)
async def archive_audit_events_externally(
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Deliver a canonical snapshot to the configured external retention mount.

    This operation is separate from the download endpoint so a browser download
    never silently writes server-side data.  It is deliberately super-admin
    only, produces no response containing audit rows, and records delivery only
    after both the NDJSON and detached digest have been exclusively created.
    """
    require_super_admin(auth)
    events = (
        await session.execute(select(AuditEvent).order_by(AuditEvent.occurred_at.asc(), AuditEvent.id.asc()))
    ).scalars().all()
    content = "".join(f"{_audit_archive_line(event)}\n" for event in events)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    archive_name = _write_external_audit_archive(content, digest)

    add_audit_event(
        session,
        actor=auth.user,
        action="audit.archive_delivered",
        target_type="audit_events",
        result="success",
        details={
            "archive_name": archive_name,
            "event_count": len(events),
            "format": "ndjson",
            "sha256": digest,
        },
    )
    await session.commit()
    return {
        "archive_name": archive_name,
        "event_count": len(events),
        "sha256": digest,
    }
