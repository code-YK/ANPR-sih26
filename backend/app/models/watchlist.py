from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ENTITY_TYPES = ("vehicle_plate",)  # only kind this build supports; kept as a
# real constraint (not free text) so a future entity type is a deliberate
# schema change, not a silent string that never matches anything.
SEVERITIES = ("low", "medium", "high")


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"
    __table_args__ = (
        # Only one entity_type exists today; a plain equality avoids the
        # single-element-tuple-repr SQL pitfall ("IN ('x',)" is invalid SQL).
        CheckConstraint("entity_type = 'vehicle_plate'", name="ck_watchlist_entity_type"),
        CheckConstraint(f"severity IN {SEVERITIES}", name="ck_watchlist_severity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="vehicle_plate")
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalised_value: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    reason_code: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default="medium")
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(nullable=False, server_default="true")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
