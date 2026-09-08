"""camera maintenance work orders and immutable lifecycle events

Revision ID: 202608311700
Revises: 202608311600
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op

revision = "202608311700"
down_revision = "202608311600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "camera_maintenance_work_orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("camera_id", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.camera_id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'cancelled')",
            name="ck_camera_maintenance_work_orders_status",
        ),
    )
    op.create_index(
        "ix_camera_maintenance_work_orders_camera_opened",
        "camera_maintenance_work_orders",
        ["camera_id", sa.text("opened_at DESC"), sa.text("id DESC")],
    )
    op.create_table(
        "camera_maintenance_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("work_order_id", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["work_order_id"], ["camera_maintenance_work_orders.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "event_type IN ('created', 'status_changed', 'note_added')",
            name="ck_camera_maintenance_events_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'cancelled')",
            name="ck_camera_maintenance_events_status",
        ),
    )
    op.create_index(
        "ix_camera_maintenance_events_work_order_occurred",
        "camera_maintenance_events",
        ["work_order_id", "occurred_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_camera_maintenance_events_work_order_occurred", table_name="camera_maintenance_events")
    op.drop_table("camera_maintenance_events")
    op.drop_index("ix_camera_maintenance_work_orders_camera_opened", table_name="camera_maintenance_work_orders")
    op.drop_table("camera_maintenance_work_orders")
