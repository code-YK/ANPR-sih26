"""Model 1 gap-analysis report: capability, coverage, and health/ageing gaps.

Runs on latitude/longitude/anpr_viable/width/height/fps/codec/is_live/
last_successful_connect/department only -- deliberately does not depend on
connectivity, storage_location, or retention_days, which can stay sparse.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models.camera import Camera
from app.services.districts import GUJARAT_DISTRICT_CENTROIDS, nearest_district

STALE_CONNECT_HOURS = 24
MIN_USABLE_WIDTH = 640
MIN_USABLE_HEIGHT = 480
MIN_USABLE_BITRATE_KBPS = 200


@dataclass
class CapabilityGap:
    camera_id: str
    camera_number: int
    name: str
    location_text: str
    department: str | None
    reason: str
    replacement_priority: bool


@dataclass
class CoverageDistrict:
    district: str
    camera_count: int


@dataclass
class HealthGap:
    camera_id: str
    camera_number: int
    name: str
    location_text: str
    department: str | None
    reasons: list[str]


@dataclass
class GapAnalysisReport:
    generated_at: datetime
    total_cameras: int
    capability_gaps: list[CapabilityGap] = field(default_factory=list)
    coverage_covered: list[CoverageDistrict] = field(default_factory=list)
    coverage_uncovered_districts: list[str] = field(default_factory=list)
    unplaced_camera_count: int = 0
    health_gaps: list[HealthGap] = field(default_factory=list)


def _capability_gap_reason(camera: Camera) -> str:
    if camera.anpr_notes:
        return camera.anpr_notes
    if camera.transport_ok == "none":
        return "camera unreachable during survey"
    if camera.width and camera.width < MIN_USABLE_WIDTH:
        return "resolution too low for plate legibility"
    return "not viable for ANPR (no reason recorded)"


def _build_capability_gaps(cameras: list[Camera]) -> list[CapabilityGap]:
    gaps = []
    for cam in cameras:
        if cam.anpr_viable is not False:
            continue
        reason = _capability_gap_reason(cam)
        # A camera that is otherwise healthy (live, connecting, reasonable
        # resolution) but still fails ANPR is the strongest replacement
        # candidate -- the gap is capability, not a dead camera.
        replacement_priority = bool(cam.is_live) and cam.transport_ok in ("rtsp", "hls")
        gaps.append(
            CapabilityGap(
                camera_id=cam.camera_id,
                camera_number=cam.camera_number,
                name=cam.name,
                location_text=cam.location_text,
                department=cam.department,
                reason=reason,
                replacement_priority=replacement_priority,
            )
        )
    gaps.sort(key=lambda g: (not g.replacement_priority, g.camera_number))
    return gaps


def _build_coverage(cameras: list[Camera]) -> tuple[list[CoverageDistrict], list[str], int]:
    placed = [c for c in cameras if c.latitude is not None and c.longitude is not None]
    unplaced_count = len(cameras) - len(placed)

    counts: Counter[str] = Counter()
    for cam in placed:
        counts[nearest_district(float(cam.latitude), float(cam.longitude))] += 1

    all_districts = [d for d, _, _ in GUJARAT_DISTRICT_CENTROIDS]
    covered = sorted(
        (CoverageDistrict(district=d, camera_count=n) for d, n in counts.items()),
        key=lambda c: -c.camera_count,
    )
    uncovered = sorted(d for d in all_districts if d not in counts)
    return covered, uncovered, unplaced_count


def _health_gap_reasons(camera: Camera, now: datetime) -> list[str]:
    reasons = []
    if camera.is_live is False:
        reasons.append("catalogue reports camera offline (is_live=false)")
    if camera.transport_ok == "none":
        reasons.append("no transport (RTSP/HLS) connected during last probe")
    if camera.last_successful_connect is None:
        reasons.append("never successfully connected")
    elif (now - camera.last_successful_connect).total_seconds() > STALE_CONNECT_HOURS * 3600:
        hours = (now - camera.last_successful_connect).total_seconds() / 3600
        reasons.append(f"last successful connect {hours:.0f}h ago (stale)")
    if camera.width and camera.width < MIN_USABLE_WIDTH:
        reasons.append(f"resolution below usable threshold ({camera.width}px wide)")
    if camera.height and camera.height < MIN_USABLE_HEIGHT:
        reasons.append(f"resolution below usable threshold ({camera.height}px tall)")
    if camera.bitrate_kbps is not None and camera.bitrate_kbps < MIN_USABLE_BITRATE_KBPS:
        reasons.append(f"bitrate below usable threshold ({camera.bitrate_kbps}kbps)")
    return reasons


def _build_health_gaps(cameras: list[Camera], now: datetime) -> list[HealthGap]:
    gaps = []
    for cam in cameras:
        reasons = _health_gap_reasons(cam, now)
        if reasons:
            gaps.append(
                HealthGap(
                    camera_id=cam.camera_id,
                    camera_number=cam.camera_number,
                    name=cam.name,
                    location_text=cam.location_text,
                    department=cam.department,
                    reasons=reasons,
                )
            )
    gaps.sort(key=lambda g: g.camera_number)
    return gaps


def build_gap_analysis_report(cameras: list[Camera]) -> GapAnalysisReport:
    now = datetime.now(timezone.utc)
    covered, uncovered, unplaced = _build_coverage(cameras)
    return GapAnalysisReport(
        generated_at=now,
        total_cameras=len(cameras),
        capability_gaps=_build_capability_gaps(cameras),
        coverage_covered=covered,
        coverage_uncovered_districts=uncovered,
        unplaced_camera_count=unplaced,
        health_gaps=_build_health_gaps(cameras, now),
    )
