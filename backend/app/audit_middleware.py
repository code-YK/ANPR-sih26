"""Central audit coverage for authenticated metadata reads and authorisation denials.

State-changing routes retain their existing domain-specific audit events. This
middleware supplies the missing access trail without logging raw URLs or query
values, which may contain sensitive identifiers.
"""

import asyncio
import logging

from fastapi import Request

from app.auth_service import AuthContext, add_audit_event
from app.db import async_session

logger = logging.getLogger("sentinel.audit")

# These authenticated paths can be requested many times per second by a video
# player or polling UI. Auditing every segment/frame would turn audit storage
# into a denial-of-service vector; their access is still enforced by the API.
_HIGH_FREQUENCY_PREFIXES = (
    "/api/hls/",
    "/api/analytics/telemetry/",
    "/api/analytics/snapshot/",
    "/api/analytics/stream/",
    "/api/investigate/recordings/",
    "/api/investigate/runs/",
)


def _route_pattern(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else request.url.path


def _is_high_frequency_media_path(path: str) -> bool:
    if path.startswith("/api/investigate/"):
        # Investigate metadata/list/search reads remain auditable; only file,
        # thumbnail, and high-cardinality track-box media endpoints are not.
        return "/media" in path or "/thumb" in path or "/boxes" in path
    return path.startswith(_HIGH_FREQUENCY_PREFIXES[:4])


_pending_writes: set[asyncio.Task] = set()


async def _write_audit_event(actor, action: str, target_id: str, result: str, details: dict) -> None:
    try:
        async with async_session() as session:
            add_audit_event(
                session,
                actor=actor,
                action=action,
                target_type="api_route",
                target_id=target_id,
                result=result,
                details=details,
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - a failed audit write is logged, never raised into a finished request
        logger.exception("Failed to record %s audit event for %s", action, target_id)


async def append_access_audit(request: Request, status_code: int) -> None:
    """Record one safe metadata-read or authorisation-denial audit event.

    The decision (what to record) is made here, synchronously; the database
    write itself runs as a task after the response is on its way. Awaiting it
    inline added a full session round trip -- ~0.3-0.4 s against the remote
    database -- to every authenticated GET, including the console's polls,
    which is most of what made the UI feel slow. Every event is still written;
    only its latency moved out of the request.
    """
    path = request.url.path
    if not path.startswith("/api/"):
        return
    auth = getattr(request.state, "auth_context", None)
    if not isinstance(auth, AuthContext):
        # Authentication failures are recorded inside get_current_auth, where
        # a known disabled/expired actor is still available when applicable.
        return
    if status_code == 403:
        action = "api.access_denied"
        result = "denied"
        details = {"method": request.method, "status_code": status_code, "reason": "authorisation"}
    elif _is_high_frequency_media_path(path):
        return
    elif request.method == "GET" and 200 <= status_code < 400:
        action = "api.read"
        result = "success"
        details = {"method": request.method, "status_code": status_code}
    else:
        return
    task = asyncio.create_task(_write_audit_event(auth.user, action, _route_pattern(request), result, details))
    # Hold a reference until it finishes; a bare create_task can be garbage
    # collected mid-flight.
    _pending_writes.add(task)
    task.add_done_callback(_pending_writes.discard)
