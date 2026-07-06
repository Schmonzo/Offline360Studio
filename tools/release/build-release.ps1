$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$TemporaryBuildDir = $null
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
        go test -mod=readonly ./...
        if ($LASTEXITCODE -ne 0) { throw "Go-Tests fehlgeschlagen." }
    } finally { Pop-Location }

    $TemporaryBuildDir = Join-Path ([IO.Path]::GetTempPath()) ("panorama-studio-release-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $TemporaryBuildDir | Out-Null
    & "tools/portable-server/build.ps1" -OutDir $TemporaryBuildDir
    if ($LASTEXITCODE -ne 0) { throw "portable-server Build fehlgeschlagen." }

    $TemporaryServer = Join-Path $TemporaryBuildDir "server.exe"
    $TemporaryServerHash = Join-Path $TemporaryBuildDir "server.exe.sha256"
    $ExpectedHash = ((Get-Content $TemporaryServerHash -Raw).Split()[0]).ToLowerInvariant()
    $ActualHash = (Get-FileHash $TemporaryServer -Algorithm SHA256).Hash.ToLowerInvariant()
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
    New-Item -ItemType Directory -Force -Path "$Stage\app\tools", "$Stage\data", "$Stage\media", "$Stage\LICENSES" | Out-Null

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

    $ZipPath = Join-Path $BuildRoot "$PackageName.zip"
    python "tools/release/package_release.py" $Stage $ZipPath
    if ($LASTEXITCODE -ne 0) { throw "ZIP-Erstellung fehlgeschlagen." }

    $TrackedChanges = git status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0) { throw "Git-Status konnte nach dem Build nicht gelesen werden." }
    if ($TrackedChanges) {
        throw "Der Release-Build hat versionierte Dateien verändert:`n$($TrackedChanges -join "`n")"
    }

    $ZipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "Release-ZIP: $ZipPath"
    Write-Host "SHA-256: $ZipHash"
} finally {
    if ($TemporaryBuildDir -and (Test-Path -LiteralPath $TemporaryBuildDir)) {
        Remove-Item -LiteralPath $TemporaryBuildDir -Recurse -Force
    }
    Pop-Location
}
