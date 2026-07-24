# Offline360 Studio Portable Server

Der portable Server wird vollstÃ¤ndig aus dem Quellcode in diesem Verzeichnis
gebaut. Er verwendet fÃ¼r HTTP ausschlieÃŸlich die Go-Standardbibliothek und
fÃ¼r MBTiles den CGO-freien SQLite-Treiber `modernc.org/sqlite` in Version
`v1.53.0`. Es gibt keine installierte LaufzeitabhÃ¤ngigkeit.

## Voraussetzungen und reproduzierbarer Build

- Windows PowerShell 5.1 oder PowerShell 7
- Go 1.25 oder neuer im `PATH`

```powershell
cd tools\portable-server
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Das Skript fÃ¼hrt `go mod tidy`, `go test ./...` und anschlieÃŸend exakt diesen
Cross-Build aus:

```powershell
$env:CGO_ENABLED="0"
$env:GOOS="windows"
$env:GOARCH="amd64"
go build -trimpath -ldflags="-s -w" -o server.exe .
```

Danach stehen `server.exe` und `server.exe.sha256` in diesem Verzeichnis. Das
Skript zeigt GrÃ¶ÃŸe und SHA-256 an. Eine vorhandene Datei lÃ¤sst sich prÃ¼fen mit:

```powershell
Get-FileHash -Algorithm SHA256 .\server.exe
Get-Content .\server.exe.sha256
```

Der Exporter akzeptiert ausschlieÃŸlich diese `server.exe` zusammen mit ihrer
Hashdatei. Der SHA-256-Eintrag muss mit der EXE Ã¼bereinstimmen.

## Betrieb

Ohne Parameter ist der Webroot das Verzeichnis der EXE und der Server wÃ¤hlt
einen freien Port auf `127.0.0.1`. Nach erfolgreichem Listen Ã¶ffnet er den
Standardbrowser.

```powershell
.\server.exe
.\server.exe --port 8765
.\server.exe --root C:\Pfad\zur\portable-tour
```

Der Server bietet statische Dateien sowie folgende ausschlieÃŸlich aus
`tour.json` konfigurierte MBTiles-Endpunkte:

- `GET /api/maps/metadata`
- `GET /api/maps/tiles/{z}/{x}/{y}`
- `GET /api/maps/style.json`

## AbhÃ¤ngigkeiten und Lizenzen

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
- `github.com/ncruces/go-strftime aktuelle offline360-studio-Version`: MIT
- `github.com/remyoudompheng/bigfft`: BSD-3-Clause
- Der in `modernc.org/sqlite` portierte SQLite-Code: Public Domain

Transitive Modulversionen und deren kryptografische Go-PrÃ¼fsummen werden von
`go mod tidy` in `go.sum` festgehalten. Die Quell- und Lizenzinformationen
von `modernc.org/sqlite` befinden sich im Ã¶ffentlichen Modul-Repository:
<https://gitlab.com/cznic/sqlite>.

