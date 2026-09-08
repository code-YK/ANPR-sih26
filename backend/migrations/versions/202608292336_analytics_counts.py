"""analytics_counts table (non-ANPR aggregate analytics, e.g. person mode)

Revision ID: 202608292336
Revises: 202608291959
Create Date: 2026-08-29

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "202608292336"
down_revision = "202608291959"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_counts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("camera_id", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unique_tracks", sa.Integer(), nullable=False),
        sa.Column("peak_concurrent", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.camera_id"], name="fk_analytics_counts_camera_id"),
    )
    op.create_index("ix_analytics_counts_camera_id_mode", "analytics_counts", ["camera_id", "mode"])


def downgrade() -> None:
    op.drop_index("ix_analytics_counts_camera_id_mode", table_name="analytics_counts")
    op.drop_table("analytics_counts")
