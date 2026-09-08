from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db import Base
from app.models.recording import INGEST_KINDS

LINK_METHODS = ("plate_exact", "operator_confirmed")


class Track(Base):
    """One contiguous appearance of a vehicle or person within one ingest run.

    This is the evidence, not the claim: `subject_id` stays NULL until an
    exact plate match or an operator explicitly confirms a link (see
    `Subject`). A cosine-similarity search result is never written here on
    its own -- appearance similarity between two CCTV crops is evidence, not
    identification.

    Composite PK on (run_id, track_ref) rather than a surrogate id: a failed
    run's rows must never be confused with a retry's, and the tracker's own
    per-run track numbering restarts at 1 on every run (`reset_id()`), so
    track_ref alone is not unique across runs.
    """

    __tablename__ = "tracks"
    __table_args__ = (
        CheckConstraint(f"kind IN {INGEST_KINDS}", name="ck_tracks_kind"),
        CheckConstraint(
            f"link_method IS NULL OR link_method IN {LINK_METHODS}", name="ck_tracks_link_method"
        ),
        CheckConstraint(
            "plate_confirmed IS NULL OR plate_tentative IS NOT NULL", name="ck_tracks_plate_confirmed_needs_tentative"
        ),
    )

    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ingest_runs.id", ondelete="CASCADE"), primary_key=True)
    track_ref: Mapped[int] = mapped_column(Integer, primary_key=True)

    recording_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Tracks that lose and re-acquire within the merge-gap window share an
    # occurrence_index, so "distinct occurrences" is
    # COUNT(DISTINCT occurrence_index), not COUNT(*) -- a person standing
    # still is one occurrence even if the tracker briefly loses and re-finds
    # them.
    occurrence_index: Mapped[int] = mapped_column(Integer, nullable=False)

    first_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    last_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    first_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False)
    best_conf: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    thumb_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Fixed-rate timeline: {"t0_ms","dt_ms","w","h","b":[[cx,cy,bw,bh],...]}
    # (coords normalised 0..1000). `deferred()` is load-bearing: a bare
    # `select(Track)` for a results list must never drag every timeline
    # along with it. Served only via GET /investigate/tracks/{..}/boxes.
    boxes: Mapped[dict | None] = deferred(mapped_column(JSONB, nullable=True))

    # Vehicle only. Two columns, not one, because live and offline want
    # opposite things: `plate_confirmed` mirrors PlateReader.confirmed()
    # (zero-edit, >=2 votes -- precision, right for a live alert);
    # `plate_tentative` mirrors consensus() (recall, right for an
    # investigator who can judge a tentative read themselves). Collapsing
    # them would undo the care in plates.py.
    plate_confirmed: Mapped[str | None] = mapped_column(Text, nullable=True)
    plate_tentative: Mapped[str | None] = mapped_column(Text, nullable=True)
    plate_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    plate_votes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Phase 2.
    embedding: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, nullable=True))
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)

    subject_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    link_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_score: Mapped[float | None] = mapped_column(Numeric(6, 5), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
