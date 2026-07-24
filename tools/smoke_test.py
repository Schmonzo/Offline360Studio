from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(url: str, *, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=data, headers=headers, method=method),
            timeout=15,
        ) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers


def wait_until_ready(base_url: str, process: subprocess.Popen, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"App vorzeitig beendet (Exit {process.returncode}).")
        try:
            if request(base_url + "/")[0] == 200:
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise RuntimeError("App wurde nicht rechtzeitig erreichbar.")


def main() -> int:
    port = free_port()
    production_database = ROOT / "data" / "OFFLINE360_STUDIO.db"
    production_state = (
        (production_database.stat().st_size, production_database.stat().st_mtime_ns)
        if production_database.exists()
        else None
    )
    with tempfile.TemporaryDirectory(prefix="panorama-smoke-") as temporary:
        runtime_root = Path(temporary)
        (runtime_root / "media" / "photos").mkdir(parents=True)
        (runtime_root / "media" / "photos" / "smoke.jpg").write_bytes(
            b"\xff\xd8\xff\xd9"
        )
        environment = os.environ.copy()
        environment.update(
            {
                "OFFLINE360_STUDIO_RUNTIME_ROOT": str(runtime_root),
                "OFFLINE360_STUDIO_PORT": str(port),
                "OFFLINE360_STUDIO_NO_BROWSER": "1",
                "PYTHONUNBUFFERED": "1",
            }
        )
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "app.py")],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creationflags,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            wait_until_ready(base_url, process)
            assert request(base_url + "/")[0] == 200
            assert request(base_url + "/api/projects")[0] == 200
            assert request(base_url + "/api/diagnostics")[0] == 200
            status, backup_data, headers = request(
                base_url + "/api/backup/export",
                method="POST",
                payload={"includes_media": False, "includes_maps": False},
            )
            assert status == 200 and backup_data.startswith(b"PK")
            status, body, _ = request(
                base_url + "/api/projects",
                method="POST",
                payload={"name": "Smoke-Test"},
            )
            assert status == 201
            project_id = json.loads(body)["item"]["id"]
            status, _, _ = request(
                base_url + "/api/export/portable-tour",
                method="POST",
                payload={
                    "project_id": project_id,
                    "filename": "smoke-tour",
                    "include_videos": False,
                    "include_map": False,
                    "include_tracks": False,
                },
            )
            assert status == 200
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
            output = process.stdout.read() if process.stdout else ""
        if process.returncode not in {0, 130, 3221225786, -signal.SIGINT}:
            raise RuntimeError(
                f"App wurde nicht sauber beendet (Exit {process.returncode}).\n{output}"
            )
        current_state = (
            (production_database.stat().st_size, production_database.stat().st_mtime_ns)
            if production_database.exists()
            else None
        )
        assert current_state == production_state, "Produktive Datenbank wurde verÃ¤ndert."
    print("Smoke-Test erfolgreich.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

