from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AnalyticsCount(Base):
    """Periodic per-camera aggregate: how many distinct tracks were seen in a
    window and the peak seen at once. Written by both analytics modes.

    `mode="person"` is here because a person detection carries no identifier
    -- no face recognition, explicitly out of scope -- so it cannot match a
    watchlist, correlate across cameras, or appear in a journey. This table
    exists precisely so that data is never forced into `sightings`, which is
    plate-keyed.

    `mode="vehicle"` is here for a different reason: it is the denominator
    for `sightings`. A sighting is only written once a plate is CONFIRMED,
    so vehicles whose plate was never readable never appear there. Comparing
    the two gives a camera's measured plate-read yield instead of letting a
    plate-conditioned undercount be read as traffic volume."""

    __tablename__ = "analytics_counts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    camera_id: Mapped[str] = mapped_column(Text, ForeignKey("cameras.camera_id"), nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unique_tracks: Mapped[int] = mapped_column(Integer, nullable=False)
    peak_concurrent: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
