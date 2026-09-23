"""Importing this package registers every tool.

Import for side effects: each module's @tool decorators populate
app.agent.registry.TOOLS at import time.
"""

from app.agent.tools import alerts, analytics, cameras, navigation, vehicles, watchlist  # noqa: F401

__all__ = ["alerts", "analytics", "cameras", "navigation", "vehicles", "watchlist"]
