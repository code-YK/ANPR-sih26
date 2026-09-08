"""recordings, ingest runs, tracks, and subjects for offline investigation

Revision ID: 202608301800
Revises: 202608301200
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202608301800"
down_revision = "202608301200"
branch_labels = None
depends_on = None

_RECORDING_STATUSES = ("uploading", "normalising", "ready", "rejected")
_INGEST_KINDS = ("vehicle", "person")
_INGEST_RUN_STATUSES = (
    "queued", "running", "completed", "completed_partial", "failed", "stalled", "cancelled",
)
_LINK_METHODS = ("plate_exact", "operator_confirmed")


def upgrade() -> None:
    # Fuzzy plate search: 1-2 character OCR errors dominate real reads, and
    # exact matching alone would miss most of them. pg_trgm is the standard
    # extension for this; PostGIS is already installed the same way.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "recordings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("normalised_path", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Numeric(10, 3), nullable=True),
        sa.Column("fps_num", sa.Integer(), nullable=True),
        sa.Column("fps_den", sa.Integer(), nullable=True),
        sa.Column("frame_count", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("department", sa.Text(), nullable=False),
        sa.Column("camera_id", sa.Text(), nullable=True),
        sa.Column("location_text", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), server_default="uploading", nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_sha256", name="uq_recordings_content_sha256"),
        sa.ForeignKeyConstraint(["department"], ["departments.name"], name="fk_recordings_department", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.camera_id"], name="fk_recordings_camera_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], name="fk_recordings_uploaded_by", ondelete="SET NULL"),
        sa.CheckConstraint(f"status IN {_RECORDING_STATUSES}", name="ck_recordings_status"),
    )
    op.create_index("ix_recordings_department", "recordings", ["department"])
    op.create_index("ix_recordings_status", "recordings", ["status"])

    op.create_table(
        "ingest_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("recording_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("tracker_config", sa.Text(), nullable=False),
        sa.Column("imgsz", sa.Integer(), nullable=False),
        sa.Column("frame_stride", sa.Integer(), server_default="1", nullable=False),
        sa.Column("effective_tracker_settings", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("progress_pct", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("frames_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("frames_expected", sa.Integer(), nullable=True),
        sa.Column("track_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunk_count_expected", sa.Integer(), nullable=True),
        sa.Column("chunk_count_received", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("worker_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], name="fk_ingest_runs_recording_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_ingest_runs_created_by", ondelete="SET NULL"),
        sa.CheckConstraint(f"kind IN {_INGEST_KINDS}", name="ck_ingest_runs_kind"),
        sa.CheckConstraint(f"status IN {_INGEST_RUN_STATUSES}", name="ck_ingest_runs_status"),
    )
    op.create_index("ix_ingest_runs_recording_id", "ingest_runs", ["recording_id"])
    # The queue/reaper scan "which runs are queued or running" every
    # supervisor tick; a partial index keeps that cheap regardless of how
    # many completed runs accumulate.
    op.create_index(
        "ix_ingest_runs_active_status",
        "ingest_runs",
        ["status"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "subjects",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("plate", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_subjects_created_by", ondelete="SET NULL"),
        sa.CheckConstraint(f"kind IN {_INGEST_KINDS}", name="ck_subjects_kind"),
    )
    op.create_index("ix_subjects_plate", "subjects", ["plate"])

    op.create_table(
        "tracks",
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("track_ref", sa.Integer(), nullable=False),
        sa.Column("recording_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("occurrence_index", sa.Integer(), nullable=False),
        sa.Column("first_frame", sa.Integer(), nullable=False),
        sa.Column("last_frame", sa.Integer(), nullable=False),
        sa.Column("first_ms", sa.BigInteger(), nullable=False),
        sa.Column("last_ms", sa.BigInteger(), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=False),
        sa.Column("best_conf", sa.Numeric(5, 4), nullable=False),
        sa.Column("thumb_path", sa.Text(), nullable=True),
        sa.Column("boxes", postgresql.JSONB(), nullable=True),
        sa.Column("plate_confirmed", sa.Text(), nullable=True),
        sa.Column("plate_tentative", sa.Text(), nullable=True),
        sa.Column("plate_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("plate_votes", sa.Integer(), nullable=True),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("link_method", sa.Text(), nullable=True),
        sa.Column("link_score", sa.Numeric(6, 5), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "track_ref"),
        sa.ForeignKeyConstraint(["run_id"], ["ingest_runs.id"], name="fk_tracks_run_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], name="fk_tracks_recording_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], name="fk_tracks_subject_id", ondelete="SET NULL"),
        sa.CheckConstraint(f"kind IN {_INGEST_KINDS}", name="ck_tracks_kind"),
        sa.CheckConstraint(f"link_method IS NULL OR link_method IN {_LINK_METHODS}", name="ck_tracks_link_method"),
        sa.CheckConstraint(
            "plate_confirmed IS NULL OR plate_tentative IS NOT NULL",
            name="ck_tracks_plate_confirmed_needs_tentative",
        ),
    )
    op.create_index("ix_tracks_recording_id", "tracks", ["recording_id"])
    op.create_index("ix_tracks_subject_id", "tracks", ["subject_id"])
    op.create_index("ix_tracks_plate_confirmed", "tracks", ["plate_confirmed"])
    # Trigram GIN index for fuzzy plate search over both plate columns.
    op.execute(
        "CREATE INDEX ix_tracks_plate_confirmed_trgm ON tracks USING gin (plate_confirmed gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_tracks_plate_tentative_trgm ON tracks USING gin (plate_tentative gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tracks_plate_tentative_trgm")
    op.execute("DROP INDEX IF EXISTS ix_tracks_plate_confirmed_trgm")
    op.drop_index("ix_tracks_plate_confirmed", table_name="tracks")
    op.drop_index("ix_tracks_subject_id", table_name="tracks")
    op.drop_index("ix_tracks_recording_id", table_name="tracks")
    op.drop_table("tracks")

    op.drop_index("ix_subjects_plate", table_name="subjects")
    op.drop_table("subjects")

    op.drop_index("ix_ingest_runs_active_status", table_name="ingest_runs")
    op.drop_index("ix_ingest_runs_recording_id", table_name="ingest_runs")
    op.drop_table("ingest_runs")

    op.drop_index("ix_recordings_status", table_name="recordings")
    op.drop_index("ix_recordings_department", table_name="recordings")
    op.drop_table("recordings")

    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
