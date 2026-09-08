import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import async_session, get_session
from app.models.auth import AuditEvent, User, UserDepartmentAccess, UserSession
from app.models.camera import Camera
from app.security import hash_password, normalise_email, token_digest

logger = logging.getLogger("sentinel.auth")

_CLEARANCE_RANK = {"viewer": 1, "operator": 2}


def _route_pattern(request: Request) -> str:
    """Return a stable route template without recording request values.

    Query strings can contain plates, names, or filters. Route parameters can
    too, so audit rows use FastAPI's matched template rather than the raw URL.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else request.url.path


async def audit_auth_denial(
    session: AsyncSession,
    request: Request,
    *,
    reason: str,
    status_code: int,
    actor: User | None = None,
) -> None:
    """Persist an authentication denial without retaining URL parameters."""
    add_audit_event(
        session,
        actor=actor,
        action="api.access_denied",
        target_type="api_route",
        target_id=_route_pattern(request),
        result="denied",
        details={"method": request.method, "reason": reason, "status_code": status_code},
    )
    await session.commit()


@dataclass(frozen=True)
class AuthContext:
    user: User
    grants: dict[str, str]

    @property
    def is_super_admin(self) -> bool:
        return self.user.role == "super_admin"

    @property
    def is_department_admin(self) -> bool:
        return self.user.role == "department_admin"

    def has_department(self, department: str | None, clearance: str = "viewer") -> bool:
        if self.is_super_admin:
            return True
        if department is None:
            return False
        actual = self.grants.get(department)
        return actual is not None and _CLEARANCE_RANK[actual] >= _CLEARANCE_RANK[clearance]


def require_super_admin(auth: AuthContext) -> None:
    if not auth.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super-admin access required")


def require_department_access(auth: AuthContext, department: str | None, clearance: str = "viewer") -> None:
    if not auth.has_department(department, clearance):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Department access denied")


def authorised_departments(auth: AuthContext, clearance: str = "viewer") -> set[str] | None:
    """None means unrestricted (super admin); otherwise the permitted set."""
    if auth.is_super_admin:
        return None
    minimum = _CLEARANCE_RANK[clearance]
    return {department for department, grant in auth.grants.items() if _CLEARANCE_RANK[grant] >= minimum}


async def get_authorised_camera(
    session: AsyncSession,
    auth: AuthContext,
    camera_id: str,
    clearance: str = "viewer",
) -> Camera:
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id!r} not found")
    require_department_access(auth, camera.department, clearance)
    return camera


async def get_current_auth(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    settings = get_settings()
    raw_token = request.cookies.get(settings.auth_cookie_name)
    if not raw_token:
        await audit_auth_denial(session, request, reason="missing_session", status_code=401)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    digest = token_digest(raw_token)
    row = (
        await session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == digest)
        )
    ).first()
    if row is None:
        await audit_auth_denial(session, request, reason="invalid_session", status_code=401)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid")

    user_session, user = row
    now = datetime.now(timezone.utc)
    if user_session.expires_at <= now:
        await session.delete(user_session)
        await audit_auth_denial(session, request, reason="expired_session", status_code=401, actor=user)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has expired")
    if user.status != "active":
        await audit_auth_denial(session, request, reason="account_disabled", status_code=403, actor=user)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    grant_rows = (
        await session.execute(
            select(UserDepartmentAccess.department, UserDepartmentAccess.clearance).where(
                UserDepartmentAccess.user_id == user.id
            )
        )
    ).all()
    auth = AuthContext(user=user, grants={department: clearance for department, clearance in grant_rows})
    request.state.auth_context = auth
    return auth


async def require_worker_token(
    x_sentinel_worker_token: str | None = Header(default=None),
) -> None:
    expected = get_settings().worker_api_token
    if not expected or not x_sentinel_worker_token or not hmac.compare_digest(expected, x_sentinel_worker_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid worker credentials required")


def add_audit_event(
    session: AsyncSession,
    *,
    action: str,
    target_type: str,
    result: str,
    actor: User | None = None,
    actor_email: str | None = None,
    target_id: str | int | None = None,
    department: str | None = None,
    details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else actor_email,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        department=department,
        result=result,
        details=details,
    )
    session.add(event)
    return event


async def ensure_seed_super_admin() -> None:
    """Idempotently seed the one demo super admin from environment values."""
    settings = get_settings()
    if not settings.super_admin_email or not settings.super_admin_password:
        logger.warning(
            "Super admin not seeded: set SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD outside Git before login"
        )
        return
    if len(settings.super_admin_password) < 10:
        logger.error("Super admin not seeded: SUPER_ADMIN_PASSWORD must contain at least 10 characters")
        return

    email = normalise_email(settings.super_admin_email)
    async with async_session() as session:
        existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is not None:
            return
        user = User(
            full_name=settings.super_admin_name.strip() or "Sentinel Super Admin",
            email=email,
            password_hash=hash_password(settings.super_admin_password),
            role="super_admin",
            home_department=None,
            status="active",
        )
        session.add(user)
        await session.flush()
        add_audit_event(
            session,
            actor=user,
            action="super_admin.seeded",
            target_type="user",
            target_id=user.id,
            result="success",
        )
        await session.commit()
        logger.info("Seeded demo super admin account for %s", email)


async def create_user_session(session: AsyncSession, user: User) -> tuple[str, datetime]:
    from app.security import new_session_token

    settings = get_settings()
    raw_token = new_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.auth_session_hours)
    await session.execute(delete(UserSession).where(UserSession.expires_at <= datetime.now(timezone.utc)))
    session.add(UserSession(token_hash=token_digest(raw_token), user_id=user.id, expires_at=expires_at))
    return raw_token, expires_at
