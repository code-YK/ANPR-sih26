"""Permission behaviour of the tools that change state.

The distinction under test is the one that is easiest to get wrong in this
codebase: starting ANPR is a *camera edit* (camera-admin), while starting
Person/Suspicious analytics is an *operator* action. A department user with
operator clearance can do the second and must not be able to do the first.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.agent.registry import ToolContext, dispatch
from app.agent.tools.analytics import _require_camera_admin
from app.agent.tools.navigation import navigate_to
from app.models.camera import Camera
from tests.conftest import make_auth


def make_camera(camera_id: str = "cam07", department: str | None = "Traffic") -> Camera:
    camera = Camera()
    camera.camera_id = camera_id
    camera.name = f"Camera {camera_id}"
    camera.department = department
    camera.analytics_enabled = False
    camera.analytics_finetuned_enabled = False
    return camera


class SessionWithCamera:
    """FakeSession that can resolve one camera by id."""

    def __init__(self, camera: Camera | None):
        self.camera = camera
        self.added: list = []
        self.commits = 0

    async def get(self, _model, camera_id):
        if self.camera is not None and self.camera.camera_id == camera_id:
            return self.camera
        return None

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


class TestAnprRequiresCameraAdmin:
    async def test_super_admin_is_allowed_on_any_department(self):
        session = SessionWithCamera(make_camera(department="Highways"))
        ctx = ToolContext(auth=make_auth(role="super_admin"), session=session)
        camera = await _require_camera_admin("cam07", ctx)
        assert camera.camera_id == "cam07"

    async def test_department_admin_is_allowed_on_their_home_department(self):
        session = SessionWithCamera(make_camera(department="Traffic"))
        ctx = ToolContext(
            auth=make_auth(role="department_admin", home_department="Traffic"), session=session
        )
        camera = await _require_camera_admin("cam07", ctx)
        assert camera.department == "Traffic"

    async def test_department_admin_is_refused_on_another_department(self):
        session = SessionWithCamera(make_camera(department="Highways"))
        ctx = ToolContext(
            auth=make_auth(role="department_admin", home_department="Traffic"), session=session
        )
        with pytest.raises(HTTPException) as exc:
            await _require_camera_admin("cam07", ctx)
        assert exc.value.status_code == 403

    async def test_operator_clearance_alone_cannot_start_anpr(self):
        """The whole point of the distinction: operator clearance starts
        Person analytics but must not reach the camera's ANPR column."""
        session = SessionWithCamera(make_camera(department="Traffic"))
        ctx = ToolContext(
            auth=make_auth(role="department_user", grants={"Traffic": "operator"}), session=session
        )
        with pytest.raises(HTTPException) as exc:
            await _require_camera_admin("cam07", ctx)
        assert exc.value.status_code == 403
        assert "camera administration" in exc.value.detail.lower()

    async def test_missing_camera_is_404_not_403(self):
        """Order matters: a 403 for a camera that does not exist would let
        someone probe which camera ids are real."""
        session = SessionWithCamera(None)
        ctx = ToolContext(auth=make_auth(role="super_admin"), session=session)
        with pytest.raises(HTTPException) as exc:
            await _require_camera_admin("nope", ctx)
        assert exc.value.status_code == 404


class TestNavigationPermissions:
    async def test_admin_page_refused_for_department_user(self):
        ctx = ToolContext(
            auth=make_auth(role="department_user", grants={"Traffic": "operator"}), session=None
        )
        from app.agent.tools.navigation import NavigateParams

        with pytest.raises(HTTPException) as exc:
            await navigate_to(NavigateParams(page="admin"), ctx)
        assert exc.value.status_code == 403

    @pytest.mark.parametrize("role", ["super_admin", "department_admin"])
    async def test_admin_page_allowed_for_administrators(self, role):
        from app.agent.tools.navigation import NavigateParams

        ctx = ToolContext(auth=make_auth(role=role), session=None)
        result = await navigate_to(NavigateParams(page="admin"), ctx)
        assert result["path"] == "/admin"


class TestNavigationRouting:
    """Paths must match the routes registered in frontend-v5 Shell.jsx."""

    @pytest.mark.parametrize(
        "params,expected",
        [
            ({"page": "live"}, "/live"),
            ({"page": "live_camera", "camera_id": "cam07"}, "/live/cam07"),
            ({"page": "journeys"}, "/journeys"),
            ({"page": "journeys_plate", "plate": "GJ01AB1234"}, "/journeys/GJ01AB1234"),
            ({"page": "investigate"}, "/investigate"),
            ({"page": "watchlist"}, "/watchlist"),
            ({"page": "registry"}, "/registry"),
            ({"page": "alerts"}, "/alerts"),
        ],
    )
    async def test_routes(self, ctx, params, expected):
        result = await dispatch("navigate_to", params, ctx)
        assert result["ok"] is True
        assert result["data"]["path"] == expected

    async def test_plate_is_normalised_into_the_url(self, ctx):
        result = await dispatch(
            "navigate_to", {"page": "journeys_plate", "plate": "gj01 ab1234"}, ctx
        )
        assert result["data"]["path"] == "/journeys/GJ01AB1234"

    async def test_unknown_page_is_rejected_by_the_schema(self, ctx):
        result = await dispatch("navigate_to", {"page": "secret_admin_backdoor"}, ctx)
        assert result["ok"] is False
        assert "Invalid arguments" in result["error"]
