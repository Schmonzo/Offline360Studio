param(
    [ValidateSet("dev", "standalone")]
    [string]$Mode = "dev"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Official CPython Windows embeddable package (64-bit).
# Release: https://www.python.org/downloads/release/python-31210/
# Artifact: https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip
# SHA-256: verified against the artifact's python.org Sigstore bundle.
$EmbeddedPythonVersion = "3.12.10"
$EmbeddedPythonArchive = "python-$EmbeddedPythonVersion-embed-amd64.zip"
$EmbeddedPythonUrl = "https://www.python.org/ftp/python/$EmbeddedPythonVersion/$EmbeddedPythonArchive"
$EmbeddedPythonSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"

# The embeddable distribution has no pip. This bootstrap file is downloaded
# only by the release build and is verified before it is executed.
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$GetPipSha256 = "fb24e693bab954209a063d90953621412ccad4a500905a726286e038f508ddf6"
$BuildPipVersion = "25.1.1"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$CacheDir = Join-Path $PSScriptRoot "cache"
$TemporaryBuildDir = $null

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath $($Arguments -join ' ') ist mit Exitcode $LASTEXITCODE fehlgeschlagen."
    }
}

function Invoke-NamedStep {
    param(
        [Parameter(Mandatory = $true)][string]$StartMessage,
        [Parameter(Mandatory = $true)][string]$SuccessMessage,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    Write-Host $StartMessage
    & $Action
    Write-Host $SuccessMessage
}

function Get-VerifiedDownload {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    if (Test-Path -LiteralPath $Destination) {
        $CachedHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($CachedHash -eq $ExpectedSha256) {
            Write-Host "Verifizierten Cache verwenden: $Destination"
            return
        }
        Write-Warning "Cache-Datei hat einen falschen SHA-256 und wird neu geladen: $Destination"
        Remove-Item -LiteralPath $Destination -Force
    }

    $Partial = "$Destination.download"
    if (Test-Path -LiteralPath $Partial) {
        Remove-Item -LiteralPath $Partial -Force
    }
    try {
        Write-Host "Download: $Url"
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Partial
        $ActualSha256 = (Get-FileHash -LiteralPath $Partial -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualSha256 -ne $ExpectedSha256) {
            throw "SHA-256-Abweichung fuer $Url. Erwartet: $ExpectedSha256, erhalten: $ActualSha256"
        }
        Move-Item -LiteralPath $Partial -Destination $Destination
    } finally {
        if (Test-Path -LiteralPath $Partial) {
            Remove-Item -LiteralPath $Partial -Force
        }
    }
}

function Write-StandaloneLauncher {
    param([Parameter(Mandatory = $true)][string]$Destination)
    @'
@echo off
setlocal
cd /d "%~dp0"

set "OFFLINE360_STUDIO_RUNTIME_ROOT=%CD%"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONNOUSERSITE=1"
set "PYTHON_EXE=%CD%\runtime\python\python.exe"

if not exist "%PYTHON_EXE%" (
  echo FEHLER: Die eingebettete Python-Runtime fehlt:
  echo %PYTHON_EXE%
  echo Bitte das Release-ZIP erneut vollstaendig entpacken.
  pause
  exit /b 1
)
if not exist "%CD%\app\app.py" (
  echo FEHLER: app\app.py fehlt. Bitte das Release-ZIP erneut entpacken.
  pause
  exit /b 1
)

echo Starte Offline360 Studio...
"%PYTHON_EXE%" "%CD%\app\app.py"
if errorlevel 1 (
  echo.
  echo FEHLER: Offline360 Studio wurde mit einem Fehler beendet.
  echo Details stehen, soweit verfuegbar, in logs\offline360-studio.log.
  pause
  exit /b 1
)
endlocal
'@ | Set-Content -LiteralPath $Destination -Encoding ascii
}

Push-Location $Repo
try {
    $Dirty = git status --porcelain
    if ($LASTEXITCODE -ne 0) { throw "Git-Status konnte nicht gelesen werden." }
    if ($Dirty) {
        throw "Der Git-Arbeitsbaum ist nicht sauber. Release-Build abgebrochen."
    }

    $Branch = git branch --show-current
    $Version = python -c "from core.version import __version__; print(__version__)"
    if ($LASTEXITCODE -ne 0 -or -not $Version) { throw "Version konnte nicht gelesen werden." }
    Write-Host "Branch: $Branch"
    Write-Host "Version: $Version"
    Write-Host "Modus: $Mode"

    Invoke-NamedStep "Python tests..." "Python tests OK" {
        Invoke-External python -m unittest discover -s tests
    }
    Invoke-NamedStep "JavaScript checks..." "JavaScript checks OK" {
        foreach ($Script in @("static/js/app.js", "static/js/admin.js", "static/js/portable_export.js")) {
            Invoke-External node --check $Script
        }
    }
    Invoke-NamedStep "Go tests..." "Go tests OK" {
        Push-Location "tools/portable-server"
        try {
            Invoke-External go test -mod=readonly ./...
        } finally { Pop-Location }
    }

    $TemporaryBuildDir = Join-Path ([IO.Path]::GetTempPath()) ("offline360-studio-release-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $TemporaryBuildDir | Out-Null
    & "tools/portable-server/build.ps1" -OutDir $TemporaryBuildDir
    if ($LASTEXITCODE -ne 0) { throw "portable-server Build fehlgeschlagen." }

    $TemporaryServer = Join-Path $TemporaryBuildDir "server.exe"
    $TemporaryServerHash = Join-Path $TemporaryBuildDir "server.exe.sha256"
    $ExpectedServerHash = ((Get-Content $TemporaryServerHash -Raw).Split()[0]).ToLowerInvariant()
    $ActualServerHash = (Get-FileHash $TemporaryServer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ExpectedServerHash -ne $ActualServerHash) { throw "portable-server SHA-256 stimmt nicht." }

    $BuildRoot = Join-Path $Repo "build\release"
    $PackageName = "Offline360Studio-$Version-win64-$Mode"
    $Stage = Join-Path $BuildRoot $PackageName
    $ResolvedBuildRoot = [IO.Path]::GetFullPath($BuildRoot).TrimEnd('\') + '\'
    $ResolvedStage = [IO.Path]::GetFullPath($Stage)
    if (-not $ResolvedStage.StartsWith($ResolvedBuildRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsicherer Release-Staging-Pfad: $ResolvedStage"
    }
    if (Test-Path $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
    New-Item -ItemType Directory -Force -Path `
        "$Stage\app\tools", "$Stage\data", "$Stage\media", "$Stage\logs", "$Stage\LICENSES" | Out-Null

    $AppItems = @(
        "app.py", "core", "static", "portable_viewer",
        "requirements.txt", "README.md", "docs", "LICENSE"
    )
    foreach ($Item in $AppItems) {
        Copy-Item -LiteralPath $Item -Destination "$Stage\app" -Recurse -Force
    }
    Copy-Item -LiteralPath "tools/portable-server" -Destination "$Stage\app\tools" -Recurse -Force
    Copy-Item -LiteralPath $TemporaryServer -Destination "$Stage\app\tools\portable-server\server.exe" -Force
    Copy-Item -LiteralPath $TemporaryServerHash -Destination "$Stage\app\tools\portable-server\server.exe.sha256" -Force
    Copy-Item "LICENSE" "$Stage\LICENSES\Offline360Studio.txt"
    Copy-Item "static\lib\three.LICENSE.txt" "$Stage\LICENSES\three.txt"
    Copy-Item "static\lib\leaflet\LICENSE.txt" "$Stage\LICENSES\leaflet.txt"
    Copy-Item "static\lib\maplibre\LICENSE.txt" "$Stage\LICENSES\maplibre.txt"
    Set-Content "$Stage\VERSION.txt" $Version -Encoding ascii

    if ($Mode -eq "standalone") {
        $PythonCachePath = Join-Path $CacheDir $EmbeddedPythonArchive
        $GetPipCachePath = Join-Path $CacheDir "get-pip.py"
        Get-VerifiedDownload $EmbeddedPythonUrl $PythonCachePath $EmbeddedPythonSha256
        Get-VerifiedDownload $GetPipUrl $GetPipCachePath $GetPipSha256

        $PythonRuntime = Join-Path $Stage "runtime\python"
        New-Item -ItemType Directory -Force -Path $PythonRuntime | Out-Null
        Expand-Archive -LiteralPath $PythonCachePath -DestinationPath $PythonRuntime

        $PthFile = @(Get-ChildItem -LiteralPath $PythonRuntime -Filter "python*._pth")
        if ($PthFile.Count -ne 1) {
            throw "Genau eine Embedded-Python _pth-Datei wurde erwartet."
        }
        @(
            "python312.zip"
            "."
            "Lib"
            "Lib\site-packages"
            "..\..\app"
            "import site"
        ) | Set-Content -LiteralPath $PthFile.FullName -Encoding ascii
        New-Item -ItemType Directory -Force -Path "$PythonRuntime\Lib\site-packages" | Out-Null

        $EmbeddedPython = Join-Path $PythonRuntime "python.exe"
        $PipCacheDir = Join-Path $CacheDir "pip"
        New-Item -ItemType Directory -Force -Path $PipCacheDir | Out-Null
        Invoke-External $EmbeddedPython $GetPipCachePath `
            --disable-pip-version-check `
            --no-warn-script-location `
            --cache-dir $PipCacheDir `
            "pip==$BuildPipVersion"
        Invoke-External $EmbeddedPython -m pip install `
            --disable-pip-version-check `
            --no-warn-script-location `
            --no-compile `
            --only-binary=:all: `
            --cache-dir $PipCacheDir `
            --requirement "$Stage\app\requirements.txt" `
            --target "$PythonRuntime\Lib\site-packages"
        Invoke-External $EmbeddedPython -c "import core, flask, werkzeug, PIL, click, colorama, exifread, itsdangerous, jinja2, markupsafe; print('Embedded-Python-Imports erfolgreich')"

        Get-ChildItem -LiteralPath "$PythonRuntime\Lib\site-packages" |
            Where-Object { $_.Name -eq "pip" -or $_.Name -like "pip-*.dist-info" } |
            Remove-Item -Recurse -Force
        if (Test-Path -LiteralPath "$PythonRuntime\Scripts") {
            Get-ChildItem -LiteralPath "$PythonRuntime\Scripts" -Filter "pip*.exe" |
                Remove-Item -Force
        }

        Write-StandaloneLauncher "$Stage\start-offline360-studio.bat"
        if (Test-Path "$PythonRuntime\LICENSE.txt") {
            Copy-Item "$PythonRuntime\LICENSE.txt" "$Stage\LICENSES\Python.txt"
        }
        @"
Embedded Python source
Version: $EmbeddedPythonVersion
Source: $EmbeddedPythonUrl
SHA-256: $EmbeddedPythonSha256
Signature metadata: $EmbeddedPythonUrl.sigstore

pip bootstrap (build only)
Source: $GetPipUrl
SHA-256: $GetPipSha256
Pinned build pip: $BuildPipVersion
"@ | Set-Content "$Stage\LICENSES\embedded-python-source.txt" -Encoding ascii
        @"
Offline360 Studio $Version - Windows Standalone-Paket

Start: start-offline360-studio.bat doppelklicken.
Python muss nicht installiert sein; die Runtime und alle Python-Pakete liegen lokal bei.
Die Anwendung arbeitet zur Laufzeit vollstaendig offline und installiert oder laedt nichts nach.
data\, media\ und logs\ liegen ausserhalb von app\ und bleiben bei einem App-Austausch erhalten.

Der Release-Build benoetigt Internet fuer Embedded Python, pip-Bootstrap und Dependencies,
wenn der verifizierte Cache unter tools\release\cache\ noch nicht gefuellt ist.
"@ | Set-Content "$Stage\README.txt" -Encoding ascii
    } else {
        Copy-Item "start-offline360-studio.bat" "$Stage\start-offline360-studio.bat"
        @"
Offline360 Studio $Version - Windows Developer-Paket

Voraussetzung: Python 3 mit den Paketen aus app\requirements.txt.
Start: start-offline360-studio.bat doppelklicken.
Dieses Paket installiert nichts und laedt keine Komponenten nach.
"@ | Set-Content "$Stage\README.txt" -Encoding ascii
    }

    $ZipPath = Join-Path $BuildRoot "$PackageName.zip"
    Invoke-External python "tools/release/package_release.py" $Stage $ZipPath

    $TrackedChanges = git status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0) { throw "Git-Status konnte nach dem Build nicht gelesen werden." }
    if ($TrackedChanges) {
        throw "Der Release-Build hat versionierte Dateien veraendert:`n$($TrackedChanges -join "`n")"
    }

    $ZipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$ZipPath.sha256" -Value "$ZipHash  $([IO.Path]::GetFileName($ZipPath))" -Encoding ascii
    Write-Host "Release-ZIP: $ZipPath"
    Write-Host "SHA-256: $ZipHash"
} finally {
    if ($TemporaryBuildDir -and (Test-Path -LiteralPath $TemporaryBuildDir)) {
        Remove-Item -LiteralPath $TemporaryBuildDir -Recurse -Force
    }
    Pop-Location
}


