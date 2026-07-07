# Panorama Studio Portable Server

Der portable Server wird vollständig aus dem Quellcode in diesem Verzeichnis
gebaut. Er verwendet für HTTP ausschließlich die Go-Standardbibliothek und
für MBTiles den CGO-freien SQLite-Treiber `modernc.org/sqlite` in Version
`v1.53.0`. Es gibt keine installierte Laufzeitabhängigkeit.

## Voraussetzungen und reproduzierbarer Build

- Windows PowerShell 5.1 oder PowerShell 7
- Go 1.25 oder neuer im `PATH`

```powershell
cd tools\portable-server
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Das Skript führt `go mod tidy`, `go test ./...` und anschließend exakt diesen
Cross-Build aus:

```powershell
$env:CGO_ENABLED="0"
$env:GOOS="windows"
$env:GOARCH="amd64"
go build -trimpath -ldflags="-s -w" -o server.exe .
```

Danach stehen `server.exe` und `server.exe.sha256` in diesem Verzeichnis. Das
Skript zeigt Größe und SHA-256 an. Eine vorhandene Datei lässt sich prüfen mit:

```powershell
Get-FileHash -Algorithm SHA256 .\server.exe
Get-Content .\server.exe.sha256
```

Der Exporter akzeptiert ausschließlich diese `server.exe` zusammen mit ihrer
Hashdatei. Der SHA-256-Eintrag muss mit der EXE übereinstimmen.

## Betrieb

Ohne Parameter ist der Webroot das Verzeichnis der EXE und der Server wählt
einen freien Port auf `127.0.0.1`. Nach erfolgreichem Listen öffnet er den
Standardbrowser.

```powershell
.\server.exe
.\server.exe --port 8765
.\server.exe --root C:\Pfad\zur\portable-tour
```

Der Server bietet statische Dateien sowie folgende ausschließlich aus
`tour.json` konfigurierte MBTiles-Endpunkte:

- `GET /api/maps/metadata`
- `GET /api/maps/tiles/{z}/{x}/{y}`
- `GET /api/maps/style.json`

## Abhängigkeiten und Lizenzen

- Go-Standardbibliothek: Go-Projektlizenz (BSD-3-Clause)
- `modernc.org/sqlite v1.53.0`: BSD-3-Clause
- `modernc.org/libc v1.73.4`: BSD-3-Clause
- `modernc.org/fileutil v1.4.0`: BSD-3-Clause
- `modernc.org/mathutil v1.7.1`: BSD-3-Clause
- `modernc.org/memory v1.11.0`: BSD-3-Clause
- `golang.org/x/sys v0.44.0`: BSD-3-Clause
- `github.com/google/pprof`: Apache-2.0
- `github.com/google/uuid v1.6.0`: BSD-3-Clause
- `github.com/dustin/go-humanize v<version>`: MIT
- `github.com/mattn/go-isatty v0.0.20`: MIT
- `github.com/ncruces/go-strftime aktuelle Panorama-Studio-Version`: MIT
- `github.com/remyoudompheng/bigfft`: BSD-3-Clause
- Der in `modernc.org/sqlite` portierte SQLite-Code: Public Domain

Transitive Modulversionen und deren kryptografische Go-Prüfsummen werden von
`go mod tidy` in `go.sum` festgehalten. Die Quell- und Lizenzinformationen
von `modernc.org/sqlite` befinden sich im öffentlichen Modul-Repository:
<https://gitlab.com/cznic/sqlite>.
