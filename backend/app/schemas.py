from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.camera import (
    CAMERA_TYPES,
    GEOCODE_CONFIDENCES,
    MAINTENANCE_STATUSES,
    METADATA_CONFIDENCES,
    OWNERSHIPS,
    TRANSPORTS,
)
from app.models.recording import INGEST_KINDS
from app.models.watchlist import SEVERITIES


class CameraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    camera_id: str
    camera_number: int
    name: str
    location_text: str

    # Raw source URLs remain server-side. Browser playback uses the
    # authenticated HLS relay and only needs to know if one is available.
    stream_available: bool
    # Analytics can additionally consume RTSP/TCP. This is intentionally a
    # capability flag rather than an endpoint so it cannot leak source URLs.
    analytics_stream_available: bool

    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    bitrate_kbps: int | None
    transport_ok: str | None

    anpr_viable: bool | None
    anpr_notes: str | None
    last_surveyed_at: datetime | None

    latitude: float | None
    longitude: float | None
    geocode_confidence: str | None

    department: str | None
    ownership: str | None
    camera_type: str | None
    connectivity: str | None
    storage_location: str | None
    retention_days: int | None
    metadata_confidence: str | None

    is_live: bool | None
    last_successful_connect: datetime | None
    health_reason: str | None
    analytics_enabled: bool

    # A plain internal reference id, not sensitive like the source's URL/
    # credential fields -- NULL means the official sandbox catalogue sync
    # or manual onboarding, unchanged from before catalogue_sources existed.
    source_id: int | None

    created_at: datetime
    updated_at: datetime


def _validate_choice_fields(
    *,
    department: str | None,
    ownership: str | None,
    camera_type: str | None,
    metadata_confidence: str | None,
    geocode_confidence: str | None,
) -> list[str]:
    errors = []
    # Department existence is validated asynchronously against the dynamic
    # departments table in the camera router.
    if ownership is not None and ownership not in OWNERSHIPS:
        errors.append(f"ownership must be one of {OWNERSHIPS}")
    if camera_type is not None and camera_type not in CAMERA_TYPES:
        errors.append(f"camera_type must be one of {CAMERA_TYPES}")
    if metadata_confidence is not None and metadata_confidence not in METADATA_CONFIDENCES:
        errors.append(f"metadata_confidence must be one of {METADATA_CONFIDENCES}")
    if geocode_confidence is not None and geocode_confidence not in GEOCODE_CONFIDENCES:
        errors.append(f"geocode_confidence must be one of {GEOCODE_CONFIDENCES}")
    return errors


class CameraOperatorUpdate(BaseModel):
    """Fields an operator may set. All optional; only provided fields are applied."""

    department: str | None = Field(default=None, description="Existing department name")
    ownership: str | None = Field(default=None, description=f"One of {OWNERSHIPS}")
    camera_type: str | None = Field(default=None, description=f"One of {CAMERA_TYPES}")
    connectivity: str | None = None
    storage_location: str | None = None
    retention_days: int | None = None
    metadata_confidence: str | None = Field(default=None, description=f"One of {METADATA_CONFIDENCES}")

    latitude: float | None = None
    longitude: float | None = None
    geocode_confidence: str | None = Field(default=None, description=f"One of {GEOCODE_CONFIDENCES}")

    anpr_viable: bool | None = None
    anpr_notes: str | None = None

    analytics_enabled: bool | None = None

    def validate_choices(self) -> list[str]:
        return _validate_choice_fields(
            department=self.department,
            ownership=self.ownership,
            camera_type=self.camera_type,
            metadata_confidence=self.metadata_confidence,
            geocode_confidence=self.geocode_confidence,
        )


class CameraCreate(BaseModel):
    """Manual onboarding: register a camera that isn't in the sandbox catalogue.

    camera_id and camera_number are assigned server-side (see routers/cameras.py)
    to guarantee a manually-created row can never collide with a future
    catalogue-synced camera_id.
    """

    name: str
    location_text: str

    rtsp_url: str | None = None
    hls_url: str | None = None
    webrtc_url: str | None = None

    department: str | None = Field(default=None, description="Existing department name")
    ownership: str | None = Field(default=None, description=f"One of {OWNERSHIPS}")
    camera_type: str | None = Field(default=None, description=f"One of {CAMERA_TYPES}")
    connectivity: str | None = None
    storage_location: str | None = None
    retention_days: int | None = None
    metadata_confidence: str | None = Field(default=None, description=f"One of {METADATA_CONFIDENCES}")

    latitude: float | None = None
    longitude: float | None = None
    geocode_confidence: str | None = Field(default=None, description=f"One of {GEOCODE_CONFIDENCES}")

    def validate_choices(self) -> list[str]:
        errors = _validate_choice_fields(
            department=self.department,
            ownership=self.ownership,
            camera_type=self.camera_type,
            metadata_confidence=self.metadata_confidence,
            geocode_confidence=self.geocode_confidence,
        )
        if not self.name.strip():
            errors.append("name must not be blank")
        if not self.location_text.strip():
            errors.append("location_text must not be blank")
        return errors


