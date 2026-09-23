"""Watchlist tools.

Only list and create. Deletion is deliberately absent: it is the one
irreversible operation in this feature's reach, and v1 has no confirmation
step. It stays available on the Watchlist page.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.registry import ToolContext, tool
from app.models.watchlist import SEVERITIES
from app.routers.watchlist import create_watchlist_entry
from app.routers.watchlist import list_watchlist as _list_watchlist
from app.schemas import WatchlistEntryCreate


class ListWatchlistParams(BaseModel):
    plate: str | None = Field(default=None, description="Filter to one plate.")
    only_active: bool | None = Field(default=None, description="Restrict to active entries.")


@tool(
    name="list_watchlist",
    description=(
        "Vehicles currently on the watchlist. Pair with navigate_to(page='watchlist')."
    ),
    params=ListWatchlistParams,
)
async def list_watchlist(params: ListWatchlistParams, ctx: ToolContext) -> dict:
    rows = await _list_watchlist(
        active=params.only_active, plate=params.plate, _auth=ctx.auth, session=ctx.session
    )
    return {
        "count": len(rows),
        "entries": [
            {
                "id": row.id,
                "plate": row.raw_value,
                "normalised": row.normalised_value,
                "severity": row.severity,
                "reason_code": row.reason_code,
                "notes": row.notes,
                "active": row.active,
            }
            for row in rows
        ],
    }


class AddWatchlistParams(BaseModel):
    plate: str = Field(description="Registration number to watch for.")
    reason: str = Field(
        description="Why this vehicle is being watchlisted. Required -- it is written to the "
        "audit trail. Never invent it; ask the user."
    )
    severity: str = Field(
        default="medium", description=f"One of {list(SEVERITIES)}. Default medium."
    )


@tool(
    name="add_to_watchlist",
    description=(
        "Add a vehicle to the watchlist so live sightings raise an alert. Requires super-admin. "
        "Both the plate and a reason are required -- ask for the reason rather than inventing "
        "one, it goes into the audit record. Pair with navigate_to(page='watchlist')."
    ),
    params=AddWatchlistParams,
    mutating=True,
)
async def add_to_watchlist(params: AddWatchlistParams, ctx: ToolContext) -> dict:
    entry = await create_watchlist_entry(
        payload=WatchlistEntryCreate(
            raw_value=params.plate,
            severity=params.severity,
            notes=params.reason,
            source="copilot",
        ),
        auth=ctx.auth,
        session=ctx.session,
    )
    return {
        "id": entry.id,
        "plate": entry.raw_value,
        "normalised": entry.normalised_value,
        "severity": entry.severity,
        "notes": entry.notes,
        "active": entry.active,
    }


__all__ = ["add_to_watchlist", "list_watchlist"]
