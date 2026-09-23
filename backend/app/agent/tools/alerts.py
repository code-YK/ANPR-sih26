"""Alert triage tools."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.registry import ToolContext, tool
from app.routers.alerts import acknowledge_alert as _acknowledge_alert
from app.routers.alerts import list_alerts as _list_alerts
from app.routers.alerts import resolve_alert as _resolve_alert

ALERT_STATUSES = ("open", "acknowledged", "resolved")


class ListAlertsParams(BaseModel):
    status: str | None = Field(
        default=None, description=f"Filter by status, one of {list(ALERT_STATUSES)}."
    )
    camera_id: str | None = Field(default=None, description="Filter to one camera.")
    limit: int = Field(default=25, ge=1, le=100)


def _alert_brief(alert) -> dict:
    return {
        "alert_id": alert.id,
        "alert_type": alert.alert_type,
        "plate": alert.plate,
        "label": alert.label,
        "camera_id": alert.camera_id,
        "camera_name": alert.camera_name,
        "location": alert.location_text,
        "status": alert.status,
        "severity": alert.severity,
        "event_time": alert.event_time.isoformat() if alert.event_time else None,
    }


@tool(
    name="list_alerts",
    description=(
        "Watchlist-match alerts, newest first. Use for 'any alerts', 'what's open', 'show alerts "
        "on camera 7'. Pair with navigate_to(page='alerts')."
    ),
    params=ListAlertsParams,
)
async def list_alerts(params: ListAlertsParams, ctx: ToolContext) -> dict:
    rows = await _list_alerts(
        status=params.status,
        camera_id=params.camera_id,
        limit=params.limit,
        auth=ctx.auth,
        session=ctx.session,
    )
    return {"count": len(rows), "alerts": [_alert_brief(row) for row in rows]}


class AlertIdParams(BaseModel):
    alert_id: int = Field(description="Numeric alert id from list_alerts.")


@tool(
    name="acknowledge_alert",
    description=(
        "Mark one alert as acknowledged -- the operator has seen it and is handling it. Requires "
        "operator clearance. Reversible in effect; it does not delete anything."
    ),
    params=AlertIdParams,
    mutating=True,
)
async def acknowledge_alert(params: AlertIdParams, ctx: ToolContext) -> dict:
    alert = await _acknowledge_alert(alert_id=params.alert_id, auth=ctx.auth, session=ctx.session)
    return _alert_brief(alert)


@tool(
    name="resolve_alert",
    description=(
        "Mark one alert as resolved -- it has been dealt with. Requires operator clearance. The "
        "alert and its history are kept."
    ),
    params=AlertIdParams,
    mutating=True,
)
async def resolve_alert(params: AlertIdParams, ctx: ToolContext) -> dict:
    alert = await _resolve_alert(alert_id=params.alert_id, auth=ctx.auth, session=ctx.session)
    return _alert_brief(alert)


__all__ = ["acknowledge_alert", "list_alerts", "resolve_alert"]
