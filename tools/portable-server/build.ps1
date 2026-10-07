param(
    [string]$OutDir = $PSScriptRoot,
    [switch]$Tidy
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Go {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & go @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "go $($Arguments -join ' ') ist mit Exitcode $LASTEXITCODE fehlgeschlagen."
    }
}

if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    Write-Error "Go ist nicht installiert oder nicht im PATH. Benötigt wird Go 1.25 oder neuer."
    exit 1
}

Push-Location $PSScriptRoot
try {
    if ($Tidy) {
        Invoke-Go -Arguments @("mod", "tidy")
    }
    Invoke-Go -Arguments @("test", "-mod=readonly", "./...")

    $ResolvedOutDir = [IO.Path]::GetFullPath($OutDir)
    New-Item -ItemType Directory -Force -Path $ResolvedOutDir | Out-Null
    $ServerPath = Join-Path $ResolvedOutDir "server.exe"
    $HashPath = Join-Path $ResolvedOutDir "server.exe.sha256"

    $env:CGO_ENABLED = "0"
    $env:GOOS = "windows"
    $env:GOARCH = "amd64"
    Invoke-Go -Arguments @(
        "build",
        "-mod=readonly",
        "-trimpath",
        "-ldflags=-s -w",
        "-o",
        $ServerPath,
        "."
    )

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ServerPath).Hash.ToLowerInvariant()
    Set-Content -LiteralPath $HashPath -Value "$hash  server.exe" -Encoding ascii
    $size = (Get-Item -LiteralPath $ServerPath).Length
    Write-Host "server.exe erstellt: $ServerPath ($size Bytes)"
    Write-Host "SHA-256: $hash"
}
catch {
    Write-Error $_
    exit 1
}
finally {
    Pop-Location
}

