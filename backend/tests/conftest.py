"""Shared fixtures.

The Copilot suite runs with no database and no OpenRouter key. Tool handlers
are exercised through fakes because what is being tested is the *registry's*
contract -- schema safety, permission propagation, error shaping -- not
SQLAlchemy. The real queries are already covered by the routers these tools
delegate to.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# The app package is imported as `app.*`, so backend/ must be importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth_service import AuthContext  # noqa: E402
from app.models.auth import User  # noqa: E402


def make_user(*, role: str, home_department: str | None = "Traffic", user_id: int = 1) -> User:
    user = User()
    user.id = user_id
    user.full_name = "Test Officer"
    user.email = "officer@example.invalid"
    user.role = role
    user.home_department = home_department
    user.status = "active"
    return user


def make_auth(*, role: str = "super_admin", grants: dict[str, str] | None = None,
              home_department: str | None = "Traffic") -> AuthContext:
    return AuthContext(
        user=make_user(role=role, home_department=home_department),
        grants=grants or {},
    )


@dataclass
class FakeSession:
    """Stands in for AsyncSession: records what the registry writes."""

    added: list = field(default_factory=list)
    commits: int = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def flush(self):
        pass

    @property
    def audit_actions(self) -> list[str]:
        return [getattr(o, "action", None) for o in self.added]


@pytest.fixture
def super_admin() -> AuthContext:
    return make_auth(role="super_admin")


@pytest.fixture
def department_admin() -> AuthContext:
    return make_auth(role="department_admin", grants={"Traffic": "operator"})


@pytest.fixture
def department_user() -> AuthContext:
    """Operator clearance on Traffic only -- no camera-admin rights anywhere."""
    return make_auth(role="department_user", grants={"Traffic": "operator"})


@pytest.fixture
def viewer() -> AuthContext:
    return make_auth(role="department_user", grants={"Traffic": "viewer"})


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def ctx(super_admin, session):
    from app.agent.registry import ToolContext

    return ToolContext(auth=super_admin, session=session)
