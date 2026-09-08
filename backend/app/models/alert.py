from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ALERT_STATUSES = ("open", "acknowledged", "resolved")
# What raised the alert. "watchlist" is the mandatory ANPR path: a confirmed
# plate matched an active watchlist entry, so both sighting_id and
# watchlist_entry_id are present. "suspicious" is the person-based
# suspicious-activity detector (best.pt "potentially_dangerous_person"): it
# has neither a plate sighting nor a watchlist entry, so it carries its own
# label/severity on the alert row instead of joining out for them.
ALERT_TYPES = ("watchlist", "suspicious")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(f"status IN {ALERT_STATUSES}", name="ck_alerts_status"),
        CheckConstraint(f"alert_type IN {ALERT_TYPES}", name="ck_alerts_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Nullable so a non-ANPR alert (a suspicious-person detection has no plate
    # sighting and no watchlist entry) can share this one table and the one
    # Alerts view, rather than forking a parallel alerts system. The watchlist
    # path still always sets both -- enforced by create_sighting, not by the
    # column nullability.
    sighting_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sightings.id"))
    watchlist_entry_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("watchlist_entries.id"))
    camera_id: Mapped[str] = mapped_column(Text, ForeignKey("cameras.camera_id"), nullable=False)

    alert_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="watchlist")
    # Only set for alerts that don't join out to a watchlist entry for these:
    # a human-readable summary (e.g. "Potentially dangerous person") and the
    # alert's own severity. A "watchlist" alert leaves both null and reads
    # them from the joined WatchlistEntry instead.
    label: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(Text)

    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    match_confidence: Mapped[float | None] = mapped_column(Numeric)
    dedup_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")

    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