class BulkImportRowResult(BaseModel):
    camera_id: str
    status: str  # "created" | "updated" | "error"
    errors: list[str] = []


class BulkImportResult(BaseModel):
    total_rows: int
    created: int
    updated: int
    failed: int
    results: list[BulkImportRowResult]


class CameraHealthObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    observed_at: datetime
    status: str
    source: str
    transport_ok: str
    is_live: bool | None
    reason: str | None


class CameraMaintenanceCreate(BaseModel):
    summary: str
    note: str | None = None

    def validate_content(self) -> list[str]:
        errors = []
        if not self.summary.strip():
            errors.append("summary must not be blank")
        if self.note is not None and not self.note.strip():
            errors.append("note must not be blank when provided")
        return errors


class CameraMaintenanceUpdate(BaseModel):
    status: str | None = Field(default=None, description=f"One of {MAINTENANCE_STATUSES}")
    note: str | None = None

    def validate_content(self) -> list[str]:
        errors = []
        if self.status is not None and self.status not in MAINTENANCE_STATUSES:
            errors.append(f"status must be one of {MAINTENANCE_STATUSES}")
        if self.note is not None and not self.note.strip():
            errors.append("note must not be blank when provided")
        if self.status is None and self.note is None:
            errors.append("provide status or note")
        return errors


class CameraMaintenanceEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    event_type: str
    status: str
    note: str | None


class CameraMaintenanceWorkOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: str
    summary: str
    status: str
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    events: list[CameraMaintenanceEventOut]


class SyncResult(BaseModel):
    fetched: int
    inserted: int
    updated: int
    disappeared: list[str]


class CatalogueSourceCreate(BaseModel):
    name: str
    adapter: str = Field(description="One of the registered adapters, see app/pipeline/catalogue_sources.py")
    base_url: str
    browser_base_url: str | None = None
    auth_header_name: str | None = None
    auth_secret: str | None = None
    allow_private_host: bool = False


class CatalogueSourceUpdate(BaseModel):
    """All optional; only provided fields are applied. Omitting auth_secret
    leaves the stored value unchanged -- same secret-rotation UX as never
    re-sending a password hash. There is no way to set it back to null
    through this route; delete and recreate the source for that."""

    name: str | None = None
    adapter: str | None = None
    base_url: str | None = None
    browser_base_url: str | None = None
    auth_header_name: str | None = None
    auth_secret: str | None = None
    allow_private_host: bool | None = None
    active: bool | None = None


