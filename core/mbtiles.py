from __future__ import annotations

import gzip
import io
import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


MAX_MBTILES_SIZE = 5 * 1024 * 1024 * 1024
MAX_VECTOR_TILE_SIZE = 16 * 1024 * 1024
MAX_DECOMPRESSED_VECTOR_TILE_SIZE = 64 * 1024 * 1024
MAX_METADATA_JSON_SIZE = 1024 * 1024
RASTER_FORMATS = {"png", "jpg", "jpeg", "webp"}
VECTOR_FORMATS = {"pbf", "mvt"}
SUPPORTED_FORMATS = RASTER_FORMATS | VECTOR_FORMATS
MAP_TYPES = {"raster", "vector"}
CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "pbf": "application/vnd.mapbox-vector-tile",
    "mvt": "application/vnd.mapbox-vector-tile",
}
REQUIRED_TILE_COLUMNS = {"zoom_level", "tile_column", "tile_row", "tile_data"}
REQUIRED_MAP_COLUMNS = {"zoom_level", "tile_column", "tile_row", "tile_id"}
REQUIRED_IMAGE_COLUMNS = {"tile_id", "tile_data"}
SCHEMA_TYPES = {"flat", "normalized"}


class MBTilesError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Metadata:
    name: str
    format: str
    map_type: str
    schema_type: str
    min_zoom: int | None
    max_zoom: int | None
    bounds: str | None
    center: str | None
    attribution: str
    vector_layers: tuple[dict, ...]

    @property
    def style_available(self) -> bool:
        return self.map_type == "vector" and bool(self.vector_layers)


def map_type_for_format(tile_format: object) -> str | None:
    if not isinstance(tile_format, str):
        return None
    normalized = tile_format.strip().lower()
    if normalized in RASTER_FORMATS:
        return "raster"
    if normalized in VECTOR_FORMATS:
        return "vector"
    return None


def validated_map_type(map_type: object, tile_format: object) -> str:
    expected = map_type_for_format(tile_format)
    if map_type in MAP_TYPES and map_type == expected:
        return str(map_type)
    return "unknown"


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def save_upload(
    stream: BinaryIO, destination: Path, max_size: int = MAX_MBTILES_SIZE
) -> int:
    written = 0
    try:
        with destination.open("xb") as target:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_size:
                    raise MBTilesError(
                        "map_too_large",
                        f"Die MBTiles-Datei Ã¼berschreitet das Limit von "
                        f"{max_size // (1024**3)} GB.",
                        413,
                    )
                target.write(chunk)
    except MBTilesError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise MBTilesError(
            "map_upload_failed",
            "Die MBTiles-Datei konnte nicht gespeichert werden.",
            500,
        ) from exc
    return written


def _optional_zoom(value: str | None, field: str) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        result = int(value)
    except ValueError as exc:
        raise MBTilesError(
            "invalid_metadata", f"Das MBTiles-Feld {field} ist ungÃ¼ltig."
        ) from exc
    if not 0 <= result <= 30:
        raise MBTilesError(
            "invalid_metadata",
            f"Das MBTiles-Feld {field} muss zwischen 0 und 30 liegen.",
        )
    return result


def _metadata_json(value: str | None) -> dict:
    if not value:
        return {}
    if len(value.encode("utf-8", errors="replace")) > MAX_METADATA_JSON_SIZE:
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _vector_layers(document: dict) -> tuple[dict, ...]:
    layers = document.get("vector_layers")
    if not isinstance(layers, list):
        return ()
    result: list[dict] = []
    seen: set[str] = set()
    for item in layers[:256]:
        if not isinstance(item, dict):
            continue
        layer_id = item.get("id")
        if (
            not isinstance(layer_id, str)
            or not layer_id.strip()
            or len(layer_id.strip()) > 200
            or "://" in layer_id
            or layer_id.strip() in seen
        ):
            continue
        layer_id = layer_id.strip()
        layer: dict = {"id": layer_id}
        fields = item.get("fields")
        if isinstance(fields, dict):
            layer["fields"] = {
                str(key)[:200]: str(value)[:200]
                for key, value in list(fields.items())[:256]
                if isinstance(key, str)
            }
        for key in ("description",):
            if isinstance(item.get(key), str):
                layer[key] = item[key][:1000]
        for key in ("minzoom", "maxzoom"):
            value = item.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                layer[key] = max(0, min(30, value))
        seen.add(layer_id)
        result.append(layer)
    return tuple(result)


