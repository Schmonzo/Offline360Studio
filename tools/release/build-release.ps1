$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
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
    Write-Host "Pakettyp: Developer-Paket (Python 3 und requirements.txt erforderlich)"

    python -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw "Python-Tests fehlgeschlagen." }
    foreach ($Script in @("static/js/app.js", "static/js/admin.js", "static/js/portable_export.js")) {
        node --check $Script
        if ($LASTEXITCODE -ne 0) { throw "JavaScript-Syntaxprüfung fehlgeschlagen: $Script" }
    }
    Push-Location "tools/portable-server"
    try {
        go test ./...
        if ($LASTEXITCODE -ne 0) { throw "Go-Tests fehlgeschlagen." }
    } finally { Pop-Location }
    & "tools/portable-server/build.ps1"
    if ($LASTEXITCODE -ne 0) { throw "portable-server Build fehlgeschlagen." }

    $ExpectedHash = ((Get-Content "tools/portable-server/server.exe.sha256" -Raw).Split()[0]).ToLowerInvariant()
    $ActualHash = (Get-FileHash "tools/portable-server/server.exe" -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ExpectedHash -ne $ActualHash) { throw "portable-server SHA-256 stimmt nicht." }

    $BuildRoot = Join-Path $Repo "build\release"
    $PackageName = "PanoramaStudio-$Version-win64"
    $Stage = Join-Path $BuildRoot $PackageName
    $ResolvedBuildRoot = [IO.Path]::GetFullPath($BuildRoot).TrimEnd('\') + '\'
    $ResolvedStage = [IO.Path]::GetFullPath($Stage)
    if (-not $ResolvedStage.StartsWith($ResolvedBuildRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsicherer Release-Staging-Pfad: $ResolvedStage"
    }
    if (Test-Path $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
    New-Item -ItemType Directory -Force -Path "$Stage\app", "$Stage\data", "$Stage\media", "$Stage\LICENSES" | Out-Null

    $AppItems = @(
        "app.py", "core", "static", "portable_viewer", "tools/portable-server",
        "requirements.txt", "README.md", "docs", "LICENSE"
    )
    foreach ($Item in $AppItems) {
        Copy-Item -LiteralPath $Item -Destination "$Stage\app" -Recurse -Force
    }
    Copy-Item "start-panorama-studio.bat" "$Stage\start-panorama-studio.bat"
    Copy-Item "LICENSE" "$Stage\LICENSES\PanoramaStudio.txt"
    Copy-Item "static\lib\three.LICENSE.txt" "$Stage\LICENSES\three.txt"
    Copy-Item "static\lib\leaflet\LICENSE.txt" "$Stage\LICENSES\leaflet.txt"
    Copy-Item "static\lib\maplibre\LICENSE.txt" "$Stage\LICENSES\maplibre.txt"
    Set-Content "$Stage\VERSION.txt" $Version -Encoding ascii
    @"
Panorama Studio $Version – Windows Developer-Paket

Voraussetzung: Python 3 mit den Paketen aus app\requirements.txt.
Start: start-panorama-studio.bat doppelklicken.
Dieses Paket installiert nichts und lädt keine Komponenten nach.
Eine eingebettete Python-Runtime ist für die nächste Stabilisierungsetappe geplant.
"@ | Set-Content "$Stage\README.txt" -Encoding utf8

    python "tools/release/package_release.py" $Stage (Join-Path $BuildRoot "$PackageName.zip")
    if ($LASTEXITCODE -ne 0) { throw "ZIP-Erstellung fehlgeschlagen." }
} finally {
    Pop-Location
}
