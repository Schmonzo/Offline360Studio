from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

RUNTIME_ROOT_ENV = "PANORAMA_STUDIO_RUNTIME_ROOT"
DATABASE_FILENAME = "panorama_studio.db"
LOG_FILENAME = "panorama-studio.log"


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    data: Path
    config: Path
    maps: Path
    media: Path
    photos: Path
    videos: Path
    thumbnails: Path
    logs: Path
    database: Path
    log_file: Path

    def required_directories(self) -> tuple[Path, ...]:
        return (
            self.data,
            self.config,
            self.maps,
            self.media,
            self.photos,
            self.videos,
            self.thumbnails,
            self.logs,
        )

    def ensure_directories(self) -> None:
        for directory in self.required_directories():
            directory.mkdir(parents=True, exist_ok=True)

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()


def runtime_root(app_dir: Path | None = None) -> Path:
    fallback = app_dir or Path(__file__).resolve().parents[1]
    configured = os.environ.get(RUNTIME_ROOT_ENV)
    return Path(configured).expanduser().resolve() if configured else fallback.resolve()


def data_dir(root: Path | None = None) -> Path:
    return (root or runtime_root()) / "data"


def media_dir(root: Path | None = None) -> Path:
    return (root or runtime_root()) / "media"


def thumbnail_dir(root: Path | None = None) -> Path:
    return media_dir(root) / "thumbs"


def logs_dir(root: Path | None = None) -> Path:
    return (root or runtime_root()) / "logs"


def database_path(root: Path | None = None) -> Path:
    return data_dir(root) / DATABASE_FILENAME


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def build_runtime_paths(app_dir: Path | None = None) -> RuntimePaths:
    root = runtime_root(app_dir)
    data = data_dir(root)
    media = media_dir(root)
    logs = logs_dir(root)
    return RuntimePaths(
        root=root,
        data=data,
        config=data / "config",
        maps=data / "maps",
        media=media,
        photos=media / "photos",
        videos=media / "videos",
        thumbnails=thumbnail_dir(root),
        logs=logs,
        database=database_path(root),
        log_file=logs / LOG_FILENAME,
    )
