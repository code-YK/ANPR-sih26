from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AnalyticsCount(Base):
    """Periodic aggregate from a non-ANPR analytics mode (person tracking so
    far). A person detection carries no identifier -- no face recognition,
    explicitly out of scope -- so it cannot match a watchlist, correlate
    across cameras, or appear in a journey. This table exists precisely so
    that data never gets forced into `sightings`, which is plate-keyed."""

    __tablename__ = "analytics_counts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    camera_id: Mapped[str] = mapped_column(Text, ForeignKey("cameras.camera_id"), nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unique_tracks: Mapped[int] = mapped_column(Integer, nullable=False)
    peak_concurrent: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
