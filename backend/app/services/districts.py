"""Nearest-centroid district approximation.

The registry does not persist a district field (see the build spec's gap
analysis inputs) and district boundary polygons are out of scope for this
build. As an approximation, each geocoded camera is assigned to its nearest
Gujarat district headquarters by straight-line distance. This is a coarse
stand-in for reverse geocoding or a real boundary lookup -- accurate enough
to say "several cameras near Junagadh, none near Dahod" but not a survey
grade district determination. State this limitation wherever the report is
presented.
"""

import math

# (district, lat, lon) for Gujarat's district headquarters -- approximate,
# public-knowledge coordinates, sufficient for nearest-centroid bucketing.
GUJARAT_DISTRICT_CENTROIDS = [
    ("Ahmedabad", 23.0225, 72.5714),
    ("Amreli", 21.6032, 71.2222),
    ("Anand", 22.5645, 72.9289),
    ("Aravalli", 23.2686, 73.0169),
    ("Banaskantha", 24.1719, 72.4386),
    ("Bharuch", 21.7051, 72.9959),
    ("Bhavnagar", 21.7645, 72.1519),
    ("Botad", 22.1704, 71.6683),
    ("Chhota Udaipur", 22.3, 74.0167),
    ("Dahod", 22.8344, 74.2593),
    ("Dang", 20.75, 73.6833),
    ("Devbhoomi Dwarka", 22.2394, 68.9678),
    ("Gandhinagar", 23.2156, 72.6369),
    ("Gir Somnath", 20.9, 70.4),
    ("Jamnagar", 22.4707, 70.0577),
    ("Junagadh", 21.5222, 70.4579),
    ("Kheda", 22.75, 72.6833),
    ("Kutch", 23.25, 69.6669),
    ("Mahisagar", 23.1667, 73.6167),
    ("Mehsana", 23.5880, 72.3693),
    ("Morbi", 22.8173, 70.8377),
    ("Narmada", 21.8791, 73.5),
    ("Navsari", 20.9467, 72.9520),
    ("Panchmahal", 22.7667, 73.6),
    ("Patan", 23.8493, 72.1266),
    ("Porbandar", 21.6417, 69.6293),
    ("Rajkot", 22.3039, 70.8022),
    ("Sabarkantha", 23.8333, 73.0),
    ("Surat", 21.1702, 72.8311),
    ("Surendranagar", 22.7469, 71.6483),
    ("Tapi", 21.1167, 73.4),
    ("Vadodara", 22.3072, 73.1812),
    ("Valsad", 20.5992, 72.9342),
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_district(lat: float, lon: float) -> str:
    return min(
        GUJARAT_DISTRICT_CENTROIDS,
        key=lambda entry: _haversine_km(lat, lon, entry[1], entry[2]),
    )[0]
