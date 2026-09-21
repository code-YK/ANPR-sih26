#!/usr/bin/env python3
"""Load a dense, Ahmedabad-local demo dataset for the operator console.

The rows are synthetic — no real person, vehicle, or government feed is
represented — but names, coordinates, plate formats, and traffic patterns
are chosen so the registry, GIS map, Journey, Alerts, Watchlist, and
maintenance views look like a working city deployment.

This command is database-only. It never contacts a camera, starts a worker,
or writes a stream URL. Investigate recordings and tracks are omitted
because those rows must point at a real uploaded file.

Run from ``backend`` after migrations::

    .venv\\Scripts\\python.exe scripts\\seed_ahmedabad_demo.py          # Windows
    .venv/bin/python scripts/seed_ahmedabad_demo.py                    # Linux

Re-running replaces only this script's rows. ``--reset`` removes them.
``--verify`` checks the loaded set without writing.

Journey plates worth searching after a load:

    GJ01AB1847   stolen vehicle, SG Highway southbound
    GJ01HX2291   weekday Chandkheda → CG Road commute
    GJ01BT1044   city-bus loop, east–central
    RJ14RS5521   out-of-state lookout entering via Sarkhej
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import async_session  # noqa: E402
from app.models.alert import Alert  # noqa: E402
from app.models.analytics_count import AnalyticsCount  # noqa: E402
from app.models.auth import AuditEvent, Department, RegistrationRequest  # noqa: E402
from app.models.camera import (  # noqa: E402
    Camera,
    CameraHealthObservation,
    CameraMaintenanceEvent,
    CameraMaintenanceWorkOrder,
    Sighting,
)
from app.models.subject import Subject  # noqa: E402
from app.models.watchlist import WatchlistEntry  # noqa: E402
from app.plate_format import normalise  # noqa: E402
from app.security import hash_password  # noqa: E402

_MARKER = "ahmedabad-seed-v1"
_CAMERA_PREFIX = "amd-seed-"
_WATCHLIST_SOURCE = _MARKER
_SEED_EMAIL_DOMAIN = "ahmedabad-seed.invalid"
_IST = timezone(timedelta(hours=5, minutes=30))

_DEPARTMENTS = ("Police", "Transport", "Municipal")


def _ist(days_ago: int, hour: int, minute: int, second: int = 0) -> datetime:
    local = datetime.now(_IST) - timedelta(days=days_ago)
    return datetime(local.year, local.month, local.day, hour, minute, second, tzinfo=_IST).astimezone(timezone.utc)


def _bbox(n: int) -> dict:
    return {
        "x": round(0.10 + (n % 8) * 0.07, 3),
        "y": round(0.30 + (n % 5) * 0.05, 3),
        "width": 0.20,
        "height": 0.09,
    }


def _cam(camera_id: str, camera_number: int, **overrides) -> dict:
    row = {
        "camera_id": camera_id,
        "camera_number": camera_number,
        "codec": "h264",
        "width": 1920,
        "height": 1080,
        "fps": 25.0,
        "bitrate_kbps": 1800,
        "transport_ok": "hls",
        "anpr_viable": True,
        "anpr_notes": "Lane-facing, daytime ANPR viable",
        "geocode_confidence": "exact",
        "ownership": "government",
        "camera_type": "fixed",
        "connectivity": "leased fibre",
        "storage_location": "AMC Traffic Cell, Paldi",
        "retention_days": 30,
        "metadata_confidence": "confirmed",
        "is_live": True,
        "health_reason": None,
        "analytics_enabled": False,
        "analytics_finetuned_enabled": False,
        "rtsp_url": None,
        "hls_url": None,
        "webrtc_url": None,
    }
    row.update(overrides)
    return row


# Real public-road coordinates around Ahmedabad. Camera IDs, names, and
# departments are synthetic; the points are the junctions they claim to cover.
_CAMERAS: list[dict] = [
    _cam(
        "amd-seed-01", 8101,
        name="Gota Cross Road",
        location_text="Gota Cross Road, S.G. Highway, Ahmedabad",
        latitude=23.1018, longitude=72.5406, department="Transport",
        storage_location="BRTS Control Room, Ranip", retention_days=45,
        last_surveyed_at=_ist(2, 11, 20),
    ),
    _cam(
        "amd-seed-02", 8102,
        name="Sola Bridge",
        location_text="Sola Bridge, Science City Road, Ahmedabad",
        latitude=23.0734, longitude=72.5196, department="Police",
        camera_type="ip", bitrate_kbps=2200,
        last_surveyed_at=_ist(4, 9, 40),
    ),
    _cam(
        "amd-seed-03", 8103,
        name="Thaltej Cross Road",
        location_text="Thaltej Cross Road, S.G. Highway, Ahmedabad",
        latitude=23.0488, longitude=72.5162, department="Police",
        last_surveyed_at=_ist(1, 16, 5),
    ),
    _cam(
        "amd-seed-04", 8104,
        name="ISKCON Flyover",
        location_text="ISKCON Flyover, S.G. Highway, Ahmedabad",
        latitude=23.0274, longitude=72.5076, department="Transport",
        storage_location="BRTS Control Room, Ranip",
        last_surveyed_at=_ist(1, 16, 12),
    ),
    _cam(
        "amd-seed-05", 8105,
        name="Prahladnagar Cross Road",
        location_text="Prahladnagar Cross Road, S.G. Highway, Ahmedabad",
        latitude=23.0116, longitude=72.5064, department="Police",
        camera_type="ip",
        last_surveyed_at=_ist(3, 10, 0),
    ),
    _cam(
        "amd-seed-06", 8106,
        name="Sarkhej Circle",
        location_text="Sarkhej Circle, S.G. Highway, Ahmedabad",
        latitude=22.9828, longitude=72.5014, department="Transport",
        last_surveyed_at=_ist(5, 8, 30),
    ),
    _cam(
        "amd-seed-07", 8107,
        name="Subhash Bridge",
        location_text="Subhash Bridge, Sabarmati, Ahmedabad",
        latitude=23.0624, longitude=72.5808, department="Police",
        storage_location="Police Commissionerate, Shahibaug", retention_days=90,
        last_surveyed_at=_ist(0, 7, 15),
    ),
    _cam(
        "amd-seed-08", 8108,
        name="Income Tax Circle",
        location_text="Income Tax Circle, Ashram Road, Ahmedabad",
        latitude=23.0402, longitude=72.5704, department="Police",
        camera_type="ptz", codec="h265", bitrate_kbps=1600,
        anpr_notes="PTZ; ANPR viable when locked to the southbound carriageway",
        last_surveyed_at=_ist(6, 14, 0),
    ),
    _cam(
        "amd-seed-09", 8109,
        name="C.G. Road, Navrangpura",
        location_text="C.G. Road at Municipal Market, Navrangpura, Ahmedabad",
        latitude=23.0306, longitude=72.5598, department="Municipal",
        last_surveyed_at=_ist(2, 19, 40),
    ),
    _cam(
        "amd-seed-10", 8110,
        name="Ellis Bridge",
        location_text="Ellis Bridge, Ashram Road, Ahmedabad",
        latitude=23.0226, longitude=72.5716, department="Police",
        camera_type="ip",
        last_surveyed_at=_ist(1, 12, 10),
    ),
    _cam(
        "amd-seed-11", 8111,
        name="Paldi Cross Road",
        location_text="Paldi Cross Road, Ahmedabad",
        latitude=23.0110, longitude=72.5630, department="Police",
        last_surveyed_at=_ist(8, 11, 0),
    ),
    _cam(
        "amd-seed-12", 8112,
        name="Lal Darwaja BRTS",
        location_text="Lal Darwaja BRTS station, Ahmedabad",
        latitude=23.0252, longitude=72.5812, department="Transport",
        storage_location="BRTS Control Room, Ranip",
        last_surveyed_at=_ist(0, 6, 50),
    ),
    _cam(
        "amd-seed-13", 8113,
        name="Kalupur Railway Approach",
        location_text="Kalupur Railway Station approach, Ahmedabad",
        latitude=23.0264, longitude=72.6014, department="Police",
        geocode_confidence="approximate",
        anpr_notes="Oblique view of the station approach; reads drop after dusk",
        storage_location="Police Commissionerate, Shahibaug", retention_days=90,
        last_surveyed_at=_ist(9, 17, 20),
    ),
    _cam(
        "amd-seed-14", 8114,
        name="Maninagar Cross Road",
        location_text="Maninagar Cross Road, Ahmedabad",
        latitude=22.9968, longitude=72.6034, department="Municipal",
        camera_type="ip",
        last_surveyed_at=_ist(3, 15, 0),
    ),
    _cam(
        "amd-seed-15", 8115,
        name="CTM Cross Road",
        location_text="CTM Cross Road, Ahmedabad",
        latitude=23.0032, longitude=72.6248, department="Transport",
        last_surveyed_at=_ist(2, 13, 25),
    ),
    _cam(
        "amd-seed-16", 8116,
        name="Nikol Canal Road",
        location_text="Nikol Canal Road junction, Ahmedabad",
        latitude=23.0472, longitude=72.6490, department="Police",
        last_surveyed_at=_ist(4, 10, 45),
    ),
    _cam(
        "amd-seed-17", 8117,
        name="Odhav GIDC Gate",
        location_text="Odhav GIDC main gate, Ahmedabad",
        latitude=23.0228, longitude=72.6615, department="Transport",
        camera_type="analog", codec="h264", width=720, height=576, fps=12.5,
        bitrate_kbps=600, transport_ok="none", anpr_viable=False,
        anpr_notes="Analog encoder, 4CIF; plate height below ANPR threshold",
        geocode_confidence="approximate", metadata_confidence="inferred",
        connectivity="municipal WAN", retention_days=7, is_live=False,
        health_reason="Last mile to the GIDC cabin has been down since last week",
        last_surveyed_at=_ist(12, 11, 0),
    ),
    _cam(
        "amd-seed-18", 8118,
        name="Naroda Patiya",
        location_text="Naroda Patiya junction, Ahmedabad",
        latitude=23.0688, longitude=72.6502, department="Police",
        last_surveyed_at=_ist(1, 9, 5),
    ),
    _cam(
        "amd-seed-19", 8119,
        name="Narol Circle",
        location_text="Narol Circle, National Highway 47, Ahmedabad",
        latitude=22.9618, longitude=72.5896, department="Transport",
        storage_location="RTO workshop, Subhash Bridge", retention_days=45,
        last_surveyed_at=_ist(0, 5, 40),
    ),
    _cam(
        "amd-seed-20", 8120,
        name="Vatva GIDC Crossing",
        location_text="Vatva GIDC Phase 4 crossing, Ahmedabad",
        latitude=22.9572, longitude=72.6318, department="Transport",
        camera_type="ip", codec="h265",
        last_surveyed_at=_ist(7, 18, 10),
    ),
    _cam(
        "amd-seed-21", 8121,
        name="Airport Approach, Hansol",
        location_text="Sardar Vallabhbhai Patel International Airport approach, Hansol, Ahmedabad",
        latitude=23.0774, longitude=72.6288, department="Police",
        camera_type="ptz", bitrate_kbps=2400, retention_days=90,
        storage_location="Police Commissionerate, Shahibaug",
        anpr_notes="PTZ on the arrivals approach; ANPR when zoomed to the lane",
        last_surveyed_at=_ist(2, 21, 0),
    ),
    _cam(
        "amd-seed-22", 8122,
        name="Motera Stadium Road",
        location_text="Motera Stadium Road, Ahmedabad",
        latitude=23.0920, longitude=72.5968, department="Municipal",
        last_surveyed_at=_ist(5, 12, 30),
    ),
    _cam(
        "amd-seed-23", 8123,
        name="Chandkheda BRTS",
        location_text="Chandkheda BRTS terminal, Ahmedabad",
        latitude=23.1104, longitude=72.5842, department="Transport",
        storage_location="BRTS Control Room, Ranip",
        last_surveyed_at=_ist(1, 7, 55),
    ),
    _cam(
        "amd-seed-24", 8124,
        name="Law Garden, Netaji Road",
        location_text="Law Garden, Netaji Road, Ahmedabad",
        latitude=23.0268, longitude=72.5594, department="Municipal",
        camera_type="ptz", transport_ok="none", anpr_viable=False, is_live=False,
        anpr_notes="Garden-facing PTZ; carriageway is outside the current preset",
        connectivity="4G backup", health_reason="PTZ housing seized; preset motor not responding",
        last_surveyed_at=_ist(3, 18, 0),
    ),
    _cam(
        "amd-seed-25", 8125,
        name="Jamalpur Darwaja",
        location_text="Jamalpur Darwaja, Ahmedabad",
        latitude=23.0105, longitude=72.5875, department="Police",
        camera_type="analog", width=1280, height=720, fps=15.0, bitrate_kbps=800,
        geocode_confidence="approximate", metadata_confidence="inferred",
        anpr_notes="Dust on the housing; reads are intermittent after 16:00 IST",
        connectivity="4G backup", retention_days=14,
        last_surveyed_at=_ist(11, 9, 20),
    ),
    _cam(
        "amd-seed-26", 8126,
        name="Danilimda stores yard",
        location_text="Municipal stores yard, Danilimda, Ahmedabad — not yet placed on the map",
        latitude=None, longitude=None, geocode_confidence="failed",
        department="Municipal", camera_type="fixed", transport_ok="none",
        anpr_viable=False, anpr_notes="Asset is in stores; no live view",
        metadata_confidence="inferred", is_live=False, connectivity="none",
        retention_days=7, health_reason="Camera is in the yard inventory, not mounted",
        last_surveyed_at=_ist(20, 10, 0),
    ),
    _cam(
        "amd-seed-27", 8127,
        name="Drive-in Road mall exit",
        location_text="Drive-in Road mall exit lane, Ahmedabad",
        latitude=23.0468, longitude=72.5312, department="Municipal",
        ownership="private", camera_type="ip", geocode_confidence="approximate",
        connectivity="mall LAN, municipal relay", retention_days=15,
        anpr_notes="Exit-lane camera shared under a municipal MoU",
        last_surveyed_at=_ist(6, 16, 45),
    ),
    _cam(
        "amd-seed-28", 8128,
        name="Bopal Approach, S.P. Ring Road",
        location_text="Bopal Approach, S.P. Ring Road, Ahmedabad",
        latitude=23.0308, longitude=72.4676, department="Police",
        last_surveyed_at=_ist(2, 8, 10),
    ),
]


_WATCHLIST: list[dict] = [
    {
        "raw_value": "GJ-01-AB-1847",
        "reason_code": "stolen-vehicle",
        "severity": "high",
        "active": True,
        "notes": "Reported stolen from a Thaltej society basement on 18 Sep. White SUV, last known west-side.",
    },
    {
        "raw_value": "GJ-01-CD-5520",
        "reason_code": "hit-and-run",
        "severity": "high",
        "active": True,
        "notes": "Ashram Road incident near Income Tax Circle, 16 Sep evening. Black sedan.",
    },
    {
        "raw_value": "GJ-27-EF-3318",
        "reason_code": "unpaid-challan",
        "severity": "medium",
        "active": True,
        "notes": "Ahmedabad East series. Twelve unpaid e-challans; RTO Subhash Bridge notice outstanding.",
    },
    {
        "raw_value": "GJ-01-GH-7742",
        "reason_code": "court-summons",
        "severity": "medium",
        "active": True,
        "notes": "Summons returnable at the Metropolitan Magistrate, Ghee Kanta.",
    },
    {
        "raw_value": "GJ-05-MN-2204",
        "reason_code": "interstate-lookout",
        "severity": "medium",
        "active": True,
        "notes": "Surat series goods carrier. Check at Narol / Vatva weighbridge approaches.",
    },
    {
        "raw_value": "RJ-14-RS-5521",
        "reason_code": "stolen-vehicle",
        "severity": "high",
        "active": True,
        "notes": "Lookout forwarded by Jaipur traffic. White car, likely entering via Sarkhej.",
    },
    {
        "raw_value": "MH-12-TU-8830",
        "reason_code": "permit-check",
        "severity": "low",
        "active": True,
        "notes": "Mumbai series. Airport taxi-stand contract-carriage permit query, not a stop order.",
    },
    {
        "raw_value": "GJ-01-JK-4409",
        "reason_code": "permit-check",
        "severity": "low",
        "active": True,
        "notes": "Contract-carriage permit, peak-hour corridor on S.G. Highway.",
    },
    {
        "raw_value": "GJ-18-PQ-9088",
        "reason_code": "cleared",
        "severity": "low",
        "active": False,
        "notes": "Gandhinagar series. Watch closed 12 Sep after recovery in Sector 21.",
    },
    {
        "raw_value": "KA-03-MN-5512",
        "reason_code": "interstate-lookout",
        "severity": "medium",
        "active": True,
        "notes": "Bengaluru series. Requested check if seen on the airport approach.",
    },
]


# Explicit story journeys: (plate_raw, vehicle_type, colour, days_ago, hour, minute, camera_id, confidence, raw_ocr or None)
_STORY_STOPS: list[tuple] = [
    # Stolen white SUV, S.G. Highway southbound this morning.
    ("GJ-01-AB-1847", "car", "white", 0, 7, 12, "amd-seed-01", 0.97, "GJ 01 AB 1847"),
    ("GJ-01-AB-1847", "car", "white", 0, 7, 24, "amd-seed-03", 0.94, "GJ01AB1847"),
    ("GJ-01-AB-1847", "car", "white", 0, 7, 33, "amd-seed-04", 0.98, "GJ-01-AB-1847"),
    ("GJ-01-AB-1847", "car", "white", 0, 7, 41, "amd-seed-05", 0.91, "GJ0IAB1847"),
    ("GJ-01-AB-1847", "car", "white", 0, 7, 54, "amd-seed-06", 0.62, "GJ01AB1847"),  # sub-threshold
    ("GJ-01-AB-1847", "car", "white", 1, 19, 8, "amd-seed-05", 0.93, "GJ-01-AB-1847"),
    # Hit-and-run black sedan, Ashram Road two evenings ago.
    ("GJ-01-CD-5520", "car", "black", 2, 19, 14, "amd-seed-07", 0.96, "GJ01CD5520"),
    ("GJ-01-CD-5520", "car", "black", 2, 19, 22, "amd-seed-08", 0.95, "GJ-01-CD-5520"),
    ("GJ-01-CD-5520", "car", "black", 2, 19, 31, "amd-seed-10", 0.92, "GJ01CD5520"),
    ("GJ-01-CD-5520", "car", "black", 2, 19, 40, "amd-seed-11", 0.88, "GJ01CD552O"),
    # Unpaid-challan, east side this afternoon.
    ("GJ-27-EF-3318", "car", "grey", 0, 14, 5, "amd-seed-16", 0.94, "GJ27EF3318"),
    ("GJ-27-EF-3318", "car", "grey", 0, 14, 18, "amd-seed-15", 0.90, "GJ-27-EF-3318"),
    ("GJ-27-EF-3318", "car", "grey", 0, 14, 36, "amd-seed-13", 0.87, "GJ27EF3318"),
    # Court summons, single Lal Darwaja sighting yesterday, later cleared.
    ("GJ-01-GH-7742", "car", "blue", 1, 11, 42, "amd-seed-12", 0.96, "GJ01GH7742"),
    # Surat truck, industrial south-east.
    ("GJ-05-MN-2204", "truck", "brown", 1, 5, 10, "amd-seed-19", 0.93, "GJ05MN2204"),
    ("GJ-05-MN-2204", "truck", "brown", 1, 5, 28, "amd-seed-20", 0.91, "GJ-05-MN-2204"),
    ("GJ-05-MN-2204", "truck", "brown", 0, 4, 52, "amd-seed-17", 0.72, "GJ05MN2204"),
    ("GJ-05-MN-2204", "truck", "brown", 0, 5, 18, "amd-seed-18", 0.89, "GJ05MN2204"),
    # Jaipur stolen car entering from Sarkhej toward the old city.
    ("RJ-14-RS-5521", "car", "white", 0, 9, 6, "amd-seed-06", 0.97, "RJ14RS5521"),
    ("RJ-14-RS-5521", "car", "white", 0, 9, 18, "amd-seed-05", 0.95, "RJ-14-RS-5521"),
    ("RJ-14-RS-5521", "car", "white", 0, 9, 41, "amd-seed-11", 0.92, "RJ14RS5521"),
    ("RJ-14-RS-5521", "car", "white", 0, 9, 58, "amd-seed-13", 0.88, "RJ14R55521"),
    # Mumbai permit-check, airport northbound yesterday.
    ("MH-12-TU-8830", "car", "white", 1, 16, 4, "amd-seed-21", 0.94, "MH12TU8830"),
    ("MH-12-TU-8830", "car", "white", 1, 16, 22, "amd-seed-22", 0.91, "MH-12-TU-8830"),
    ("MH-12-TU-8830", "car", "white", 1, 16, 38, "amd-seed-23", 0.90, "MH12TU8830"),
    # Contract carriage on S.G. Highway, mid-morning.
    ("GJ-01-JK-4409", "bus", "yellow", 0, 8, 5, "amd-seed-03", 0.93, "GJ01JK4409"),
    ("GJ-01-JK-4409", "bus", "yellow", 0, 8, 14, "amd-seed-04", 0.95, "GJ-01-JK-4409"),
    ("GJ-01-JK-4409", "bus", "yellow", 0, 8, 26, "amd-seed-05", 0.86, "GJ01JK4409"),
    # Inactive / cleared plate, historical only.
    ("GJ-18-PQ-9088", "car", "silver", 9, 13, 20, "amd-seed-01", 0.92, "GJ18PQ9088"),
    # Bengaluru lookout, airport this morning, then Motera.
    ("KA-03-MN-5512", "car", "black", 0, 10, 44, "amd-seed-21", 0.96, "KA03MN5512"),
    ("KA-03-MN-5512", "car", "black", 0, 11, 2, "amd-seed-22", 0.90, "KA-03-MN-5512"),
    # City-bus loop.
    ("GJ-01-BT-1044", "bus", "blue", 0, 7, 50, "amd-seed-14", 0.94, "GJ01BT1044"),
    ("GJ-01-BT-1044", "bus", "blue", 0, 8, 6, "amd-seed-15", 0.91, "GJ-01-BT-1044"),
    ("GJ-01-BT-1044", "bus", "blue", 0, 8, 22, "amd-seed-13", 0.89, "GJ01BT1044"),
    ("GJ-01-BT-1044", "bus", "blue", 0, 8, 35, "amd-seed-12", 0.93, "GJ01BT1044"),
    ("GJ-01-BT-1044", "bus", "blue", 0, 8, 48, "amd-seed-11", 0.88, "GJ01BT1044"),
    ("GJ-01-BT-1044", "bus", "blue", 0, 17, 10, "amd-seed-11", 0.90, "GJ01BT1044"),
    ("GJ-01-BT-1044", "bus", "blue", 0, 17, 24, "amd-seed-12", 0.94, "GJ-01-BT-1044"),
    ("GJ-01-BT-1044", "bus", "blue", 0, 17, 40, "amd-seed-13", 0.87, "GJ01BT1044"),
    ("GJ-01-BT-1044", "bus", "blue", 0, 17, 55, "amd-seed-14", 0.92, "GJ01BT1044"),
]


_COMMUTERS = [
    {
        "raw": "GJ-01-HX-2291",
        "vehicle_type": "car",
        "colour": "white",
        "morning": [
            ("amd-seed-23", 8, 12, 0.97),
            ("amd-seed-22", 8, 21, 0.95),
            ("amd-seed-07", 8, 33, 0.96),
            ("amd-seed-08", 8, 48, 0.93),
            ("amd-seed-09", 8, 57, 0.94),
        ],
        "evening": [
            ("amd-seed-09", 18, 22, 0.92),
            ("amd-seed-08", 18, 31, 0.90),
            ("amd-seed-07", 18, 44, 0.94),
            ("amd-seed-23", 19, 5, 0.96),
        ],
        "days": (0, 1, 2),
    },
    {
        "raw": "GJ-01-KL-8834",
        "vehicle_type": "car",
        "colour": "silver",
        "morning": [
            ("amd-seed-28", 8, 40, 0.95),
            ("amd-seed-05", 8, 55, 0.92),
            ("amd-seed-04", 9, 4, 0.94),
            ("amd-seed-27", 9, 18, 0.88),
        ],
        "evening": [
            ("amd-seed-27", 18, 50, 0.90),
            ("amd-seed-04", 19, 4, 0.93),
            ("amd-seed-28", 19, 22, 0.91),
        ],
        "days": (0, 1),
    },
    {
        "raw": "GJ-27-NP-4410",
        "vehicle_type": "motorcycle",
        "colour": "red",
        "morning": [
            ("amd-seed-16", 9, 5, 0.86),
            ("amd-seed-18", 9, 18, 0.84),
        ],
        "evening": [
            ("amd-seed-18", 19, 40, 0.82),
            ("amd-seed-16", 19, 52, 0.85),
        ],
        "days": (0, 1, 3),
    },
    {
        "raw": "GJ-01-QR-6721",
        "vehicle_type": "car",
        "colour": "grey",
        "morning": [
            ("amd-seed-27", 11, 10, 0.93),
            ("amd-seed-09", 11, 28, 0.91),
            ("amd-seed-10", 11, 40, 0.89),
        ],
        "evening": [
            ("amd-seed-09", 20, 15, 0.90),
            ("amd-seed-27", 20, 34, 0.88),
        ],
        "days": (0,),
    },
    {
        "raw": "BH-23-AA-1024",
        "vehicle_type": "car",
        "colour": "white",
        "morning": [
            ("amd-seed-19", 6, 40, 0.95),
            ("amd-seed-11", 7, 5, 0.92),
            ("amd-seed-10", 7, 14, 0.94),
            ("amd-seed-08", 7, 22, 0.90),
        ],
        "evening": [],
        "days": (0, 2),
    },
]


_BACKGROUND: list[tuple] = [
    ("GJ-01-UV-5560", "truck", "white", 0, 3, 12, "amd-seed-20", 0.91, "GJ01UV5560"),
    ("GJ-01-UV-5560", "truck", "white", 0, 3, 31, "amd-seed-19", 0.88, "GJ-01-UV-5560"),
    ("GJ-01-UV-5560", "truck", "white", 0, 3, 58, "amd-seed-06", 0.86, "GJ01UV5560"),
    ("GJ-06-WD-2194", "car", "blue", 0, 12, 8, "amd-seed-21", 0.94, "GJ06WD2194"),
    ("GJ-06-WD-2194", "car", "blue", 0, 12, 26, "amd-seed-07", 0.90, "GJ-06-WD-2194"),
    ("GJ-03-YX-7702", "car", "silver", 1, 15, 44, "amd-seed-06", 0.93, "GJ03YX7702"),
    ("MP-09-CD-3344", "truck", "brown", 1, 2, 18, "amd-seed-19", 0.87, "MP09CD3344"),
    ("MP-09-CD-3344", "truck", "brown", 1, 2, 40, "amd-seed-20", 0.84, "MP-09-CD-3344"),
    ("GJ-01-SA-1180", "motorcycle", "black", 0, 13, 5, "amd-seed-09", 0.79, "GJ01SA1180"),
    ("GJ-01-SA-1180", "motorcycle", "black", 0, 13, 22, "amd-seed-24", 0.51, "GJ0ISA1180"),  # sub-threshold
    ("GJ-01-ZA-9021", "car", "red", 0, 16, 10, "amd-seed-14", 0.92, "GJ01ZA9021"),
    ("GJ-01-ZA-9021", "car", "red", 0, 16, 28, "amd-seed-15", 0.88, "GJ-01-ZA-9021"),
    ("GJ-27-LM-6603", "car", "white", 2, 10, 2, "amd-seed-16", 0.91, "GJ27LM6603"),
    ("GJ-01-FC-3340", "car", "grey", 0, 18, 8, "amd-seed-04", 0.95, "GJ01FC3340"),
    ("GJ-01-FC-3340", "car", "grey", 0, 18, 19, "amd-seed-03", 0.93, "GJ01FC3340"),
    ("GJ-01-FC-3340", "car", "grey", 0, 18, 33, "amd-seed-02", 0.90, "GJ-01-FC-3340"),
    ("DL7CA1234", "car", "black", 0, 21, 15, "amd-seed-21", 0.89, "DL7CA1234"),
    ("GJ011284", "car", "white", 3, 9, 40, "amd-seed-10", 0.77, "GJ011284"),
    ("GJ-01-HX-2291", "car", "white", 0, 12, 14, "amd-seed-11", 0.51, "GJ01HX229I"),  # sub-threshold lunch detour
]


def _camera_ids() -> list[str]:
    return [row["camera_id"] for row in _CAMERAS]


def _with_geog(camera: dict) -> dict:
    values = dict(camera)
    lat, lon = values.get("latitude"), values.get("longitude")
    if lat is not None and lon is not None:
        values["geog"] = WKTElement(f"POINT({lon} {lat})", srid=4326)
    else:
        values["geog"] = None
    return values


def _sighting(
    *,
    camera_id: str,
    seen_at: datetime,
    raw_plate: str,
    vehicle_type: str,
    colour: str,
    confidence: float,
    raw_ocr: str | None,
    index: int,
    epoch_id: int = 1,
) -> Sighting:
    plate = normalise(raw_plate)
    return Sighting(
        camera_id=camera_id,
        seen_at=seen_at,
        plate=plate,
        vehicle_type=vehicle_type,
        vehicle_colour=colour,
        confidence=confidence,
        frame_pts_ms=int(seen_at.timestamp() * 1000) % 3_600_000 + index * 17,
        epoch_id=epoch_id,
        raw_ocr_text=raw_ocr or raw_plate,
        bbox=_bbox(index),
        model_version=_MARKER,
    )


def _all_sighting_specs() -> list[tuple]:
    rows: list[tuple] = list(_STORY_STOPS)
    rows.extend(_BACKGROUND)
    for commuter in _COMMUTERS:
        for day in commuter["days"]:
            for camera_id, hour, minute, confidence in commuter["morning"]:
                rows.append(
                    (commuter["raw"], commuter["vehicle_type"], commuter["colour"], day, hour, minute, camera_id, confidence, commuter["raw"])
                )
            if day in (0, 1):
                for camera_id, hour, minute, confidence in commuter["evening"]:
                    rows.append(
                        (commuter["raw"], commuter["vehicle_type"], commuter["colour"], day, hour, minute, camera_id, confidence, commuter["raw"])
                    )
    return rows


async def reset_seed_data() -> None:
    camera_ids = _camera_ids()
    async with async_session() as session:
        await session.execute(delete(Alert).where(Alert.camera_id.in_(camera_ids)))
        await session.execute(delete(Alert).where(Alert.dedup_key.like(f"{_MARKER}:%")))
        await session.execute(delete(Sighting).where(Sighting.model_version == _MARKER))
        await session.execute(delete(Sighting).where(Sighting.camera_id.in_(camera_ids)))
        await session.execute(delete(AnalyticsCount).where(AnalyticsCount.camera_id.in_(camera_ids)))
        order_ids = list(
            (await session.execute(
                select(CameraMaintenanceWorkOrder.id).where(CameraMaintenanceWorkOrder.camera_id.in_(camera_ids))
            )).scalars()
        )
        if order_ids:
            await session.execute(delete(CameraMaintenanceEvent).where(CameraMaintenanceEvent.work_order_id.in_(order_ids)))
            await session.execute(delete(CameraMaintenanceWorkOrder).where(CameraMaintenanceWorkOrder.id.in_(order_ids)))
        await session.execute(delete(CameraHealthObservation).where(CameraHealthObservation.source == _MARKER))
        await session.execute(delete(CameraHealthObservation).where(CameraHealthObservation.camera_id.in_(camera_ids)))
        await session.execute(delete(Subject).where(Subject.notes.like(f"[{_MARKER}]%")))
        await session.execute(delete(WatchlistEntry).where(WatchlistEntry.source == _WATCHLIST_SOURCE))
        await session.execute(delete(AuditEvent).where(AuditEvent.actor_email.like(f"%@{_SEED_EMAIL_DOMAIN}")))
        await session.execute(delete(AuditEvent).where(AuditEvent.action.like(f"{_MARKER}.%")))
        await session.execute(delete(RegistrationRequest).where(RegistrationRequest.email.like(f"%@{_SEED_EMAIL_DOMAIN}")))
        await session.execute(delete(Camera).where(Camera.camera_id.like(f"{_CAMERA_PREFIX}%")))
        await session.commit()


def _stamp_connect_times(cameras: list[dict], now: datetime) -> None:
    for camera in cameras:
        if camera["is_live"]:
            camera["last_successful_connect"] = now - timedelta(minutes=2 + (camera["camera_number"] % 11))
        elif camera["camera_id"] == "amd-seed-17":
            camera["last_successful_connect"] = now - timedelta(days=6, hours=4)
        elif camera["camera_id"] == "amd-seed-24":
            camera["last_successful_connect"] = now - timedelta(days=2, hours=7)
        else:
            camera["last_successful_connect"] = None


async def seed_demo_data() -> None:
    await reset_seed_data()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cameras = [dict(row) for row in _CAMERAS]
    _stamp_connect_times(cameras, now)

    async with async_session() as session:
        for name in _DEPARTMENTS:
            if await session.get(Department, name) is None:
                session.add(Department(name=name))
        await session.flush()

        session.add_all(Camera(**_with_geog(row)) for row in cameras)
        await session.flush()

        watchlist_rows: list[WatchlistEntry] = []
        for item in _WATCHLIST:
            watchlist_rows.append(
                WatchlistEntry(
                    raw_value=item["raw_value"],
                    normalised_value=normalise(item["raw_value"]),
                    reason_code=item["reason_code"],
                    severity=item["severity"],
                    notes=item["notes"],
                    source=_WATCHLIST_SOURCE,
                    active=item["active"],
                )
            )
        session.add_all(watchlist_rows)
        await session.flush()
        watchlist_by_plate = {entry.normalised_value: entry for entry in watchlist_rows}

        sightings: list[Sighting] = []
        for index, spec in enumerate(_all_sighting_specs()):
            raw_plate, vehicle_type, colour, days_ago, hour, minute, camera_id, confidence, raw_ocr = spec
            epoch_id = 2 if camera_id == "amd-seed-25" and days_ago == 0 else 1
            sightings.append(
                _sighting(
                    camera_id=camera_id,
                    seen_at=_ist(days_ago, hour, minute, second=index % 50),
                    raw_plate=raw_plate,
                    vehicle_type=vehicle_type,
                    colour=colour,
                    confidence=confidence,
                    raw_ocr=raw_ocr,
                    index=index,
                    epoch_id=epoch_id,
                )
            )
        session.add_all(sightings)
        await session.flush()

        def _latest_alertable(plate_raw: str) -> Sighting:
            key = normalise(plate_raw)
            candidates = [
                row for row in sightings
                if row.plate == key and row.confidence is not None and float(row.confidence) >= 0.85
            ]
            return max(candidates, key=lambda row: row.seen_at)

        alerts: list[Alert] = []

        def _add_watchlist_alert(plate_raw: str, status: str, sighting: Sighting, *, ack: datetime | None = None, resolved: datetime | None = None) -> None:
            entry = watchlist_by_plate[normalise(plate_raw)]
            alerts.append(
                Alert(
                    sighting_id=sighting.id,
                    watchlist_entry_id=entry.id,
                    camera_id=sighting.camera_id,
                    event_time=sighting.seen_at,
                    match_confidence=sighting.confidence,
                    dedup_key=f"{entry.normalised_value}:{entry.id}",
                    status=status,
                    acknowledged_at=ack,
                    resolved_at=resolved,
                )
            )

        stolen = _latest_alertable("GJ-01-AB-1847")
        _add_watchlist_alert("GJ-01-AB-1847", "open", stolen)

        hit = _latest_alertable("GJ-01-CD-5520")
        _add_watchlist_alert("GJ-01-CD-5520", "acknowledged", hit, ack=hit.seen_at + timedelta(hours=2))

        challan = _latest_alertable("GJ-27-EF-3318")
        _add_watchlist_alert("GJ-27-EF-3318", "open", challan)

        summons = _latest_alertable("GJ-01-GH-7742")
        _add_watchlist_alert("GJ-01-GH-7742", "resolved", summons, ack=summons.seen_at + timedelta(minutes=40), resolved=summons.seen_at + timedelta(hours=3))

        truck = _latest_alertable("GJ-05-MN-2204")
        _add_watchlist_alert("GJ-05-MN-2204", "open", truck)

        jaipur = _latest_alertable("RJ-14-RS-5521")
        _add_watchlist_alert("RJ-14-RS-5521", "open", jaipur)

        mumbai = _latest_alertable("MH-12-TU-8830")
        _add_watchlist_alert("MH-12-TU-8830", "resolved", mumbai, resolved=mumbai.seen_at + timedelta(hours=5))

        carriage = _latest_alertable("GJ-01-JK-4409")
        _add_watchlist_alert("GJ-01-JK-4409", "acknowledged", carriage, ack=carriage.seen_at + timedelta(minutes=25))

        bengaluru = _latest_alertable("KA-03-MN-5512")
        _add_watchlist_alert("KA-03-MN-5512", "open", bengaluru)

        yesterday_stolen = next(
            row for row in sightings
            if row.plate == normalise("GJ-01-AB-1847") and row.camera_id == "amd-seed-05" and row.seen_at < stolen.seen_at
        )
        _add_watchlist_alert(
            "GJ-01-AB-1847",
            "resolved",
            yesterday_stolen,
            ack=yesterday_stolen.seen_at + timedelta(minutes=50),
            resolved=yesterday_stolen.seen_at + timedelta(hours=4),
        )

        alerts.extend(
            [
                Alert(
                    camera_id="amd-seed-24",
                    alert_type="suspicious",
                    label="Potentially dangerous person",
                    severity="high",
                    event_time=_ist(0, 21, 18),
                    match_confidence=0.91,
                    dedup_key=f"{_MARKER}:suspicious:amd-seed-24:14",
                    status="open",
                ),
                Alert(
                    camera_id="amd-seed-13",
                    alert_type="suspicious",
                    label="Potentially dangerous person",
                    severity="high",
                    event_time=_ist(1, 22, 4),
                    match_confidence=0.88,
                    dedup_key=f"{_MARKER}:suspicious:amd-seed-13:7",
                    status="acknowledged",
                    acknowledged_at=_ist(1, 22, 40),
                ),
                Alert(
                    camera_id="amd-seed-19",
                    alert_type="suspicious",
                    label="Potentially dangerous person",
                    severity="high",
                    event_time=_ist(2, 1, 12),
                    match_confidence=0.84,
                    dedup_key=f"{_MARKER}:suspicious:amd-seed-19:3",
                    status="resolved",
                    acknowledged_at=_ist(2, 1, 40),
                    resolved_at=_ist(2, 3, 5),
                ),
                Alert(
                    camera_id="amd-seed-25",
                    alert_type="suspicious",
                    label="Potentially dangerous person",
                    severity="high",
                    event_time=_ist(0, 18, 47),
                    match_confidence=0.79,
                    dedup_key=f"{_MARKER}:suspicious:amd-seed-25:21",
                    status="open",
                ),
            ]
        )
        session.add_all(alerts)

        busy = ("amd-seed-04", "amd-seed-09", "amd-seed-12", "amd-seed-13", "amd-seed-19", "amd-seed-21")
        counts: list[AnalyticsCount] = []
        for camera_id in busy:
            for step in range(18):
                window_end = now - timedelta(minutes=5 * step)
                window_start = window_end - timedelta(minutes=5)
                hour = window_end.astimezone(_IST).hour
                if 8 <= hour <= 10 or 17 <= hour <= 20:
                    unique, peak = 24 + (step % 9), 10 + (step % 6)
                elif 0 <= hour <= 5:
                    unique, peak = 2 + (step % 3), 1 + (step % 2)
                else:
                    unique, peak = 11 + (step % 7), 4 + (step % 4)
                counts.append(
                    AnalyticsCount(
                        camera_id=camera_id,
                        mode="person",
                        window_start=window_start,
                        window_end=window_end,
                        unique_tracks=unique,
                        peak_concurrent=min(peak, unique),
                    )
                )
        session.add_all(counts)

        health: list[CameraHealthObservation] = []
        for camera in cameras:
            if camera["is_live"]:
                health.append(
                    CameraHealthObservation(
                        camera_id=camera["camera_id"],
                        observed_at=now - timedelta(minutes=3),
                        status="healthy",
                        source=_MARKER,
                        transport_ok=camera["transport_ok"] if camera["transport_ok"] != "none" else "hls",
                        is_live=True,
                        reason="Probe: stream available",
                    )
                )
            else:
                health.append(
                    CameraHealthObservation(
                        camera_id=camera["camera_id"],
                        observed_at=now - timedelta(minutes=8),
                        status="offline",
                        source=_MARKER,
                        transport_ok="none",
                        is_live=False,
                        reason=camera["health_reason"] or "Probe: endpoint unavailable",
                    )
                )
        health.extend(
            [
                CameraHealthObservation(
                    camera_id="amd-seed-24", observed_at=now - timedelta(hours=30), status="healthy",
                    source=_MARKER, transport_ok="hls", is_live=True, reason="Probe: stream available",
                ),
                CameraHealthObservation(
                    camera_id="amd-seed-24", observed_at=now - timedelta(hours=26), status="offline",
                    source=_MARKER, transport_ok="none", is_live=False, reason="PTZ preset motor timeout",
                ),
                CameraHealthObservation(
                    camera_id="amd-seed-08", observed_at=now - timedelta(hours=6), status="offline",
                    source=_MARKER, transport_ok="none", is_live=False, reason="Short fibre cut on Ashram Road",
                ),
                CameraHealthObservation(
                    camera_id="amd-seed-08", observed_at=now - timedelta(hours=4), status="healthy",
                    source=_MARKER, transport_ok="rtsp", is_live=True, reason="Link restored; PTZ reachable",
                ),
                CameraHealthObservation(
                    camera_id="amd-seed-17", observed_at=now - timedelta(days=6), status="healthy",
                    source=_MARKER, transport_ok="hls", is_live=True, reason="Probe: stream available",
                ),
            ]
        )
        session.add_all(health)

        orders = [
            CameraMaintenanceWorkOrder(
                camera_id="amd-seed-24",
                summary="PTZ housing seized on Netaji Road / Law Garden — restore garden and carriageway presets",
                status="in_progress",
                opened_at=_ist(3, 18, 20),
            ),
            CameraMaintenanceWorkOrder(
                camera_id="amd-seed-17",
                summary="Restore last-mile link to Odhav GIDC cabin encoder",
                status="open",
                opened_at=_ist(6, 10, 0),
            ),
            CameraMaintenanceWorkOrder(
                camera_id="amd-seed-19",
                summary="Replace IR array at Narol Circle for night coverage",
                status="resolved",
                opened_at=_ist(10, 9, 0),
                closed_at=_ist(8, 16, 30),
            ),
            CameraMaintenanceWorkOrder(
                camera_id="amd-seed-26",
                summary="Mount the Danilimda yard spare at the assigned Paldi pole",
                status="cancelled",
                opened_at=_ist(15, 11, 0),
                closed_at=_ist(14, 12, 0),
            ),
        ]
        session.add_all(orders)
        await session.flush()

        session.add_all(
            [
                CameraMaintenanceEvent(work_order_id=orders[0].id, occurred_at=_ist(3, 18, 20), event_type="created", status="open", note="Opened after the evening health probe."),
                CameraMaintenanceEvent(work_order_id=orders[0].id, occurred_at=_ist(2, 9, 10), event_type="status_changed", status="in_progress", note="Field team assigned from Paldi workshop."),
                CameraMaintenanceEvent(work_order_id=orders[0].id, occurred_at=_ist(1, 15, 40), event_type="note_added", status="in_progress", note="Housing bolts seized; waiting on a replacement yoke."),
                CameraMaintenanceEvent(work_order_id=orders[1].id, occurred_at=_ist(6, 10, 0), event_type="created", status="open", note="GIDC cabin reports no encoder power."),
                CameraMaintenanceEvent(work_order_id=orders[2].id, occurred_at=_ist(10, 9, 0), event_type="created", status="open", note="Night reads falling on the NH-47 approach."),
                CameraMaintenanceEvent(work_order_id=orders[2].id, occurred_at=_ist(9, 14, 0), event_type="status_changed", status="in_progress", note="IR array swapped."),
                CameraMaintenanceEvent(work_order_id=orders[2].id, occurred_at=_ist(8, 16, 30), event_type="status_changed", status="resolved", note="Night probe confirmed illumination on both lanes."),
                CameraMaintenanceEvent(work_order_id=orders[3].id, occurred_at=_ist(15, 11, 0), event_type="created", status="open", note="Stores-yard spare listed against a Paldi pole."),
                CameraMaintenanceEvent(work_order_id=orders[3].id, occurred_at=_ist(14, 12, 0), event_type="status_changed", status="cancelled", note="Pole already has a live camera; ticket was a duplicate."),
            ]
        )

        session.add_all(
            [
                Subject(kind="vehicle", label="White SUV, S.G. Highway corridor", plate=normalise("GJ-01-AB-1847"), notes=f"[{_MARKER}] Stolen-vehicle watch, Thaltej to Sarkhej."),
                Subject(kind="vehicle", label="Surat series goods carrier", plate=normalise("GJ-05-MN-2204"), notes=f"[{_MARKER}] Interstate lookout, Narol–Vatva–Odhav."),
                Subject(kind="person", label="Unidentified person, Law Garden PTZ", plate=None, notes=f"[{_MARKER}] Raised from a suspicious-activity alert; no identification attached."),
            ]
        )

        session.add_all(
            [
                RegistrationRequest(
                    full_name="Kiran Joshi",
                    email=f"kiran.joshi@{_SEED_EMAIL_DOMAIN}",
                    password_hash=hash_password(secrets.token_urlsafe(24)),
                    requested_department="Municipal",
                    requested_role="department_user",
                    status="pending",
                ),
                RegistrationRequest(
                    full_name="Farhan Qureshi",
                    email=f"farhan.qureshi@{_SEED_EMAIL_DOMAIN}",
                    password_hash=hash_password(secrets.token_urlsafe(24)),
                    requested_department="Police",
                    requested_role="department_user",
                    status="rejected",
                    reviewed_at=_ist(4, 12, 0),
                    rejection_reason="Home department could not be verified against the staff roll.",
                ),
                RegistrationRequest(
                    full_name="Nisha Mehta",
                    email=f"nisha.mehta@{_SEED_EMAIL_DOMAIN}",
                    password_hash=hash_password(secrets.token_urlsafe(24)),
                    requested_department="Transport",
                    requested_role="department_admin",
                    status="approved",
                    reviewed_at=_ist(8, 10, 30),
                ),
            ]
        )

        session.add(
            AuditEvent(
                actor_email=f"seed@{_SEED_EMAIL_DOMAIN}",
                action=f"{_MARKER}.loaded",
                target_type="demo_dataset",
                target_id=_MARKER,
                result="success",
                details={
                    "cameras": len(cameras),
                    "sightings": len(sightings),
                    "alerts": len(alerts),
                    "watchlist": len(watchlist_rows),
                },
                occurred_at=now,
            )
        )
        session.add(
            AuditEvent(
                actor_email=f"operator@{_SEED_EMAIL_DOMAIN}",
                action="alert.acknowledged",
                target_type="alert",
                target_id="seed",
                department="Police",
                result="success",
                details={"seed": _MARKER, "plate": normalise("GJ-01-CD-5520")},
                occurred_at=hit.seen_at + timedelta(hours=2),
            )
        )
        session.add(
            AuditEvent(
                actor_email=f"operator@{_SEED_EMAIL_DOMAIN}",
                action="camera_maintenance.created",
                target_type="camera",
                target_id="amd-seed-24",
                department="Municipal",
                result="success",
                details={"seed": _MARKER},
                occurred_at=_ist(3, 18, 20),
            )
        )
        await session.commit()

    print(
        f"Loaded Ahmedabad seed: {len(cameras)} cameras, {len(sightings)} sightings, "
        f"{len(alerts)} alerts, {len(watchlist_rows)} watchlist entries."
    )
    print("Journey plates: GJ01AB1847  GJ01HX2291  GJ01BT1044  RJ14RS5521")
    print("Rows are namespaced amd-seed-* / ahmedabad-seed-v1. Use --reset to remove them.")


async def verify_demo_data() -> None:
    camera_ids = set(_camera_ids())
    async with async_session() as session:
        cameras = (await session.execute(select(Camera).where(Camera.camera_id.like(f"{_CAMERA_PREFIX}%")))).scalars().all()
        sightings = (await session.execute(select(Sighting).where(Sighting.model_version == _MARKER))).scalars().all()
        alerts = (await session.execute(select(Alert).where(Alert.camera_id.in_(camera_ids)))).scalars().all()
        watchlist = (await session.execute(select(WatchlistEntry).where(WatchlistEntry.source == _WATCHLIST_SOURCE))).scalars().all()
        health = (await session.execute(select(CameraHealthObservation).where(CameraHealthObservation.source == _MARKER))).scalars().all()
        orders = (await session.execute(select(CameraMaintenanceWorkOrder).where(CameraMaintenanceWorkOrder.camera_id.in_(camera_ids)))).scalars().all()
        counts = (await session.execute(select(AnalyticsCount).where(AnalyticsCount.camera_id.in_(camera_ids)))).scalars().all()
        subjects = (await session.execute(select(Subject).where(Subject.notes.like(f"[{_MARKER}]%")))).scalars().all()

    errors: list[str] = []
    if {c.camera_id for c in cameras} != camera_ids:
        errors.append("camera IDs are missing or duplicated")
    if any(c.rtsp_url or c.hls_url or c.webrtc_url for c in cameras):
        errors.append("seed camera exposes a source endpoint")
    if len(sightings) < 80:
        errors.append(f"expected at least 80 sightings, found {len(sightings)}")
    if {a.status for a in alerts} != {"open", "acknowledged", "resolved"}:
        errors.append("alerts do not cover every status")
    if {a.alert_type for a in alerts} != {"watchlist", "suspicious"}:
        errors.append("alerts do not cover both types")
    if len(watchlist) != len(_WATCHLIST):
        errors.append("watchlist count mismatch")
    if not any(e.active is False for e in watchlist):
        errors.append("expected an inactive watchlist entry")
    if len(health) < len(_CAMERAS):
        errors.append("health observations missing")
    if {o.status for o in orders} != {"open", "in_progress", "resolved", "cancelled"}:
        errors.append("maintenance statuses incomplete")
    if len(counts) < 18:
        errors.append("analytics counts missing")
    if len(subjects) != 3:
        errors.append("subjects missing")
    unplaced = [c for c in cameras if c.latitude is None]
    if len(unplaced) != 1:
        errors.append("expected exactly one unplaced camera")
    if errors:
        raise RuntimeError("Ahmedabad seed verification failed: " + "; ".join(errors))
    print(
        f"Verified Ahmedabad seed: {len(cameras)} cameras, {len(sightings)} sightings, "
        f"{len(alerts)} alerts, {len(watchlist)} watchlist entries, {len(health)} health rows, "
        f"{len(orders)} work orders, {len(counts)} person-count windows."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Load synthetic Ahmedabad-local rows for the operator console")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--reset", action="store_true", help="Remove only rows managed by this seed")
    action.add_argument("--verify", action="store_true", help="Verify the Ahmedabad seed rows")
    args = parser.parse_args()
    async def _seed_and_verify() -> None:
        await seed_demo_data()
        await verify_demo_data()

    if args.reset:
        asyncio.run(reset_seed_data())
        print("Removed Ahmedabad seed rows.")
    elif args.verify:
        asyncio.run(verify_demo_data())
    else:
        asyncio.run(_seed_and_verify())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
