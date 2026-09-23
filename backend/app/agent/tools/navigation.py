"""The page-awareness tool.

No backend work: this validates a destination and echoes it back, and the
chat client turns it into a react-router push. It is a tool rather than
something inferred from the other tools' results so the model can also honour
a bare "take me to the watchlist", and so navigation stays an explicit,
auditable decision instead of a side effect.
"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.agent.registry import RENDER_NAVIGATE, ToolContext, tool

# Must match the routes registered in frontend-v5/src/app/Shell.jsx.
PAGES = {
    "live": "/live",
    "live_camera": "/live/{cameraId}",
    "journeys": "/journeys",
    "journeys_plate": "/journeys/{plate}",
    "investigate": "/investigate",
    "watchlist": "/watchlist",
    "registry": "/registry",
    "alerts": "/alerts",
    "admin": "/admin",
}

PageName = Literal[
    "live",
    "live_camera",
    "journeys",
    "journeys_plate",
    "investigate",
    "watchlist",
    "registry",
    "alerts",
    "admin",
]


class NavigateParams(BaseModel):
    page: PageName = Field(description="Which console page to open.")
    camera_id: str | None = Field(
        default=None, description="Required for page='live_camera'."
    )
    plate: str | None = Field(default=None, description="Required for page='journeys_plate'.")


@tool(
    name="navigate_to",
    description=(
        "Open a page of the console for the operator. Call this in the SAME turn as the tool "
        "whose results the page shows -- trace_vehicle then navigate_to(page='journeys_plate'), "
        "list_alerts then navigate_to(page='alerts'), and so on. The chat panel stays open. You "
        "may also call it alone when the user simply asks to go somewhere. Only 'admin' is "
        "restricted; it requires an administrator."
    ),
    params=NavigateParams,
    render=RENDER_NAVIGATE,
)
async def navigate_to(params: NavigateParams, ctx: ToolContext) -> dict:
    if params.page == "live_camera" and not params.camera_id:
        raise HTTPException(status_code=422, detail="page='live_camera' needs camera_id")
    if params.page == "journeys_plate" and not params.plate:
        raise HTTPException(status_code=422, detail="page='journeys_plate' needs plate")
    if params.page == "admin" and not (ctx.auth.is_super_admin or ctx.auth.is_department_admin):
        raise HTTPException(status_code=403, detail="The Admin page requires an administrator account")

    path = PAGES[params.page]
    if params.camera_id:
        path = path.replace("{cameraId}", params.camera_id)
    if params.plate:
        path = path.replace("{plate}", params.plate.upper().replace(" ", ""))
    return {"page": params.page, "path": path}


__all__ = ["PAGES", "navigate_to"]