class CatalogueSourceOut(BaseModel):
    """Deliberately omits auth_secret entirely -- not masked, not present."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    adapter: str
    base_url: str
    browser_base_url: str | None
    auth_header_name: str | None
    allow_private_host: bool
    active: bool
    created_at: datetime
    updated_at: datetime
    last_synced_at: datetime | None
    last_sync_result: dict | None


class ProbeResult(BaseModel):
    camera_id: str
    transport_ok: str
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    bitrate_kbps: int | None
    error: str | None = None


class ProbeRunResult(BaseModel):
    probed: int
    results: list[ProbeResult]


class GeocodeResult(BaseModel):
    camera_id: str
    latitude: float | None
    longitude: float | None
    geocode_confidence: str


class GeocodeRunResult(BaseModel):
    geocoded: int
    results: list[GeocodeResult]


class GeocodeSearchResult(BaseModel):
    display_name: str
    latitude: float
    longitude: float


# --------------------------------------------------------------------------
# Sightings, watchlist, alerts (Model 2 vertical slice)
# --------------------------------------------------------------------------


class SightingCreate(BaseModel):
    """Posted by an observation worker for one confirmed detection.

    seen_at must already be PTS-anchored by the worker (see
    multi-object-tracking/camera_feeds.py's ProgramDateTimeAnchor) -- this
    endpoint never substitutes datetime.now() for a missing timestamp.
    """

    camera_id: str
    plate: str | None = None
    vehicle_type: str | None = None
    vehicle_colour: str | None = None
    confidence: float | None = None
    seen_at: datetime
    frame_pts_ms: int | None = None
    epoch_id: int = 0

    # Evidence fields (Section 5 live-test Phase 3), all optional -- a
    # worker without --plates, or a track whose crop never cleared the
    # size gate, still reports a sighting with none of these. The image
    # itself is never carried in this JSON payload: the worker (same host
    # as the backend, same convention as recordings_dir) writes the crop
    # directly under settings.evidence_dir and reports only the resulting
    # relative path.
    raw_ocr_text: str | None = None
    bbox: dict | None = None
    model_version: str | None = None
    evidence_path: str | None = None


class SightingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: str
    seen_at: datetime
    plate: str | None
    vehicle_type: str | None
    vehicle_colour: str | None
    confidence: float | None
    frame_pts_ms: int | None
    epoch_id: int
    raw_ocr_text: str | None = None
    bbox: dict | None = None
    model_version: str | None = None

    # Deliberately not the raw evidence_path -- same "capability flag, not
    # the endpoint" discipline as Camera.stream_available. A caller that
    # wants the image requests GET /sightings/{id}/evidence, which
    # rechecks department authorisation and returns 404 once retention has
    # actually deleted the file (not just when this flag looks stale).
    has_evidence: bool = False


class SightingIngestResult(BaseModel):
    sighting_id: int
    matched: bool
    alert_id: int | None = None


class WatchlistEntryCreate(BaseModel):
    raw_value: str
    reason_code: str | None = None
    severity: str = Field(default="medium", description=f"One of {SEVERITIES}")
    notes: str | None = None
    source: str | None = None
    active: bool = True

    def validate_choices(self) -> list[str]:
        errors = []
        if self.severity not in SEVERITIES:
            errors.append(f"severity must be one of {SEVERITIES}")
        if not self.raw_value.strip():
            errors.append("raw_value must not be blank")
        return errors


class WatchlistEntryUpdate(BaseModel):
    """All optional; only provided fields are applied."""

    reason_code: str | None = None
    severity: str | None = Field(default=None, description=f"One of {SEVERITIES}")
    notes: str | None = None
    source: str | None = None
    active: bool | None = None

    def validate_choices(self) -> list[str]:
        if self.severity is not None and self.severity not in SEVERITIES:
            return [f"severity must be one of {SEVERITIES}"]
        return []


class WatchlistEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_type: str
    raw_value: str
    normalised_value: str
    reason_code: str | None
    severity: str
    notes: str | None
    source: str | None
    active: bool
    created_at: datetime
    updated_at: datetime


class WatchlistBulkRowResult(BaseModel):
    raw_value: str
    status: str  # "added" | "error"
    errors: list[str] = []


class WatchlistBulkResult(BaseModel):
    total_rows: int
    added: int
    failed: int
    results: list[WatchlistBulkRowResult]


class JourneyStop(BaseModel):
    sighting_id: int
    camera_id: str
    camera_name: str
    location_text: str
    department: str | None
    latitude: float | None
    longitude: float | None
    geocode_confidence: str | None
    seen_at: datetime
    confidence: float | None
    vehicle_type: str | None
    epoch_id: int
    has_evidence: bool = False


class VehicleJourney(BaseModel):
    plate: str
    sighting_count: int
    camera_count: int
    first_seen: datetime | None
    last_seen: datetime | None
    stops: list[JourneyStop]
    # Stops on cameras with no coordinates are still counted here, never
    # silently dropped from sighting_count/stops -- same provenance rule as
    # geocode_confidence elsewhere in the registry.
    unplaced_stops: int
    # Authorised users receive visible stops plus an explicit count of stops
    # omitted because their camera belongs to another department.
    restricted_stops: int = 0


class JourneyExportStop(BaseModel):
    """One row of GET /vehicles/{plate}/journey/export -- a superset of
    JourneyStop with the extra fields the Section 5 live-test plan's
    report spec calls for (sequence, evidence reference, alert status)
    that the browser map/timeline view doesn't need."""
    sequence: int
    sighting_id: int
    camera_id: str
    camera_name: str
    department: str | None
    location_text: str
    latitude: float | None
    longitude: float | None
    geocode_confidence: str | None
    seen_at: datetime
    confidence: float | None
    # Server-relative path to GET .../evidence, never the raw file --
    # same discipline as has_evidence elsewhere; the endpoint it points at
    # re-checks department authorisation on every request regardless of
    # who generated this report.
    evidence_url: str | None
    alert_id: int | None
    alert_status: str | None


class JourneyExportReport(BaseModel):
    plate: str
    generated_at: datetime
    sighting_count: int
    camera_count: int
    first_seen: datetime | None
    last_seen: datetime | None
    unplaced_stops: int
    restricted_stops: int
    stops: list[JourneyExportStop]


class AlertOut(BaseModel):
    id: int
    # Null for a "suspicious" alert -- it has no plate sighting and no
    # watchlist entry; the ANPR "watchlist" path always populates both.
    sighting_id: int | None
    watchlist_entry_id: int | None
    camera_id: str
    # "watchlist" (ANPR plate match) or "suspicious" (dangerous-person
    # detection). Lets the UI render the right identity column per alert.
    alert_type: str = "watchlist"
    event_time: datetime
    match_confidence: float | None
    dedup_key: str
    status: str
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime

    # Denormalised for the UI. For a watchlist alert these are joined from
    # sightings/cameras/watchlist_entries at read time; for a suspicious
    # alert `plate`/`reason_code` are null and `label`/`severity` come off
    # the alert row itself. `camera_name`/`location_text` are always present
    # (the camera FK is non-nullable).
    plate: str | None = None
    label: str | None = None
    has_evidence: bool = False
    camera_name: str
    location_text: str
    department: str | None
    reason_code: str | None
    severity: str | None = None


class SuspiciousAlertCreate(BaseModel):
    """Posted by the suspicious-activity worker when a tracked person is
    classified as potentially dangerous. Deliberately not a `sighting`:
    there is no plate/identity, so it never enters the journey or watchlist
    paths -- it is a standalone alert with its own label and severity.

    `event_time` is the PTS-anchored detection time when the stream is
    anchored; the worker omits it (and the backend stamps arrival time)
    only when the stream never anchored, since -- unlike a plate sighting
    that feeds a journey -- an un-anchored suspicious alert is still
    actionable for immediate review.
    """

    camera_id: str
    track_id: int
    confidence: float | None = None
    label: str = "Potentially dangerous person"
    severity: str = Field(default="high", description=f"One of {SEVERITIES}")
    event_time: datetime | None = None


class AnalyticsCountCreate(BaseModel):
    """Posted periodically by a non-ANPR worker (person mode). Never a
    substitute for `sightings` -- there is no plate/identity here."""

    camera_id: str
    mode: str = "person"
    window_start: datetime
    window_end: datetime
    unique_tracks: int
    peak_concurrent: int


class AnalyticsCountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: str
    mode: str
    window_start: datetime
    window_end: datetime
    unique_tracks: int
    peak_concurrent: int
    created_at: datetime


# --------------------------------------------------------------------------
# Investigate: offline recordings, ingest runs, tracks, subjects
# --------------------------------------------------------------------------

class RecordingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    content_sha256: str
    content_type: str | None
    size_bytes: int
    duration_seconds: float | None
    fps_num: int | None
    fps_den: int | None
    frame_count: int | None
    width: int | None
    height: int | None
    department: str
    camera_id: str | None
    location_text: str | None
    recorded_at: datetime | None
    status: str
    reject_reason: str | None
    uploaded_by: int | None
    created_at: datetime


class RecordingUploadFields(BaseModel):
    """Multipart form fields alongside the file. Not the file itself --
    FastAPI takes that as a separate `UploadFile` parameter."""

    department: str
    camera_id: str | None = None
    location_text: str | None = None
    recorded_at: datetime | None = None

    def validate_choices(self) -> list[str]:
        errors = []
        if not self.department.strip():
            errors.append("department must not be blank")
        return errors


class IngestRunCreate(BaseModel):
    kind: str = Field(description=f"One of {INGEST_KINDS}")
    model: str | None = None
    imgsz: int | None = None

    def validate_choices(self) -> list[str]:
        errors = []
        if self.kind not in INGEST_KINDS:
            errors.append(f"kind must be one of {INGEST_KINDS}")
        return errors


class IngestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recording_id: int
    kind: str
    model: str
    tracker_config: str
    imgsz: int
    frame_stride: int
    effective_tracker_settings: dict | None
    status: str
    progress_pct: float
    frames_processed: int
    frames_expected: int | None
    track_count: int
    chunk_count_expected: int | None
    chunk_count_received: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    # Not a DB column -- computed by the router from the same queue the
    # supervisor tick uses, so "queued behind the concurrency cap" is
    # distinguishable from "broken", the same reasoning as the live
    # analytics status endpoint's `queue_position`.
    queue_position: int | None = None


class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: int
    track_ref: int
    recording_id: int
    kind: str
    occurrence_index: int
    first_frame: int
    last_frame: int
    first_ms: int
    last_ms: int
    frame_count: int
    best_conf: float
    thumb_path: str | None
    plate_confirmed: str | None
    plate_tentative: str | None
    plate_confidence: float | None
    plate_votes: int | None
    embedding_model: str | None
    subject_id: int | None
    link_method: str | None
    link_score: float | None
    created_at: datetime


class TrackBoxesOut(BaseModel):
    """The fixed-rate bbox timeline, served separately from TrackOut so a
    results list never drags a track's full timeline along with it (see
    Track.boxes's `deferred()` in the model)."""

    t0_ms: int
    dt_ms: int
    w: int
    h: int
    b: list[list[int]]


class IngestChunkTrack(BaseModel):
    """One finalised track, as reported by the ingest worker. A track is
    only ever sent once it has been absent longer than the run's effective
    track_buffer -- i.e. it is truly final and will not be revised."""

    track_ref: int
    kind: str
    first_frame: int
    last_frame: int
    first_ms: int
    last_ms: int
    frame_count: int
    best_conf: float
    boxes: TrackBoxesOut
    thumb_path: str | None = None
    plate_confirmed: str | None = None
    plate_tentative: str | None = None
    plate_confidence: float | None = None
    plate_votes: int | None = None
    # Person tracks only -- base64-encoded packed float32 bytes (see
    # multi-object-tracking/person_embedding.py). Absent/None for vehicle
    # tracks and for any person track an embedding hiccup skipped.
    embedding: str | None = None
    embedding_dim: int | None = None
    embedding_model: str | None = None


class IngestChunkPayload(BaseModel):
    """POSTed by the worker, worker-token only. `seq` is a monotonic
    per-run counter the worker also uses as its disk-spool filename, making
    a replayed chunk (after a network hiccup) an idempotent no-op rather
    than duplicate rows."""

    seq: int
    tracks: list[IngestChunkTrack]


class IngestHeartbeatPayload(BaseModel):
    """Sent periodically even when no track has finalised yet -- a quiet
    stretch of video with nothing to flush must not look identical to a
    hung worker to the stall reaper."""

    frames_processed: int
    frames_expected: int | None = None
    track_count: int = 0


class IngestCompletePayload(BaseModel):
    frames_processed: int
    track_count: int
    chunk_count: int
    error: str | None = None


class PlateSearchQuery(BaseModel):
    plate: str
    fuzzy: bool = True
    limit: int = 50

    def validate_choices(self) -> list[str]:
        errors = []
        if not self.plate.strip():
            errors.append("plate must not be blank")
        if not (1 <= self.limit <= 500):
            errors.append("limit must be between 1 and 500")
        return errors


class PlateSearchHit(BaseModel):
    track: TrackOut
    recording: RecordingOut
    matched_plate: str
    match_kind: str  # "exact" | "fuzzy"


class PersonSearchHit(BaseModel):
    """One candidate match for a person-photo query. `similarity` is a
    cosine similarity (both vectors L2-normalised at embed time, so this
    is a plain dot product) against a generic ImageNet appearance
    embedding -- see multi-object-tracking/person_embedding.py's module
    docstring for what this is and, just as importantly, is not."""
    track: TrackOut
    recording: RecordingOut
    similarity: float


class SubjectCreate(BaseModel):
    kind: str = Field(description=f"One of {INGEST_KINDS}")
    label: str
    plate: str | None = None
    notes: str | None = None

    def validate_choices(self) -> list[str]:
        errors = []
        if self.kind not in INGEST_KINDS:
            errors.append(f"kind must be one of {INGEST_KINDS}")
        if not self.label.strip():
            errors.append("label must not be blank")
        return errors


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    label: str
    plate: str | None
    notes: str | None
    created_by: int | None
    created_at: datetime


class TrackLinkRequest(BaseModel):
    subject_id: int


class DemoModeStatus(BaseModel):
    enabled: bool
    activated_at: str | None
    camera_count: int
    plate: str | None


class DemoModeToggle(BaseModel):
    enabled: bool


class GovernmentModeStatus(BaseModel):
    enabled: bool
    activated_at: str | None
    camera_ids: list[str]


class GovernmentModeToggle(BaseModel):
    enabled: bool


class CameraSightingReportRow(BaseModel):
    sequence: int
    sighting_id: int
    seen_at: datetime
    plate: str | None
    confidence: float | None
    vehicle_type: str | None
    evidence_url: str | None


class CameraSightingReport(BaseModel):
    camera_id: str
    camera_name: str
    location_text: str
    department: str | None
    generated_at: datetime
    sighting_count: int
    distinct_plate_count: int
    first_seen: datetime | None
    last_seen: datetime | None
    rows: list[CameraSightingReportRow]