def serialize_vector_layers(layers: tuple[dict, ...]) -> str:
    return json.dumps(layers, ensure_ascii=False, separators=(",", ":"))


def deserialize_vector_layers(value: str | None) -> list[dict]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    return list(_vector_layers({"vector_layers": parsed}))


def _columns(conn: sqlite3.Connection, name: str) -> set[str]:
    return {
        str(row[1]).lower()
        for row in conn.execute(f"PRAGMA table_info({name})").fetchall()
    }


def detect_schema(conn: sqlite3.Connection) -> str:
    objects = {
        str(row[0]).lower(): str(row[1]).lower()
        for row in conn.execute(
            """
            SELECT name, type FROM sqlite_master
            WHERE type IN ('table', 'view')
            """
        ).fetchall()
    }
    if (
        objects.get("tiles") in {"table", "view"}
        and REQUIRED_TILE_COLUMNS.issubset(_columns(conn, "tiles"))
    ):
        return "flat"
    if (
        objects.get("map") in {"table", "view"}
        and objects.get("images") in {"table", "view"}
        and REQUIRED_MAP_COLUMNS.issubset(_columns(conn, "map"))
        and REQUIRED_IMAGE_COLUMNS.issubset(_columns(conn, "images"))
    ):
        return "normalized"
    raise MBTilesError(
        "tiles_schema_invalid" if "tiles" in objects else "tiles_table_missing",
        "Weder ein gÃ¼ltiges tiles-Schema noch ein gÃ¼ltiges map/images-Schema gefunden.",
    )


def validate(path: Path, fallback_name: str) -> Metadata:
    try:
        with closing(connect_readonly(path)) as conn:
            integrity = conn.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise MBTilesError(
                    "invalid_mbtiles", "Die MBTiles-Datei ist beschÃ¤digt."
                )
            tables = {
                str(row[0]).lower()
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "metadata" not in tables:
                raise MBTilesError(
                    "metadata_table_missing",
                    "Die MBTiles-Datei enthÃ¤lt keine metadata-Tabelle.",
                )
            schema_type = detect_schema(conn)
            metadata_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(metadata)").fetchall()
            }
            if not {"name", "value"}.issubset(metadata_columns):
                raise MBTilesError(
                    "metadata_schema_invalid",
                    "Die metadata-Tabelle hat nicht die erwarteten Spalten.",
                )
            values = {
                str(row[0]).strip().lower(): str(row[1]).strip()
                for row in conn.execute("SELECT name, value FROM metadata").fetchall()
                if row[0] is not None and row[1] is not None
            }
            tile_format = values.get("format", "").lower()
            if tile_format not in SUPPORTED_FORMATS:
                raise MBTilesError(
                    "map_format_unsupported",
                    "Erlaubt sind Raster-MBTiles (PNG, JPEG, WebP) und "
                    "Vector-MBTiles (PBF, MVT).",
                    415,
                )
            tileset_type = map_type_for_format(tile_format)
            if tileset_type is None:
                raise MBTilesError(
                    "map_format_unsupported",
                    "Das Format der Kartenquelle wird nicht unterstÃ¼tzt.",
                    415,
                )
            declared_type = values.get("type", "").lower()
            allowed_declared_types = (
                {"", "baselayer"} if tileset_type == "raster"
                else {"", "baselayer", "overlay"}
            )
            if declared_type not in allowed_declared_types:
                raise MBTilesError(
                    "map_type_unsupported",
                    "Der deklarierte MBTiles-Kartentyp wird nicht unterstÃ¼tzt.",
                    415,
                )
            if schema_type == "flat":
                zooms = conn.execute(
                    """
                    SELECT MIN(zoom_level), MAX(zoom_level), COUNT(*),
                           MAX(length(tile_data))
                    FROM tiles
                    """
                ).fetchone()
            else:
                missing_images = conn.execute(
                    """
                    SELECT COUNT(*) FROM map
                    LEFT JOIN images ON images.tile_id = map.tile_id
                    WHERE images.tile_id IS NULL
                    """
                ).fetchone()
                if missing_images is not None and int(missing_images[0]) > 0:
                    raise MBTilesError(
                        "tile_references_invalid",
                        "Das map-Schema enthÃ¤lt Verweise auf fehlende Bilder.",
                    )
                zooms = conn.execute(
                    """
                    SELECT MIN(map.zoom_level), MAX(map.zoom_level), COUNT(*),
                           MAX(length(images.tile_data))
                    FROM map
                    JOIN images ON images.tile_id = map.tile_id
                    """
                ).fetchone()
            if zooms is None or int(zooms[2]) < 1:
                raise MBTilesError(
                    "tiles_empty", "Die MBTiles-Datei enthÃ¤lt keine Kartenkacheln."
                )
            if (
                tileset_type == "vector"
                and zooms[3] is not None
                and int(zooms[3]) > MAX_VECTOR_TILE_SIZE
            ):
                raise MBTilesError(
                    "vector_tile_too_large",
                    "Die MBTiles-Datei enthÃ¤lt eine zu groÃŸe PBF-Kachel.",
                    413,
                )
            min_zoom = _optional_zoom(values.get("minzoom"), "minzoom")
            max_zoom = _optional_zoom(values.get("maxzoom"), "maxzoom")
            if min_zoom is None:
                min_zoom = int(zooms[0])
            if max_zoom is None:
                max_zoom = int(zooms[1])
            if not 0 <= min_zoom <= 30 or not 0 <= max_zoom <= 30:
                raise MBTilesError(
                    "invalid_metadata",
                    "Die Kachel-Zoomstufen mÃ¼ssen zwischen 0 und 30 liegen.",
                )
            if min_zoom > max_zoom:
                raise MBTilesError(
                    "invalid_metadata", "minzoom darf nicht grÃ¶ÃŸer als maxzoom sein."
                )
            json_metadata = _metadata_json(values.get("json"))
            vector_layers = (
                _vector_layers(json_metadata) if tileset_type == "vector" else ()
            )
            name = values.get("name", "").strip() or fallback_name.strip() or "Offline-Karte"
            return Metadata(
                name=name[:200],
                format=tile_format,
                map_type=tileset_type,
                schema_type=schema_type,
                min_zoom=min_zoom,
                max_zoom=max_zoom,
                bounds=values.get("bounds") or None,
                center=values.get("center") or None,
                attribution=values.get("attribution", ""),
                vector_layers=vector_layers,
            )
    except MBTilesError:
        raise
    except (sqlite3.Error, OSError, ValueError, OverflowError) as exc:
        raise MBTilesError(
            "invalid_mbtiles",
            "Die Datei ist keine gÃ¼ltige oder lesbare MBTiles-SQLite-Datenbank.",
        ) from exc


