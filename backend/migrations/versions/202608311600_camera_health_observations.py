"""append-only camera probe health observations

Revision ID: 202608311600
Revises: 202608311200
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op

revision = "202608311600"
down_revision = "202608311200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("health_reason", sa.Text(), nullable=True))
    op.create_table(
        "camera_health_observations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("camera_id", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), server_default="probe", nullable=False),
        sa.Column("transport_ok", sa.Text(), nullable=False),
        sa.Column("is_live", sa.Boolean(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.camera_id"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('healthy', 'offline')", name="ck_camera_health_observations_status"),
        sa.CheckConstraint("transport_ok IN ('rtsp', 'hls', 'none')", name="ck_camera_health_observations_transport_ok"),
    )
    op.create_index(
        "ix_camera_health_observations_camera_observed",
        "camera_health_observations",
        ["camera_id", sa.text("observed_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_camera_health_observations_camera_observed", table_name="camera_health_observations")
    op.drop_table("camera_health_observations")
    op.drop_column("cameras", "health_reason")
