from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

from core.version import __version__

EXPORT_VERSION = __version__
ARCHIVE_ROOT = "portable-tour"
LOGGER = logging.getLogger(__name__)


class PortableExportError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def safe_filename(value: object, fallback: str = "portable-tour") -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^\w.-]+", "-", text, flags=re.UNICODE)
    text = text.strip(" .-_")
    if text.lower().endswith(".zip"):
        text = text[:-4].rstrip(" .-_")
    return (text or fallback)[:120]


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed_file(stored_path: object, base_dir: Path, allowed_root: Path) -> Path | None:
    if not isinstance(stored_path, str) or not stored_path.strip():
        return None
    relative = Path(stored_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = allowed_root.resolve()
    candidate = (base_dir / relative).resolve()
    if not _inside(candidate, root) or not candidate.is_file():
        return None
    return candidate


def _media_name(media_id: int, source: Path) -> str:
    stem = safe_filename(source.stem, f"medium-{media_id}")
    suffix = re.sub(r"[^a-zA-Z0-9.]", "", source.suffix.lower())
    return f"{media_id}-{stem}{suffix}"


def _readme(
    project_name: str,
    total_size: int,
    includes_map: bool,
    map_type: str | None,
    warnings: list[str],
) -> str:
    size_mib = total_size / (1024 * 1024)
    attribution = (
        "\nKartenattribution\n"
        "Kartendaten: OpenStreetMap-Mitwirkende (ODbL), sofern die enthaltene "
        "Kartenquelle auf OpenStreetMap-Daten basiert.\n"
        if includes_map
        else ""
    )
    warning_text = "\n".join(f"- {item}" for item in warnings) or "- Keine."
    vector_limit = (
        "- Vector-MBTiles werden mit dem lokalen MapLibre gerendert. Der "
        "automatisch erzeugte Stil verwendet keine externen Fonts, Glyphs, "
        "Sprites oder Styles; Beschriftungen sind deshalb nicht enthalten.\n"
        if map_type == "vector"
        else ""
    )
    return (
        f"Panorama Studio Portable Tour {EXPORT_VERSION}\n"
        f"Projekt: {project_name}\n\n"
        "Start\n"
        "1. start-tour.bat doppelklicken.\n"
        "2. Die Tour öffnet sich automatisch im Standardbrowser.\n"
        "Direktes Öffnen von index.html über file:// wird aus Browser-"
        "Sicherheitsgründen nicht unterstützt.\n\n"
        "Diese Tour arbeitet vollständig offline. Sie benötigt weder Python, "
        "Flask noch eine Datenbank. Es werden keine CDN-, API- oder sonstigen "
        "Netzwerkzugriffe ausgeführt. server.exe wurde reproduzierbar aus dem "
        "mit Panorama Studio gelieferten Go-Quellcode unter "
        "tools/portable-server gebaut und vor dem Export per SHA-256 geprüft.\n\n"
        "Browserempfehlung\n"
        "Aktuelle Version von Microsoft Edge, Google Chrome oder Firefox mit "
        "aktiviertem WebGL.\n\n"
        f"Ungefähre Größe der exportierten Projektdaten: {size_mib:.1f} MiB\n"
        f"{attribution}\n"
        "Lizenzhinweise\n"
        "- Marzipano: Apache License 2.0\n"
        "- Three.js: MIT License\n"
        "- Leaflet: BSD-2-Clause License\n"
        "- MapLibre GL JS (falls enthalten): BSD-3-Clause License\n"
        "- Portable Server: eigener Panorama-Studio-Quellcode\n"
        "- modernc.org/sqlite: BSD-3-Clause; SQLite: Public Domain\n"
        "Die Lizenzdateien liegen unter assets/lib/; Marzipanos Apache-2.0-"
        "Hinweis steht im Kopf von marzipano.js.\n\n"
        "Bekannte Einschränkungen\n"
        f"{vector_limit}"
        "- Browserunterstützung für Video-Codecs ist systemabhängig.\n\n"
        "Hinweise beim Export\n"
        f"{warning_text}\n"
    )


def _copy_asset(archive: zipfile.ZipFile, source: Path, target: str) -> None:
    if not source.is_file():
        raise PortableExportError(
            "viewer_asset_missing",
            f"Die portable Viewer-Datei fehlt: {source.name}",
            500,
        )
    archive.write(source, f"{ARCHIVE_ROOT}/{target}")


def _validated_server(server_executable: Path) -> tuple[Path, Path | None]:
    expected = server_executable.absolute()
    if expected.is_symlink() or not expected.is_file():
        raise PortableExportError(
            "portable_server_missing",
            "Der portable Server wurde noch nicht gebaut. Bitte "
            "tools/portable-server/build.ps1 ausführen.",
            503,
        )
    hash_file = expected.with_name("server.exe.sha256")
    if not hash_file.is_file():
        raise PortableExportError(
            "portable_server_hash_missing",
            "server.exe.sha256 fehlt. Bitte tools/portable-server/build.ps1 "
            "erneut ausführen.",
            500,
        )
    try:
        expected_hash = hash_file.read_text(encoding="ascii").split()[0].lower()
    except (OSError, UnicodeError, IndexError) as exc:
        raise PortableExportError(
            "portable_server_hash_invalid",
            "server.exe.sha256 ist ungültig. Bitte den portablen Server neu bauen.",
            500,
        ) from exc
    if re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
        raise PortableExportError(
            "portable_server_hash_invalid",
            "server.exe.sha256 ist ungültig. Bitte den portablen Server neu bauen.",
            500,
        )
    digest = hashlib.sha256()
    with expected.open("rb") as server_file:
        for chunk in iter(lambda: server_file.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_hash:
        raise PortableExportError(
            "portable_server_hash_mismatch",
            "server.exe stimmt nicht mit server.exe.sha256 überein. "
            "Bitte tools/portable-server/build.ps1 erneut ausführen.",
            500,
        )
    return expected, hash_file


def server_hash_status(server_executable: Path) -> dict[str, bool | str]:
    try:
        _validated_server(server_executable)
        return {"present": True, "sha256_valid": True, "status": "valid"}
    except PortableExportError as exc:
        return {
            "present": server_executable.is_file(),
            "sha256_valid": False,
            "status": exc.code,
        }


def create_archive(
    conn: sqlite3.Connection,
    output_path: Path,
    *,
    project_id: int,
    include_videos: bool,
    include_map: bool,
    include_tracks: bool,
    base_dir: Path,
    photo_dir: Path,
    video_dir: Path,
    thumb_dir: Path,
    maps_dir: Path,
    viewer_dir: Path,
    static_dir: Path,
    server_executable: Path,
) -> dict[str, Any]:
    project = conn.execute(
        """
        SELECT id, name, description, cover_media_id, start_media_id
        FROM projects WHERE id = ?
        """,
        (project_id,),
    ).fetchone()
    if project is None:
        raise PortableExportError(
            "project_not_found", "Das Projekt wurde nicht gefunden.", 404
        )
    server_path, server_hash_path = _validated_server(server_executable)

    rows = conn.execute(
        """
        SELECT m.*, pm.sort_order
        FROM project_media pm
        JOIN media m ON m.id = pm.media_id
        WHERE pm.project_id = ?
        ORDER BY pm.sort_order, pm.media_id
        """,
        (project_id,),
    ).fetchall()
    rows = [row for row in rows if include_videos or row["type"] != "video"]
    exported_ids = {int(row["id"]) for row in rows}
    hotspots = conn.execute(
        """
        SELECT id, source_media_id, action_type, yaw, pitch, title, info_text,
               target_media_id, visible
        FROM hotspots
        WHERE source_media_id IN (
            SELECT media_id FROM project_media WHERE project_id = ?
        )
        ORDER BY source_media_id, id
        """,
        (project_id,),
    ).fetchall()
    hotspots_by_media: dict[int, list[dict[str, Any]]] = {}
    for row in hotspots:
        item = dict(row)
        source_id = int(item.pop("source_media_id"))
        if source_id not in exported_ids:
            continue
        if item["action_type"] == "panorama" and item["target_media_id"] not in exported_ids:
            continue
        item["visible"] = bool(item["visible"])
        hotspots_by_media.setdefault(source_id, []).append(item)

    warnings: list[str] = []
    media_payload: list[dict[str, Any]] = []
    pending_files: list[tuple[Path, str]] = []
    total_size = 0
    for order, row in enumerate(rows):
        media_id = int(row["id"])
        allowed_root = photo_dir if row["type"] == "photo" else video_dir
        source = _allowed_file(row["file_path"], base_dir, allowed_root)
        local_path = None
        available = source is not None
        if source is not None:
            local_path = f"assets/media/{_media_name(media_id, source)}"
            pending_files.append((source, local_path))
            total_size += source.stat().st_size
        else:
            message = f"Medium {media_id} ({row['title']}) fehlt oder hat einen unsicheren Pfad."
            warnings.append(message)
            LOGGER.warning(message)

        thumbnail = None
        thumb = _allowed_file(row["thumb_path"], base_dir, thumb_dir)
        if thumb is not None:
            thumbnail = f"assets/thumbnails/{_media_name(media_id, thumb)}"
            pending_files.append((thumb, thumbnail))
            total_size += thumb.stat().st_size

        media_payload.append(
            {
                "id": media_id,
                "type": row["type"],
                "title": row["title"] or "",
                "description": row["description"] or "",
                "order": order,
                "local_path": local_path,
                "thumbnail": thumbnail,
                "available": available,
                "start_view": {
                    "yaw": row["start_yaw"],
                    "pitch": row["start_pitch"],
                    "fov": row["start_fov"],
                },
                "hotspots": hotspots_by_media.get(media_id, []),
                "gps": (
                    {
                        "latitude": row["latitude"],
                        "longitude": row["longitude"],
                        "altitude": row["altitude"],
                    }
                    if row["latitude"] is not None and row["longitude"] is not None
                    else None
                ),
            }
        )

    track_payload: list[dict[str, Any]] = []
    if include_tracks:
        track_rows = conn.execute(
            """
            SELECT id, name FROM gpx_tracks
            WHERE project_id = ? ORDER BY imported_at, id
            """,
            (project_id,),
        ).fetchall()
        for track in track_rows:
            points = [
                {
                    "latitude": point["latitude"],
                    "longitude": point["longitude"],
                    "elevation": point["elevation"],
                    "recorded_at": point["recorded_at"],
                }
                for point in conn.execute(
                    """
                    SELECT latitude, longitude, elevation, recorded_at
                    FROM gpx_points WHERE track_id = ? ORDER BY sequence
                    """,
                    (track["id"],),
                ).fetchall()
            ]
            path = f"assets/tracks/{int(track['id'])}-{safe_filename(track['name'], 'track')}.json"
            track_payload.append(
                {"id": int(track["id"]), "name": track["name"], "path": path, "points": points}
            )

    map_payload = None
    map_type = None
    if include_map:
        map_row = conn.execute(
            """
            SELECT id, name, filename, format, map_type, min_zoom, max_zoom,
                   bounds, center, attribution
            FROM map_sources WHERE active = 1
            """
        ).fetchone()
        if map_row is not None:
            source = _allowed_file(map_row["filename"], maps_dir, maps_dir)
            if source is not None and source.suffix.lower() == ".mbtiles":
                map_name = f"{int(map_row['id'])}-{safe_filename(map_row['name'], 'map')}.mbtiles"
                map_path = f"assets/maps/{map_name}"
                pending_files.append((source, map_path))
                total_size += source.stat().st_size
                map_type = map_row["map_type"]
                map_payload = {
                    "path": map_path,
                    "map_type": map_type,
                    "format": map_row["format"],
                    "name": map_row["name"],
                    "attribution": map_row["attribution"] or "",
                    "bounds": map_row["bounds"],
                    "center": map_row["center"],
                    "min_zoom": map_row["min_zoom"],
                    "max_zoom": map_row["max_zoom"],
                }
            else:
                warnings.append("Die aktive Kartenquelle fehlt oder hat einen unsicheren Pfad.")
        else:
            warnings.append("Es ist keine aktive Offline-Kartenquelle vorhanden.")

    cover_id = project["cover_media_id"] if project["cover_media_id"] in exported_ids else None
    start_id = project["start_media_id"] if project["start_media_id"] in exported_ids else None
    tour = {
        "format": "panorama-studio-portable-tour",
        "version": EXPORT_VERSION,
        "project": {
            "id": int(project["id"]),
            "name": project["name"],
            "description": project["description"] or "",
            "cover_media_id": cover_id,
            "start_media_id": start_id,
        },
        "media_order": [item["id"] for item in media_payload],
        "media": media_payload,
        "gpx_tracks": track_payload,
        "map_source": map_payload,
        "warnings": warnings,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", allowZip64=True) as archive:
        for directory in (
            "assets/css/",
            "assets/js/",
            "assets/lib/",
            "assets/media/",
            "assets/thumbnails/",
            "assets/maps/",
            "assets/tracks/",
        ):
            archive.writestr(f"{ARCHIVE_ROOT}/{directory}", b"")
        archive.writestr(
            f"{ARCHIVE_ROOT}/tour.json",
            json.dumps(tour, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        archive.writestr(
            f"{ARCHIVE_ROOT}/README.txt",
            _readme(project["name"], total_size, map_payload is not None, map_type, warnings).encode("utf-8"),
        )
        for track in track_payload:
            archive.writestr(
                f"{ARCHIVE_ROOT}/{track['path']}",
                json.dumps(
                    {"name": track["name"], "points": track["points"]},
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8"),
            )
        for source, target in pending_files:
            archive.write(source, f"{ARCHIVE_ROOT}/{target}")

        _copy_asset(archive, viewer_dir / "index.html", "index.html")
        _copy_asset(archive, viewer_dir / "start-tour.bat", "start-tour.bat")
        _copy_asset(archive, server_path, "server.exe")
        if server_hash_path is not None:
            _copy_asset(archive, server_hash_path, "server.exe.sha256")
        _copy_asset(archive, viewer_dir / "viewer.css", "assets/css/viewer.css")
        _copy_asset(archive, viewer_dir / "viewer.js", "assets/js/viewer.js")
        _copy_asset(archive, static_dir / "lib" / "marzipano.js", "assets/lib/marzipano.js")
        _copy_asset(archive, static_dir / "lib" / "three.module.min.js", "assets/lib/three.module.min.js")
        _copy_asset(archive, static_dir / "lib" / "three.core.min.js", "assets/lib/three.core.min.js")
        _copy_asset(archive, static_dir / "lib" / "three.LICENSE.txt", "assets/lib/three.LICENSE.txt")
        _copy_asset(archive, static_dir / "lib" / "THREE.md", "assets/lib/THREE.md")
        _copy_asset(archive, static_dir / "lib" / "leaflet" / "leaflet.js", "assets/lib/leaflet.js")
        _copy_asset(archive, static_dir / "lib" / "leaflet" / "leaflet.css", "assets/lib/leaflet.css")
        _copy_asset(archive, static_dir / "lib" / "leaflet" / "LICENSE.txt", "assets/lib/leaflet.LICENSE.txt")
        _copy_asset(archive, static_dir / "lib" / "maplibre" / "maplibre-gl.js", "assets/lib/maplibre-gl.js")
        _copy_asset(archive, static_dir / "lib" / "maplibre" / "maplibre-gl.css", "assets/lib/maplibre-gl.css")
        _copy_asset(archive, static_dir / "lib" / "maplibre" / "LICENSE.txt", "assets/lib/maplibre.LICENSE.txt")
        for source_name, target_name in (
            ("marker-icon.png", "marker-icon.png"),
            ("marker-icon-2x.png", "marker-icon-2x.png"),
            ("marker-shadow.png", "marker-shadow.png"),
        ):
            _copy_asset(
                archive,
                static_dir / "lib" / "leaflet" / "images" / source_name,
                f"assets/lib/images/{target_name}",
            )

        for source_name, target_name in (
            ("video360.js", "video360.js"),
            ("tinyplanet.js", "tinyplanet.js"),
        ):
            source = (static_dir / "js" / source_name).read_text(encoding="utf-8")
            source = source.replace(
                "'/static/lib/three.module.min.js'",
                "'../lib/three.module.min.js'",
            )
            archive.writestr(f"{ARCHIVE_ROOT}/assets/js/{target_name}", source.encode("utf-8"))

    return tour
