from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

USER_ROLES = ("super_admin", "department_admin", "department_user")
USER_STATUSES = ("active", "disabled")
CLEARANCES = ("viewer", "operator")
REQUEST_STATUSES = ("pending", "approved", "rejected")
REQUESTED_ROLES = ("department_admin", "department_user")


class Department(Base):
    __tablename__ = "departments"

    # The existing camera API already uses the department name as its stable
    # value. Keeping that contract avoids a disruptive ID migration while the
    # table makes the set dynamic and centrally managed.
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN {USER_ROLES}", name="ck_users_role"),
        CheckConstraint(f"status IN {USER_STATUSES}", name="ck_users_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    home_department: Mapped[str | None] = mapped_column(Text, ForeignKey("departments.name"), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserDepartmentAccess(Base):
    __tablename__ = "user_department_access"
    __table_args__ = (
        CheckConstraint(f"clearance IN {CLEARANCES}", name="ck_user_department_access_clearance"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    department: Mapped[str] = mapped_column(
        Text, ForeignKey("departments.name", ondelete="RESTRICT"), primary_key=True
    )
    clearance: Mapped[str] = mapped_column(Text, nullable=False)
    is_home: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    granted_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RegistrationRequest(Base):
    __tablename__ = "registration_requests"
    __table_args__ = (
        CheckConstraint(f"requested_role IN {REQUESTED_ROLES}", name="ck_registration_requests_role"),
        CheckConstraint(f"status IN {REQUEST_STATUSES}", name="ck_registration_requests_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    requested_department: Mapped[str] = mapped_column(Text, ForeignKey("departments.name"), nullable=False)
    requested_role: Mapped[str] = mapped_column(Text, nullable=False, server_default="department_user")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    reviewed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserSession(Base):
    __tablename__ = "user_sessions"

    # Only a SHA-256 digest is stored. The bearer token exists solely in the
    # HttpOnly browser cookie and cannot be recovered from the database.
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
