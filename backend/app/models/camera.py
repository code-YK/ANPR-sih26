from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

OWNERSHIPS = ("government", "private")
CAMERA_TYPES = ("fixed", "ptz", "analog", "ip")
TRANSPORTS = ("rtsp", "hls", "none")
HEALTH_STATUSES = ("healthy", "offline")
MAINTENANCE_STATUSES = ("open", "in_progress", "resolved", "cancelled")
MAINTENANCE_EVENT_TYPES = ("created", "status_changed", "note_added")
GEOCODE_CONFIDENCES = ("exact", "approximate", "failed")
METADATA_CONFIDENCES = ("confirmed", "inferred")


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = (
        CheckConstraint(f"ownership IS NULL OR ownership IN {OWNERSHIPS}", name="ck_cameras_ownership"),
        CheckConstraint(f"camera_type IS NULL OR camera_type IN {CAMERA_TYPES}", name="ck_cameras_camera_type"),
        CheckConstraint(f"transport_ok IS NULL OR transport_ok IN {TRANSPORTS}", name="ck_cameras_transport_ok"),
        CheckConstraint(
            f"geocode_confidence IS NULL OR geocode_confidence IN {GEOCODE_CONFIDENCES}",
            name="ck_cameras_geocode_confidence",
        ),
        CheckConstraint(
            f"metadata_confidence IS NULL OR metadata_confidence IN {METADATA_CONFIDENCES}",
            name="ck_cameras_metadata_confidence",
        ),
    )

    camera_id: Mapped[str] = mapped_column(Text, primary_key=True)
    camera_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    location_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Nullable: required verbatim from the catalogue for API-synced cameras,
    # but a manually-registered camera (see CameraCreate) may have no stream
    # wired up yet -- metadata-only registration is allowed.
    rtsp_url: Mapped[str | None] = mapped_column(Text)
    hls_url: Mapped[str | None] = mapped_column(Text)
    webrtc_url: Mapped[str | None] = mapped_column(Text)

    codec: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Numeric)
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer)
    transport_ok: Mapped[str | None] = mapped_column(Text)

    anpr_viable: Mapped[bool | None] = mapped_column(Boolean)
    anpr_notes: Mapped[str | None] = mapped_column(Text)
    last_surveyed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    geocode_confidence: Mapped[str | None] = mapped_column(Text)
    geog: Mapped[str | None] = mapped_column(Geography(geometry_type="POINT", srid=4326, spatial_index=False))

    # Dynamic FK added by the RBAC migration. The value remains the
    # department name to preserve the existing API and CSV contracts.
    department: Mapped[str | None] = mapped_column(Text)

    # NULL = the official sandbox catalogue sync or manual onboarding
    # (unchanged from before this column existed); non-NULL = imported from
    # a named catalogue_sources row. RESTRICT so a source with cameras still
    # attached can't be deleted, only deactivated -- see
    # app/pipeline/catalogue_sources.py.
    source_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("catalogue_sources.id", ondelete="RESTRICT")
    )
    ownership: Mapped[str | None] = mapped_column(Text)
    camera_type: Mapped[str | None] = mapped_column(Text)
    connectivity: Mapped[str | None] = mapped_column(Text)
    storage_location: Mapped[str | None] = mapped_column(Text)
    retention_days: Mapped[int | None] = mapped_column(Integer)
    metadata_confidence: Mapped[str | None] = mapped_column(Text)

    is_live: Mapped[bool | None] = mapped_column(Boolean)
    last_successful_connect: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last probe's operator-readable outcome. The complete, append-only probe
    # observation sequence is in camera_health_observations.
    health_reason: Mapped[str | None] = mapped_column(Text)

    # Operator toggle for continuous ANPR monitoring (build spec §2.4). The
    # UI only ever sets this column; the analytics supervisor is what
    # actually spawns/stops the worker, on its own periodic tick.
    analytics_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def stream_available(self) -> bool:
        """Public API capability flag; raw source endpoints stay server-side."""
        return bool(self.hls_url)

    @property
    def analytics_stream_available(self) -> bool:
        """Whether an analytics worker has a supported source to consume.

        Browser playback deliberately remains HLS-only: a browser cannot play
        RTSP directly and raw source URLs must never leave the backend. The
        workers, however, can safely consume either HLS or RTSP/TCP, so this
        is a separate public capability instead of overloading
        ``stream_available``.
        """
        return bool(self.hls_url or self.rtsp_url)

    @property
    def webrtc_preview_available(self) -> bool:
        """Whether the local MediaMTX relay can build a WHEP preview.

        It can ingest either RTSP/TCP directly or the existing HLS fallback;
        the browser receives only authenticated WHEP signaling and never a
        raw source URL.
        """
        return bool(self.rtsp_url or self.hls_url)


