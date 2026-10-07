from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image


GPS_SOURCES = {"exif", "gpx", "manual"}


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a coordinate")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("coordinate is not finite")
    return result


def dms_to_decimal(value: Any, reference: Any) -> float:
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError("GPS coordinate must contain degrees, minutes and seconds")
    degrees, minutes, seconds = (_number(part) for part in value)
    if degrees < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        raise ValueError("invalid DMS coordinate")
    if isinstance(reference, bytes):
        reference = reference.decode("ascii", errors="ignore")
    ref = str(reference or "").strip().upper()
    if ref not in {"N", "S", "E", "W"}:
        raise ValueError("invalid GPS reference")
    result = degrees + minutes / 60 + seconds / 3600
    return -result if ref in {"S", "W"} else result


def validate_gps(
    latitude: Any,
    longitude: Any,
    altitude: Any = None,
    source: Any = None,
) -> dict[str, float | str | None]:
    lat = _number(latitude)
    lon = _number(longitude)
    alt = None if altitude is None else _number(altitude)
    if not -90 <= lat <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= lon <= 180:
        raise ValueError("longitude must be between -180 and 180")
    if source is not None and source not in GPS_SOURCES:
        raise ValueError("invalid GPS source")
    return {
        "latitude": lat,
        "longitude": lon,
        "altitude": alt,
        "gps_source": source,
    }


def _gps_ifd(exif: Any) -> dict[int, Any]:
    try:
        return dict(exif.get_ifd(ExifTags.IFD.GPSInfo))
    except (AttributeError, KeyError, TypeError, ValueError):
        raw = exif.get(34853) if exif else None
        return dict(raw) if isinstance(raw, dict) else {}


def _captured_at(exif: Any) -> float | None:
    value = None
    offset = None
    try:
        exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
        value = exif_ifd.get(36867)
        offset = exif_ifd.get(36881)
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    value = value or (exif.get(36867) if exif else None) or (exif.get(306) if exif else None)
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="ignore")
    if isinstance(offset, bytes):
        offset = offset.decode("ascii", errors="ignore")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
        if isinstance(offset, str) and offset.strip():
            timezone = datetime.strptime(offset.strip(), "%z").tzinfo
            return parsed.replace(tzinfo=timezone).timestamp()
        # Older EXIF has no timezone field. Use the machine's local timezone.
        return parsed.astimezone().timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def read_photo_metadata(path: Path) -> dict[str, float | str | None]:
    result: dict[str, float | str | None] = {
        "latitude": None,
        "longitude": None,
        "altitude": None,
        "gps_source": None,
        "captured_at": None,
    }
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            result["captured_at"] = _captured_at(exif)
            gps = _gps_ifd(exif)
            if not gps:
                return result
            latitude = dms_to_decimal(gps.get(2), gps.get(1))
            longitude = dms_to_decimal(gps.get(4), gps.get(3))
            altitude = None
            if gps.get(6) is not None:
                altitude = _number(gps[6])
                altitude_ref = gps.get(5, 0)
                if isinstance(altitude_ref, bytes):
                    altitude_ref = altitude_ref[0] if altitude_ref else 0
                if int(altitude_ref) == 1:
                    altitude = -altitude
                elif int(altitude_ref) != 0:
                    raise ValueError("invalid altitude reference")
            validated = validate_gps(latitude, longitude, altitude, "exif")
            result.update(validated)
    except (OSError, SyntaxError, TypeError, ValueError, ZeroDivisionError):
        # Broken or incomplete metadata must never abort a media scan.
        pass
    return result

