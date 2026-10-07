from __future__ import annotations

import math
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO


MAX_GPX_FILE_SIZE = 10 * 1024 * 1024
MAX_GPX_POINTS = 100_000
_FORBIDDEN_XML = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


class GpxError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class GpxPoint:
    sequence: int
    latitude: float
    longitude: float
    elevation: float | None
    recorded_at: float | None


@dataclass(frozen=True)
class ParsedGpx:
    name: str | None
    points: list[GpxPoint]


def import_track(
    conn: sqlite3.Connection,
    parsed: ParsedGpx,
    original_filename: str,
    project_id: int | None,
) -> dict:
    cursor = conn.execute(
        """
        INSERT INTO gpx_tracks
        (name, project_id, original_filename, imported_at, point_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            parsed.name or Path(original_filename).stem or "GPX-Track",
            project_id,
            original_filename,
            time.time(),
            len(parsed.points),
        ),
    )
    track_id = int(cursor.lastrowid)
    conn.executemany(
        """
        INSERT INTO gpx_points
        (track_id, sequence, latitude, longitude, elevation, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                track_id,
                point.sequence,
                point.latitude,
                point.longitude,
                point.elevation,
                point.recorded_at,
            )
            for point in parsed.points
        ],
    )
    return dict(
        conn.execute(
            """
            SELECT id, name, project_id, original_filename, imported_at, point_count
            FROM gpx_tracks WHERE id = ?
            """,
            (track_id,),
        ).fetchone()
    )


def match_media(
    conn: sqlite3.Connection,
    track_id: int,
    max_difference: float,
    project_id: int | None,
) -> dict:
    timed_points = conn.execute(
        """
        SELECT latitude, longitude, elevation, recorded_at
        FROM gpx_points
        WHERE track_id = ? AND recorded_at IS NOT NULL
        ORDER BY recorded_at, sequence
        """,
        (track_id,),
    ).fetchall()
    point_times = [point["recorded_at"] for point in timed_points]
    query = """
        SELECT DISTINCT m.id, m.title, m.captured_at, m.gps_source,
                        m.latitude, m.longitude
        FROM media m
    """
    parameters: tuple = ()
    if project_id is not None:
        query += " JOIN project_media pm ON pm.media_id = m.id AND pm.project_id = ?"
        parameters = (project_id,)
    query += " ORDER BY m.id"
    media = conn.execute(query, parameters).fetchall()

    counts = {"matched": 0, "skipped": 0, "unmatched": 0}
    details = []
    now = time.time()
    for item in media:
        detail = {"media_id": item["id"], "title": item["title"]}
        if (
            item["gps_source"] in {"manual", "exif"}
            and item["latitude"] is not None
            and item["longitude"] is not None
        ):
            counts["skipped"] += 1
            detail.update(status="skipped", reason="existing_position")
        elif item["captured_at"] is None:
            counts["skipped"] += 1
            detail.update(status="skipped", reason="missing_capture_time")
        elif not timed_points:
            counts["unmatched"] += 1
            detail.update(status="unmatched", reason="track_has_no_timestamps")
        else:
            index = bisect_left(point_times, item["captured_at"])
            candidates = []
            if index < len(timed_points):
                candidates.append(timed_points[index])
            if index:
                candidates.append(timed_points[index - 1])
            nearest = min(
                candidates,
                key=lambda point: abs(point["recorded_at"] - item["captured_at"]),
            )
            difference = abs(nearest["recorded_at"] - item["captured_at"])
            if difference > max_difference:
                counts["unmatched"] += 1
                detail.update(
                    status="unmatched",
                    reason="outside_time_window",
                    time_difference_seconds=difference,
                )
            else:
                conn.execute(
                    """
                    UPDATE media
                    SET latitude = ?, longitude = ?, altitude = ?,
                        gps_source = 'gpx', gps_updated_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        nearest["latitude"],
                        nearest["longitude"],
                        nearest["elevation"],
                        now,
                        now,
                        item["id"],
                    ),
                )
                counts["matched"] += 1
                detail.update(
                    status="matched",
                    time_difference_seconds=difference,
                    latitude=nearest["latitude"],
                    longitude=nearest["longitude"],
                )
        details.append(detail)
    return {**counts, "details": details}


def save_upload(stream: BinaryIO, destination: Path) -> None:
    total = 0
    with destination.open("wb") as output:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_GPX_FILE_SIZE:
                raise GpxError(
                    "gpx_file_too_large",
                    f"GPX-Dateien dürfen höchstens {MAX_GPX_FILE_SIZE // (1024 * 1024)} MB groß sein.",
                    413,
                )
            output.write(chunk)
    if total == 0:
        raise GpxError("empty_gpx", "Die GPX-Datei ist leer.")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _finite(value: str, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GpxError("invalid_coordinate", f"Ungültiger GPX-Wert für {field}.") from exc
    if not math.isfinite(number):
        raise GpxError("invalid_coordinate", f"Ungültiger GPX-Wert für {field}.")
    return number


def _time(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError) as exc:
        raise GpxError("invalid_time", "Ein GPX-Zeitstempel ist ungültig.") from exc


def parse_gpx(path: Path, *, max_points: int = MAX_GPX_POINTS) -> ParsedGpx:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise GpxError("gpx_read_failed", "Die GPX-Datei konnte nicht gelesen werden.") from exc
    if len(data) > MAX_GPX_FILE_SIZE:
        raise GpxError("gpx_file_too_large", "Die GPX-Datei ist zu groß.", 413)
    if _FORBIDDEN_XML.search(data):
        raise GpxError("unsafe_xml", "DTD und Entitäten sind in GPX-Dateien nicht erlaubt.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise GpxError("invalid_xml", "Die GPX-Datei enthält kein gültiges XML.") from exc
    if _local_name(root.tag) != "gpx":
        raise GpxError("invalid_gpx", "Das XML-Dokument ist keine GPX-Datei.")

    points: list[GpxPoint] = []
    track_name = None
    for track in (element for element in root.iter() if _local_name(element.tag) == "trk"):
        if track_name is None:
            for child in track:
                if _local_name(child.tag) == "name" and child.text and child.text.strip():
                    track_name = child.text.strip()
                    break
        for segment in (child for child in track if _local_name(child.tag) == "trkseg"):
            for point in (child for child in segment if _local_name(child.tag) == "trkpt"):
                if len(points) >= max_points:
                    raise GpxError(
                        "point_limit_exceeded",
                        f"Ein GPX-Import darf höchstens {max_points} Punkte enthalten.",
                    )
                latitude = _finite(point.get("lat"), "latitude")
                longitude = _finite(point.get("lon"), "longitude")
                if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                    raise GpxError(
                        "invalid_coordinate",
                        "Ein GPX-Punkt liegt außerhalb des gültigen Koordinatenbereichs.",
                    )
                elevation = None
                recorded_at = None
                for child in point:
                    name = _local_name(child.tag)
                    if name == "ele" and child.text is not None:
                        elevation = _finite(child.text, "elevation")
                    elif name == "time":
                        recorded_at = _time(child.text)
                points.append(
                    GpxPoint(len(points), latitude, longitude, elevation, recorded_at)
                )
    if not points:
        raise GpxError("no_track_points", "Die GPX-Datei enthält keine Trackpunkte.")
    return ParsedGpx(track_name, points)

