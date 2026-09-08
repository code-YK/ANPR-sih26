from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://localhost:5432/sentinel"
    sync_database_url: str = "postgresql+psycopg2://localhost:5432/sentinel"

    # Intentionally non-routable defaults. Supply authorised values through a
    # local .env or process environment; endpoint hosts do not belong in Git.
    sandbox_catalogue_url: str = "https://provided-outside-git.invalid/api/ingest"
    sandbox_browser_base_url: str = "https://provided-outside-git.invalid"
    # 2026-09-01 integrator's guide update: the catalogue and HLS host now
    # sit behind a single password-gated session (POST password to
    # {sandbox_browser_base_url}/auth/login -> Set-Cookie), not the
    # previous no-auth/bearer-header model -- see fetch_catalogue() in
    # app/pipeline/catalogue.py. None (the default) means "no login step",
    # so the legacy no-auth sandbox keeps working unchanged.
    sandbox_access_password: str | None = None
    # RTSP/WHEP are served directly off a public IP (unauthenticated,
    # confirmed by direct probe), never through the CDN/browser host above.
    # Also None-safe: only cameras from a sandbox that actually offers this
    # get rtsp_url/webrtc_url populated.
    sandbox_stream_host: str | None = None
    sandbox_rtsp_port: int = 8554
    sandbox_webrtc_port: int = 8889

    survey_dir: str = "survey"

    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    nominatim_user_agent: str = "sentinel-cctv-registry/0.1 (hackathon onboarding pipeline)"

    ffprobe_timeout_seconds: float = 25.0
    ffmpeg_capture_timeout_seconds: float = 25.0

    probe_concurrency: int = 1

    # Where this backend can be reached by the observation worker subprocess,
    # for its --report-to flag. Only meaningful on localhost for this build.
    backend_base_url: str = "http://127.0.0.1:8000"
    # Vehicle (ANPR) mode: a bounded, configurable worker pool. Three is the
    # verified local-demo profile; production deployments should size this
    # from measured GPU, decoder, and gateway capacity rather than treating
    # it as a promise that every machine can sustain three yolo11x workers.
    # Override via MAX_CONCURRENT_VEHICLE_WORKERS (env or .env).
    max_concurrent_vehicle_workers: int = 3
    # Person-counting mode: bonus analytics (GOV-FUN-013), manual per camera,
    # a lighter model (yolo11n.pt) than the ANPR path -- kept at the previous
    # shared-pool ceiling. Override via MAX_CONCURRENT_PERSON_WORKERS.
    max_concurrent_person_workers: int = 3
    # Suspicious-activity mode (best.pt "potentially_dangerous_person"): bonus
    # analytics, manual per camera, same lighter footprint as the person path.
    # Its own budget so it never competes with the mandatory ANPR pool.
    # Override via MAX_CONCURRENT_SUSPICIOUS_WORKERS.
    max_concurrent_suspicious_workers: int = 3
    analytics_open_timeout_seconds: float = 60.0

    # Demo authentication. The account identity may be stable, but its secret
    # must be supplied outside Git. Startup seeds the account only when both
    # email and password are present.
    super_admin_email: str | None = None
    super_admin_password: str | None = None
    super_admin_name: str = "Sentinel Super Admin"
    auth_cookie_name: str = "sentinel_session"
    auth_session_hours: int = 12
    auth_cookie_secure: bool = False

    # An administrator-controlled mount outside the repository and database
    # used to deliver audit snapshots to a retention service.  The application
    # writes a new archive once only; the mount itself must enforce WORM/object
    # retention because a normal filesystem permission bit is not immutability.
    audit_archive_dir: str | None = None

    # Service-to-service authentication for analytics workers posting
    # observations/counts. This is separate from human browser sessions.
    worker_api_token: str | None = None

    # Investigate: offline recordings uploaded for forensic search.
    recordings_dir: str = "recordings"
    max_upload_mb: int = 2048
    # Shared cap for ingest_runs in "running" state -- separate from the live
    # analytics caps above, so a long offline ingest cannot starve live ANPR,
    # and vice versa. One at a time by default: this backend has one GPU.
    max_concurrent_ingest_workers: int = 1
    ingest_heartbeat_stale_seconds: float = 90.0
    ffmpeg_normalise_timeout_seconds: float = 1800.0

    # Section 5 live-test Phase 3: a bounded evidence crop per confirmed
    # sighting (plate.py's PlateReader.best_evidence() + the current
    # frame's box). Same "files on disk, path in DB" split as recordings_dir
    # above -- short retention on purpose (a live sighting's evidence is
    # for immediate operator review, not indefinite storage); the sighting
    # row and everything derived from it (alert, journey stop) keeps its
    # evidence_path forever, only the file itself expires.
    evidence_dir: str = "evidence"
    evidence_retention_hours: float = 72.0

    # Section 5 live-test Phase 4: the documented watchlist matching policy.
    # Below this, a sighting is still recorded (never dropped -- observation
    # data stays complete) but does not raise an alert, on the theory that an
    # operator acting on a sub-threshold OCR read is more likely to chase a
    # false positive than catch a real one. 0.85 is the plan's own suggested
    # conservative starting point, not a measured optimum -- tune here as
    # real OCR confidence distributions come in.
    alert_min_confidence: float = 0.85

    # WebRTC/WHEP low-latency preview: a local MediaMTX relay, fed by ffmpeg
    # pulling the same hls_url the ANPR/person workers already consume
    # directly (the catalogue's own webrtc_url times out before SDP
    # negotiation on this network -- see docs/sandbox-access.md -- so it is
    # never used for playback). All three ports are bound to 127.0.0.1 only;
    # see docs/webrtc-relay-testing.md for the same-machine media-plane
    # reachability limitation this implies.
    #
    # NOTE (merge, live-test fixture collision): scripts/live_test_relay.py's
    # own mediamtx instance defaults to these exact same ports (8554/9997) --
    # the two were built on separate branches and never run side by side
    # before this merge. Only one mediamtx can bind a given port at a time,
    # so running the live-test fixture and the WebRTC preview relay
    # concurrently on one machine needs one of the two overridden via env
    # (e.g. MEDIAMTX_RTSP_PORT / MEDIAMTX_API_PORT here, or edit
    # live_test_relay.py's RTSP_PORT/API_PORT) until they're unified.
    mediamtx_bin: str = "mediamtx"
    mediamtx_rtsp_port: int = 8554
    mediamtx_webrtc_port: int = 8889
    mediamtx_api_port: int = 9997
    webrtc_relay_idle_timeout_seconds: float = 120.0
    webrtc_relay_start_timeout_seconds: float = 8.0
    # Only the focused camera gets a relay (see FocusedPlayer.jsx) -- 2, not
    # 1, gives headroom for the old relay to still be tearing down during a
    # focus-switch handoff without hitting the cap and evicting itself.
    max_concurrent_webrtc_relays: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
