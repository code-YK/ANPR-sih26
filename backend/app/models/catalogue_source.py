from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Only the one catalogue shape this project has actually seen (see
# app/pipeline/catalogue_sources.py's adapter registry). Extend both this
# and the registry together when a genuinely different source schema shows
# up -- never accept an unvalidated adapter string.
ADAPTERS = ("sentinel_default",)


class CatalogueSource(Base):
    __tablename__ = "catalogue_sources"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="ck_catalogue_sources_name_not_blank"),
        # Not an f-string over the raw tuple: Python's repr of a one-element
        # tuple ("x",) has a trailing comma that is invalid inside a SQL
        # IN (...) list -- built explicitly so this stays correct however
        # many adapters ADAPTERS grows to.
        CheckConstraint(
            "adapter IN (" + ", ".join(f"'{a}'" for a in ADAPTERS) + ")", name="ck_catalogue_sources_adapter"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    adapter: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    browser_base_url: Mapped[str | None] = mapped_column(Text)
    auth_header_name: Mapped[str | None] = mapped_column(Text)
    # Never returned by any GET/list response -- see CatalogueSourceOut,
    # which omits this field entirely rather than masking it.
    auth_secret: Mapped[str | None] = mapped_column(Text)
    allow_private_host: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
