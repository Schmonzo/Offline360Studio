from __future__ import annotations

import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core.version import __version__
from tools.release.package_release import (
    digest,
    main,
    validate_no_absolute_build_paths,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "release" / "build-release.ps1"


class ReleaseModeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")
        match = re.search(
            r"function Write-StandaloneLauncher.*?^}\s*$",
            cls.source,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not match:
            raise AssertionError("Standalone launcher function not found")
        cls.launcher = match.group(0)

    def test_modes_and_default_are_declared(self) -> None:
        self.assertIn('[ValidateSet("dev", "standalone")]', self.source)
        self.assertRegex(self.source, r'\[string\]\$Mode\s*=\s*"dev"')

    def test_mode_specific_package_names(self) -> None:
        self.assertIn(
            '"Offline360Studio-$Version-win64-$Mode"', self.source
        )
        self.assertIn('$Mode -eq "standalone"', self.source)
        self.assertIn(
            'Copy-Item "start-offline360-studio.bat"', self.source
        )

    def test_standalone_launcher_is_local_and_offline(self) -> None:
        lowered = self.launcher.lower()
        self.assertIn(r"runtime\python\python.exe", lowered)
        self.assertIn("offline360_studio_runtime_root", lowered)
        self.assertIn(r'app\app.py', lowered)
        for forbidden in (" pip ", "winget", "invoke-webrequest", "curl ", "wget"):
            self.assertNotIn(forbidden, lowered)
        self.assertIn('"pip-*.dist-info"', self.source)
        self.assertIn('-Filter "pip*.exe"', self.source)

    def test_runtime_and_server_are_covered_by_checksums(self) -> None:
        packager = (
            ROOT / "tools" / "release" / "package_release.py"
        ).read_text(encoding="utf-8")
        self.assertIn("staging.rglob", packager)
        self.assertIn("checksums.txt", packager)
        self.assertIn(r"$Stage\app\tools\portable-server\server.exe", self.source)
        self.assertIn(
            '$PythonRuntime = Join-Path $Stage "runtime\\python"',
            self.source,
        )

    def test_documented_python_source_and_hash(self) -> None:
        self.assertIn("3.12.10", self.source)
        self.assertIn('"..\\..\\app"', self.source)
        self.assertIn(
            "4acbed6dd1c744b0376e3b1cf57ce906"
            "f9dc9e95e68824584c8099a63025a3c3",
            self.source,
        )

    def test_release_version_file_uses_central_version(self) -> None:
        self.assertIn(
            'from core.version import __version__; print(__version__)',
            self.source,
        )
        self.assertIn('Set-Content "$Stage\\VERSION.txt" $Version', self.source)
        self.assertTrue(__version__)


class ReleaseRepositoryContractTests(unittest.TestCase):
    def test_cache_and_release_paths_are_ignored(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/tools/release/cache/", ignore)
        self.assertIn("/build/cache/", ignore)
        self.assertIn("/build/release/", ignore)

    def test_readme_documents_standalone_mode(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("-Mode standalone", readme)
        self.assertIn("runtime\\python\\python.exe", readme)

    def test_runtime_root_is_package_root(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('set "offline360_studio_runtime_root=%cd%"', source.lower())
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        runtime_source = (ROOT / "core" / "runtime_paths.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("runtime_paths.build_runtime_paths(BASE_DIR)", app_source)
        self.assertIn('os.environ.get(RUNTIME_ROOT_ENV)', runtime_source)

    def test_digest_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "payload"
            path.write_bytes(b"offline360-studio")
            self.assertEqual(digest(path), digest(path))

    def test_packager_keeps_empty_dirs_and_checksums_runtime_and_server(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / "Offline360Studio-test-win64-standalone"
            (stage / "runtime" / "python").mkdir(parents=True)
            (stage / "app" / "tools" / "portable-server").mkdir(parents=True)
            (stage / "data").mkdir()
            (stage / "media").mkdir()
            (stage / "logs").mkdir()
            (stage / "runtime" / "python" / "python.exe").write_bytes(b"python")
            server = stage / "app" / "tools" / "portable-server" / "server.exe"
            server.write_bytes(b"server")
            output = root / "release.zip"
            with patch.object(sys, "argv", ["package_release.py", str(stage), str(output)]):
                self.assertEqual(main(), 0)
            checksums = (stage / "checksums.txt").read_text(encoding="ascii")
            self.assertIn("runtime/python/python.exe", checksums)
            self.assertIn("app/tools/portable-server/server.exe", checksums)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
            prefix = f"{stage.name}/"
            self.assertIn(prefix + "data/", names)
            self.assertIn(prefix + "media/", names)
            self.assertIn(prefix + "logs/", names)

    def test_packager_rejects_absolute_build_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary) / "stage"
            stage.mkdir()
            leaked = stage / "leaked.txt"
            leaked.write_text(str(stage.resolve()), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_no_absolute_build_paths(stage, [leaked])


if __name__ == "__main__":
    unittest.main()




