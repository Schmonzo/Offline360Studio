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
    Invoke-Go -Arguments @("mod", "tidy")
    Invoke-Go -Arguments @("test", "./...")
    $env:CGO_ENABLED = "0"
    $env:GOOS = "windows"
    $env:GOARCH = "amd64"
    Invoke-Go -Arguments @(
        "build",
        "-trimpath",
        "-ldflags=-s -w",
        "-o",
        "server.exe",
        "."
    )

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath .\server.exe).Hash.ToLowerInvariant()
    Set-Content -LiteralPath .\server.exe.sha256 -Value "$hash  server.exe" -Encoding ascii
    $size = (Get-Item -LiteralPath .\server.exe).Length
    Write-Host "server.exe erstellt: $size Bytes"
    Write-Host "SHA-256: $hash"
}
catch {
    Write-Error $_
    exit 1
}
finally {
    Pop-Location
}
