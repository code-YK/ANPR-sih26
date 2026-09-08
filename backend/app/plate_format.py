"""Indian plate normalisation, standalone from the ANPR/OCR stack.

The backend only ever needs to compare already-read plate strings for
watchlist matching -- it never runs OCR -- so it carries just the format
rules from multi-object-tracking/plates.py rather than depending on that
package's fast-alpr/torch/ultralytics stack. Keep this in sync with
plates.normalise()/is_valid_indian() if either changes; the logic is small
and stable enough that duplication is cheaper than a cross-repo dependency
from a lightweight API process onto a heavy ML one.
"""

import re

INDIAN_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")


def normalise(text: str) -> str:
    """Uppercase and strip anything that cannot appear in a plate."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def is_valid_indian(text: str) -> bool:
    return bool(INDIAN_PLATE_RE.match(normalise(text)))