def new_filename() -> str:
    return f"{uuid.uuid4().hex}.mbtiles"


def source_path(maps_dir: Path, filename: str) -> Path:
    if (
        not filename
        or Path(filename).name != filename
        or re.fullmatch(r"[0-9a-f]{32}\.mbtiles", filename) is None
    ):
        raise MBTilesError("invalid_map_path", "Der Kartenpfad ist ungÃ¼ltig.", 500)
    root = maps_dir.resolve()
    candidate = (root / filename).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise MBTilesError("invalid_map_path", "Der Kartenpfad ist ungÃ¼ltig.", 500) from exc
    return candidate


def import_upload(stream: BinaryIO, maps_dir: Path, original_name: str) -> tuple[str, Metadata]:
    maps_dir.mkdir(parents=True, exist_ok=True)
    temporary = maps_dir / f".import-{uuid.uuid4().hex}.tmp"
    filename = new_filename()
    destination = maps_dir / filename
    try:
        save_upload(stream, temporary)
        metadata = validate(temporary, Path(original_name).stem)
        os.replace(temporary, destination)
        return filename, metadata
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise


def read_tile(
    path: Path, z: int, x: int, xyz_y: int, schema_type: str = "flat"
) -> bytes | None:
    if schema_type not in SCHEMA_TYPES:
        raise MBTilesError(
            "map_schema_invalid", "Das gespeicherte MBTiles-Schema ist ungÃ¼ltig.", 500
        )
    tms_y = (2**z - 1) - xyz_y
    try:
        with closing(connect_readonly(path)) as conn:
            if schema_type == "flat":
                row = conn.execute(
                    """
                    SELECT tile_data FROM tiles
                    WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?
                    """,
                    (z, x, tms_y),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT images.tile_data
                    FROM map
                    JOIN images ON images.tile_id = map.tile_id
                    WHERE map.zoom_level = ?
                      AND map.tile_column = ?
                      AND map.tile_row = ?
                    """,
                    (z, x, tms_y),
                ).fetchone()
    except sqlite3.Error as exc:
        raise MBTilesError(
            "map_read_failed", "Die Kartenquelle konnte nicht gelesen werden.", 500
        ) from exc
    return bytes(row[0]) if row is not None else None


def vector_tile_encoding(tile: bytes) -> str | None:
    if len(tile) > MAX_VECTOR_TILE_SIZE:
        raise MBTilesError(
            "vector_tile_too_large", "Die angeforderte PBF-Kachel ist zu groÃŸ.", 413
        )
    if tile.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(tile)) as archive:
                decoded = archive.read(MAX_DECOMPRESSED_VECTOR_TILE_SIZE + 1)
        except (EOFError, OSError) as exc:
            raise MBTilesError(
                "vector_tile_compression_invalid",
                "Die gzip-komprimierte PBF-Kachel ist ungÃ¼ltig.",
                415,
            ) from exc
        if len(decoded) > MAX_DECOMPRESSED_VECTOR_TILE_SIZE:
            raise MBTilesError(
                "vector_tile_too_large",
                "Die entpackte PBF-Kachel Ã¼berschreitet das GrÃ¶ÃŸenlimit.",
                413,
            )
        return "gzip"
    if (
        len(tile) >= 2
        and tile[0] == 0x78
        and ((tile[0] << 8) + tile[1]) % 31 == 0
    ):
        raise MBTilesError(
            "vector_tile_compression_unsupported",
            "Die PBF-Kachel verwendet eine nicht unterstÃ¼tzte zlib-Kompression.",
            415,
        )
    return None


def _number_list(value: str | None, length: int) -> list[float] | None:
    if not value:
        return None
    try:
        numbers = [float(part.strip()) for part in value.split(",")]
    except ValueError:
        return None
    if len(numbers) != length:
        return None
    return numbers


def generate_style(source_id: int, source: dict) -> dict:
    min_zoom = source.get("min_zoom")
    max_zoom = source.get("max_zoom")
    vector_layers = deserialize_vector_layers(source.get("vector_layers"))
    tile_source: dict = {
        "type": "vector",
        "tiles": [f"/api/maps/tiles/{source_id}/{{z}}/{{x}}/{{y}}"],
        "scheme": "xyz",
    }
    if isinstance(min_zoom, int):
        tile_source["minzoom"] = min_zoom
    if isinstance(max_zoom, int):
        tile_source["maxzoom"] = max_zoom
    bounds = _number_list(source.get("bounds"), 4)
    if bounds is not None:
        tile_source["bounds"] = bounds

    layers: list[dict] = [
        {
            "id": "offline-background",
            "type": "background",
            "paint": {"background-color": "#e9e4d8"},
        }
    ]
    palette = (
        ("#d8dfc8", "#657568", "#3c6f91"),
        ("#e1d3b6", "#8a6f4d", "#566f8e"),
        ("#cfdeda", "#55736d", "#426d86"),
        ("#ded4db", "#786879", "#516f8d"),
    )
    for index, layer in enumerate(vector_layers):
        source_layer = layer["id"]
        fill, line, circle = palette[index % len(palette)]
        common = {"source": "offline-tiles", "source-layer": source_layer}
        layers.extend(
            [
                {
                    "id": f"offline-{index}-fill",
                    "type": "fill",
                    **common,
                    "filter": ["==", ["geometry-type"], "Polygon"],
                    "paint": {
                        "fill-color": fill,
                        "fill-opacity": 0.72,
                        "fill-outline-color": line,
                    },
                },
                {
                    "id": f"offline-{index}-line",
                    "type": "line",
                    **common,
                    "filter": ["==", ["geometry-type"], "LineString"],
                    "paint": {
                        "line-color": line,
                        "line-width": [
                            "interpolate",
                            ["linear"],
                            ["zoom"],
                            0,
                            0.5,
                            16,
                            3,
                        ],
                    },
                },
                {
                    "id": f"offline-{index}-circle",
                    "type": "circle",
                    **common,
                    "filter": ["==", ["geometry-type"], "Point"],
                    "paint": {
                        "circle-color": circle,
                        "circle-radius": [
                            "interpolate",
                            ["linear"],
                            ["zoom"],
                            0,
                            2,
                            16,
                            5,
                        ],
                        "circle-stroke-color": "#ffffff",
                        "circle-stroke-width": 1,
                    },
                },
            ]
        )

    style: dict = {
        "version": 8,
        "name": "Offline360 Studio Offline-Basisstil",
        "sources": {"offline-tiles": tile_source},
        "layers": layers,
    }
    center = _number_list(source.get("center"), 3)
    if center is not None:
        style["center"] = center[:2]
        style["zoom"] = center[2]
    return style

