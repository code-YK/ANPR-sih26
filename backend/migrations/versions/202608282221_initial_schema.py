"""initial schema: cameras + sightings

Revision ID: 202608282221
Revises:
Create Date: 2026-08-28

"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

# revision identifiers, used by Alembic.
revision = "202608282221"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "cameras",
        sa.Column("camera_id", sa.Text(), nullable=False),
        sa.Column("camera_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("location_text", sa.Text(), nullable=False),
        sa.Column("rtsp_url", sa.Text(), nullable=False),
        sa.Column("hls_url", sa.Text(), nullable=False),
        sa.Column("webrtc_url", sa.Text(), nullable=False),
        sa.Column("codec", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Numeric(), nullable=True),
        sa.Column("bitrate_kbps", sa.Integer(), nullable=True),
        sa.Column("transport_ok", sa.Text(), nullable=True),
        sa.Column("anpr_viable", sa.Boolean(), nullable=True),
        sa.Column("anpr_notes", sa.Text(), nullable=True),
        sa.Column("last_surveyed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("geocode_confidence", sa.Text(), nullable=True),
        sa.Column("geog", Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True),
        sa.Column("department", sa.Text(), nullable=True),
        sa.Column("ownership", sa.Text(), nullable=True),
        sa.Column("camera_type", sa.Text(), nullable=True),
        sa.Column("connectivity", sa.Text(), nullable=True),
        sa.Column("storage_location", sa.Text(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("metadata_confidence", sa.Text(), nullable=True),
        sa.Column("is_live", sa.Boolean(), nullable=True),
        sa.Column("last_successful_connect", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("camera_id"),
        sa.CheckConstraint(
            "department IS NULL OR department IN ('Health', 'Police', 'GSRTC', 'Panchayat', 'Municipal')",
            name="ck_cameras_department",
        ),
        sa.CheckConstraint(
            "ownership IS NULL OR ownership IN ('government', 'private')",
            name="ck_cameras_ownership",
        ),
        sa.CheckConstraint(
            "camera_type IS NULL OR camera_type IN ('fixed', 'ptz', 'analog', 'ip')",
            name="ck_cameras_camera_type",
        ),
        sa.CheckConstraint(
            "transport_ok IS NULL OR transport_ok IN ('rtsp', 'hls', 'none')",
            name="ck_cameras_transport_ok",
        ),
        sa.CheckConstraint(
            "geocode_confidence IS NULL OR geocode_confidence IN ('exact', 'approximate', 'failed')",
            name="ck_cameras_geocode_confidence",
        ),
        sa.CheckConstraint(
            "metadata_confidence IS NULL OR metadata_confidence IN ('confirmed', 'inferred')",
            name="ck_cameras_metadata_confidence",
        ),
    )
    op.create_index("ix_cameras_department", "cameras", ["department"])
    op.create_index("ix_cameras_anpr_viable", "cameras", ["anpr_viable"])
    op.create_index("ix_cameras_geog", "cameras", ["geog"], postgresql_using="gist")

    op.create_table(
        "sightings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("camera_id", sa.Text(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plate", sa.Text(), nullable=True),
        sa.Column("vehicle_type", sa.Text(), nullable=True),
        sa.Column("vehicle_colour", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column("frame_pts_ms", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.camera_id"], name="fk_sightings_camera_id"),
    )
    op.create_index("ix_sightings_plate", "sightings", ["plate"])
    op.create_index("ix_sightings_camera_id_seen_at", "sightings", ["camera_id", "seen_at"])


def downgrade() -> None:
    op.drop_index("ix_sightings_camera_id_seen_at", table_name="sightings")
    op.drop_index("ix_sightings_plate", table_name="sightings")
    op.drop_table("sightings")

    op.drop_index("ix_cameras_geog", table_name="cameras")
    op.drop_index("ix_cameras_anpr_viable", table_name="cameras")
    op.drop_index("ix_cameras_department", table_name="cameras")
    op.drop_table("cameras")
