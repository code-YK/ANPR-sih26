from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RECORDING_STATUSES = ("uploading", "normalising", "ready", "rejected")

INGEST_KINDS = ("vehicle", "person")
INGEST_RUN_STATUSES = (
    "queued", "running", "completed", "completed_partial", "failed", "stalled", "cancelled",
)


class Recording(Base):
    """An uploaded video file for offline investigation.

    Deliberately separate from `IngestRun`: a recording is uploaded once, but
    may be re-processed several times with different parameters (model,
    imgsz, kind) -- each of those is a new run against the same file, not a
    mutation of the recording row.
    """

    __tablename__ = "recordings"
    __table_args__ = (
        CheckConstraint(f"status IN {RECORDING_STATUSES}", name="ck_recordings_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    # Content-addressed: the stored file lives at <recordings_dir>/<sha256>/original.mp4
    # and <recordings_dir>/<sha256>/normalised.mp4. Uniqueness on the hash is
    # what makes a duplicate upload return the existing row instead of
    # silently re-ingesting the same bytes under a second id.
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    normalised_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Taken from the NORMALISED file, never the upload -- see the ingest
    # worker docstring for why frame_index/fps on an un-normalised file is
    # unreliable (VFR, rotation, non-zero start PTS).
    duration_seconds: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    fps_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps_den: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    department: Mapped[str] = mapped_column(Text, ForeignKey("departments.name", ondelete="RESTRICT"), nullable=False)
    camera_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("cameras.camera_id", ondelete="SET NULL"), nullable=True
    )
    location_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Operator-supplied wall-clock start of the recording. Nullable, and left
    # null rather than guessed -- the same honesty observation_worker.py
    # applies to seen_at: an unanchored time is reported as absent, not
    # invented.
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="uploading")
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    uploaded_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IngestRun(Base):
    """One attempt to process a Recording for a given `kind`.

    State lives here in Postgres, not in the backend's in-memory `_workers`
    dict the live analytics workers use -- an ingest run can take tens of
    minutes, and it must survive a backend restart (see
    `kill_orphans_from_previous_run`, which this table's workers are
    deliberately NOT registered with).
    """

    __tablename__ = "ingest_runs"
    __table_args__ = (
        CheckConstraint(f"kind IN {INGEST_KINDS}", name="ck_ingest_runs_kind"),
        CheckConstraint(f"status IN {INGEST_RUN_STATUSES}", name="ck_ingest_runs_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recording_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    tracker_config: Mapped[str] = mapped_column(Text, nullable=False)
    imgsz: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_stride: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # The values ACTUALLY used after per-run derivation (e.g. track_buffer
    # scaled for stride/fps) -- not just the stride, so provenance survives
    # even if the derivation formula changes later.
    effective_tracker_settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    progress_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    frames_processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    frames_expected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    chunk_count_expected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count_received: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worker_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
