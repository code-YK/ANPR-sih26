"""Indexes supporting traffic-flow analytics reads

Revision ID: 202609101000
Revises: 202608312000
Create Date: 2026-09-10

Traffic analytics introduces two read shapes the existing indexes do not
serve. Neither adds a column; this migration is purely about not table
scanning `sightings` once it holds real volume.

1. Per-plate ordered leg scans (corridor speed, origin/destination pairs,
   dwell) walk every sighting for a plate in time order.
   `ix_sightings_plate` covers the equality on plate but leaves the sort,
   so the planner sorts the whole matching set.
2. Cross-camera time bucketing (density series) filters on `seen_at` alone.
   `ix_sightings_camera_id_seen_at` is unusable for that -- camera_id is
   the leading column and the query does not constrain it.

`analytics_counts` gains window_start as a trailing column so the vehicle
count series can be range-scanned per camera rather than filtered after
loading every window ever recorded for that camera.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "202609101000"
down_revision = "202608312000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_sightings_plate_seen_at", "sightings", ["plate", "seen_at"])
    op.create_index("ix_sightings_seen_at", "sightings", ["seen_at"])
    op.create_index(
        "ix_analytics_counts_camera_mode_window",
        "analytics_counts",
        ["camera_id", "mode", "window_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_counts_camera_mode_window", table_name="analytics_counts")
    op.drop_index("ix_sightings_seen_at", table_name="sightings")
    op.drop_index("ix_sightings_plate_seen_at", table_name="sightings")
