from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.recording import INGEST_KINDS


class Subject(Base):
    """A person or vehicle of interest, created only by operator action or an
    exact plate match -- never written automatically from a similarity
    score. See `Track.subject_id`."""

    __tablename__ = "subjects"
    __table_args__ = (CheckConstraint(f"kind IN {INGEST_KINDS}", name="ck_subjects_kind"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    plate: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
