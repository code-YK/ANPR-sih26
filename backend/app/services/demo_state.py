"""Pure state-file access for demo mode, split out from demo_mode.py itself.

demo_mode.py's orchestration (enable/disable) imports helpers from
app.routers.cameras (_new_manual_camera etc.) to create demo cameras through
the same code path real onboarding uses. cameras.py, in turn, needs to know
whether demo mode is currently active so its list/export query can hide the
real government-provided cameras while demo mode is on (see
_camera_list_statement). Those two facts together mean the "is demo mode
active" check has to live somewhere neither of those modules would create an
import cycle by depending on -- this file has no dependency on either.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
STATE_PATH = os.path.join(_REPO_ROOT, "fixtures", "live-test", "demo_mode_state.json")


def load() -> dict | None:
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH) as f:
        return json.load(f)


def save(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def clear() -> None:
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)


def is_active() -> bool:
    return load() is not None