class CameraHealthObservation(Base):
    """One append-only, transport-derived camera health observation."""

    __tablename__ = "camera_health_observations"
    __table_args__ = (
        CheckConstraint(f"status IN {HEALTH_STATUSES}", name="ck_camera_health_observations_status"),
        CheckConstraint(
            f"transport_ok IN {TRANSPORTS}", name="ck_camera_health_observations_transport_ok"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    camera_id: Mapped[str] = mapped_column(Text, ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # `probe` is intentionally explicit. Catalogue `live` remains a source
    # claim; it is not silently converted into a successful transport check.
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="probe")
    transport_ok: Mapped[str] = mapped_column(Text, nullable=False)
    is_live: Mapped[bool | None] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)


class CameraMaintenanceWorkOrder(Base):
    """Current state of one operator-maintained camera remediation task.

    Its append-only lifecycle entries live in ``camera_maintenance_events``;
    this row is the efficient current-state projection for the registry UI.
    """

    __tablename__ = "camera_maintenance_work_orders"
    __table_args__ = (
        CheckConstraint(
            f"status IN {MAINTENANCE_STATUSES}", name="ck_camera_maintenance_work_orders_status"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    camera_id: Mapped[str] = mapped_column(Text, ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CameraMaintenanceEvent(Base):
    """Immutable work-order activity shown as the maintenance history."""

    __tablename__ = "camera_maintenance_events"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN {MAINTENANCE_EVENT_TYPES}", name="ck_camera_maintenance_events_type"
        ),
        CheckConstraint(
            f"status IN {MAINTENANCE_STATUSES}", name="ck_camera_maintenance_events_status"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("camera_maintenance_work_orders.id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class Sighting(Base):
    __tablename__ = "sightings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    camera_id: Mapped[str] = mapped_column(Text, nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    plate: Mapped[str | None] = mapped_column(Text)
    vehicle_type: Mapped[str | None] = mapped_column(Text)
    vehicle_colour: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric)
    frame_pts_ms: Mapped[int | None] = mapped_column(BigInteger)
    # Bumped by the observation worker on stream reconnect or a PTS
    # discontinuity (e.g. the sandbox's simulated-live loop). frame_pts_ms is
    # only comparable to another row's within the same (camera_id, epoch_id).
    epoch_id: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Evidence fields (Section 5 live-test Phase 3). `plate` above is
    # already the normalised/format-repaired value the watchlist actually
    # matches against; raw_ocr_text is what OCR's single best individual
    # read said before that repair, kept as a separate, honest fact.
    raw_ocr_text: Mapped[str | None] = mapped_column(Text)
    bbox: Mapped[dict | None] = mapped_column(JSONB)
    model_version: Mapped[str | None] = mapped_column(Text)
    # Relative path under settings.evidence_dir. The row is the durable
    # record even after the file is removed by retention (see
    # app/pipeline/evidence.py) -- never nulled on expiry, only the bytes
    # disappear. Mirrors Track.thumb_path's same split in Investigate.
    evidence_path: Mapped[str | None] = mapped_column(Text)

    @property
    def has_evidence(self) -> bool:
        """Public API capability flag; the raw path stays server-side --
        same discipline as Camera.stream_available for stream URLs."""
        return bool(self.evidence_path)
