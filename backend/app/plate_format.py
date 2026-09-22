"""Indian plate normalisation, standalone from the ANPR/OCR stack.

The backend only ever needs to compare already-read plate strings for
watchlist matching -- it never runs OCR -- so it carries just the format
rules from multi-object-tracking/plates.py rather than depending on that
package's fast-alpr/torch/ultralytics stack. Keep this in sync with
plates.normalise()/is_valid_indian() if either changes; the logic is small
and stable enough that duplication is cheaper than a cross-repo dependency
from a lightweight API process onto a heavy ML one.

Valid plates, exactly as read (no character is coerced to fit):
  * <state><2-digit district><0-3 series letters><4 digits>   UP14FS3664
  * Delhi: DL<1-2 digit district><1-3 letters><4 digits>       DL2CBB4791
  * Bharat series: <2-digit year>BH<4 digits><1-2 letters>     22BH1234AA
with a known state/UT code, no I or O in the series letters, and (Delhi) an
issued category letter first.
"""

import re

INDIAN_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")
BH_PLATE_RE = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")
_PLATE_PARTS_RE = re.compile(r"^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{4})$")

# Series letters never include I or O; Delhi's first letter is its category.
SERIES_EXCLUDED = frozenset("IO")
DELHI_CATEGORIES = frozenset("ABCEFGKLMNPQRSTUVWYZ")

STATE_CODES = frozenset({
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
    "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TG", "TN", "TR", "TS",
    "UA", "UK", "UP", "WB",
})


def normalise(text: str) -> str:
    """Uppercase and strip anything that cannot appear in a plate."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def is_valid_indian(text: str) -> bool:
    """True when `text`, exactly as read, is a registrable Indian plate."""
    s = normalise(text)
    if BH_PLATE_RE.match(s):
        return not SERIES_EXCLUDED.intersection(s[8:])
    m = _PLATE_PARTS_RE.match(s)
    if not m:
        return False
    state, district, series, _number = m.groups()
    if state not in STATE_CODES or SERIES_EXCLUDED.intersection(series):
        return False
    if state == "DL":
        return len(series) >= 1 and series[0] in DELHI_CATEGORIES
    return len(district) == 2
