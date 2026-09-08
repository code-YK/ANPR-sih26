"""watchlist_entries, alerts, and sightings.epoch_id

Revision ID: 202608291959
Revises: 202608290104
Create Date: 2026-08-29

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "202608291959"
down_revision = "202608290104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sightings",
        sa.Column("epoch_id", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False, server_default="vehicle_plate"),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("normalised_value", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False, server_default="medium"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("entity_type = 'vehicle_plate'", name="ck_watchlist_entity_type"),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high')", name="ck_watchlist_severity"),
    )
    op.create_index("ix_watchlist_entries_normalised_value", "watchlist_entries", ["normalised_value"])
    op.create_index("ix_watchlist_entries_active", "watchlist_entries", ["active"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sighting_id", sa.BigInteger(), nullable=False),
        sa.Column("watchlist_entry_id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Text(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("match_confidence", sa.Numeric(), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["sighting_id"], ["sightings.id"], name="fk_alerts_sighting_id"),
        sa.ForeignKeyConstraint(["watchlist_entry_id"], ["watchlist_entries.id"], name="fk_alerts_watchlist_entry_id"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.camera_id"], name="fk_alerts_camera_id"),
        sa.CheckConstraint("status IN ('open', 'acknowledged', 'resolved')", name="ck_alerts_status"),
    )
    op.create_index("ix_alerts_dedup_key", "alerts", ["dedup_key"])
    op.create_index("ix_alerts_status", "alerts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_alerts_status", table_name="alerts")
    op.drop_index("ix_alerts_dedup_key", table_name="alerts")
    op.drop_table("alerts")

    op.drop_index("ix_watchlist_entries_active", table_name="watchlist_entries")
    op.drop_index("ix_watchlist_entries_normalised_value", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")

    op.drop_column("sightings", "epoch_id")
