from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def main() -> int:
    staging = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    files = sorted(
        path
        for path in staging.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    checksum_path = staging / "checksums.txt"
    checksum_path.write_text(
        "".join(
            f"{digest(path)}  {path.relative_to(staging).as_posix()}\n"
            for path in files
            if path != checksum_path
        ),
        encoding="ascii",
        newline="\n",
    )
    files = sorted(
        path
        for path in staging.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = path.relative_to(staging.parent).as_posix()
            info = zipfile.ZipInfo(relative, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    print(f"Release erstellt: {output}")
    print(f"SHA-256: {digest(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
