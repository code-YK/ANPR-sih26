"""department-aware authentication, RBAC grants, registration, and audit

Revision ID: 202608301200
Revises: 202608292344
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op

revision = "202608301200"
down_revision = "202608292344"
branch_labels = None
depends_on = None

_INITIAL_DEPARTMENTS = ("Health", "Police", "GSRTC", "Panchayat", "Municipal")


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("name"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_departments_name_not_blank"),
    )
    op.create_index("uq_departments_name_lower", "departments", [sa.text("lower(name)")], unique=True)
    for name in _INITIAL_DEPARTMENTS:
        op.execute(sa.text("INSERT INTO departments (name) VALUES (:name)").bindparams(name=name))

    # Preserve any non-standard department already present in a local registry
    # before replacing the old hardcoded enum constraint with a real FK.
    op.execute(
        """
        INSERT INTO departments (name)
        SELECT DISTINCT department FROM cameras
        WHERE department IS NOT NULL
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.drop_constraint("ck_cameras_department", "cameras", type_="check")
    op.create_foreign_key(
        "fk_cameras_department", "cameras", "departments", ["department"], ["name"], ondelete="RESTRICT"
    )

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("home_department", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["home_department"], ["departments.name"], name="fk_users_home_department"),
        sa.CheckConstraint(
            "role IN ('super_admin', 'department_admin', 'department_user')", name="ck_users_role"
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    op.create_index("ix_users_home_department", "users", ["home_department"])

    # Complete the circular provenance FK only after users exists.
    op.create_foreign_key(
        "fk_departments_created_by", "departments", "users", ["created_by"], ["id"], ondelete="SET NULL"
    )

    op.create_table(
        "user_department_access",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("department", sa.Text(), nullable=False),
        sa.Column("clearance", sa.Text(), nullable=False),
        sa.Column("is_home", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("granted_by", sa.BigInteger(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "department"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department"], ["departments.name"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("clearance IN ('viewer', 'operator')", name="ck_user_department_access_clearance"),
    )
    op.create_index("ix_user_department_access_department", "user_department_access", ["department"])

    op.create_table(
        "registration_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("requested_department", sa.Text(), nullable=False),
        sa.Column("requested_role", sa.Text(), server_default="department_user", nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["requested_department"], ["departments.name"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "requested_role IN ('department_admin', 'department_user')", name="ck_registration_requests_role"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="ck_registration_requests_status"
        ),
    )
    op.create_index(
        "uq_registration_requests_pending_email",
        "registration_requests",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_registration_requests_department_status", "registration_requests", ["requested_department", "status"])

    op.create_table(
        "user_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("token_hash"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_email", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("department", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_events_department_occurred_at", "audit_events", ["department", "occurred_at"])
    op.create_index("ix_audit_events_actor_occurred_at", "audit_events", ["actor_user_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_actor_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_department_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("ix_registration_requests_department_status", table_name="registration_requests")
    op.drop_index("uq_registration_requests_pending_email", table_name="registration_requests")
    op.drop_table("registration_requests")
    op.drop_index("ix_user_department_access_department", table_name="user_department_access")
    op.drop_table("user_department_access")
    op.drop_constraint("fk_departments_created_by", "departments", type_="foreignkey")
    op.drop_index("ix_users_home_department", table_name="users")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_constraint("fk_cameras_department", "cameras", type_="foreignkey")
    op.create_check_constraint(
        "ck_cameras_department",
        "cameras",
        "department IS NULL OR department IN ('Health', 'Police', 'GSRTC', 'Panchayat', 'Municipal')",
    )
    op.drop_index("uq_departments_name_lower", table_name="departments")
    op.drop_table("departments")
