# Panorama Studio Developer Guide

## v1-Stabilisierung

`core/version.py` ist die einzige Produktversionsquelle. App, Diagnose,
Exporter, Backup und Release-Build importieren beziehungsweise lesen sie.
Das Datenbankschema liegt unter `core/migrations/`; `migrate()` legt
`schema_migrations` an und führt jede offene Migration in einer eigenen
Transaktion aus. Migrationen sind additiv, idempotent und datenerhaltend.
Automatische Downgrades sind nicht vorgesehen. Schema-Version 3 ist aktuell.

`startup_check()` prüft Verzeichnisse, Schreibzugriff, Datenbank/Migrationen
und portable-server-Hash. Kritische Fehler verhindern den Start; ein fehlender
Exportserver ist eine Warnung. `PANORAMA_STUDIO_RUNTIME_ROOT` setzt für Tests
die Wurzel von `data/`, `media/` und `logs/`.

`GET /api/diagnostics` liefert den gekürzten Diagnosebericht,
`GET /api/diagnostics/report` denselben Inhalt als Download. Das Rotationslog
hat 5 MiB und fünf Backups. Logs dürfen keine Benutzerinhalte, Geheimnisse
oder vollständigen sensitiven Pfade enthalten.

Backupformat 2 enthält App- und Schema-Version sowie SHA-256 für alle
Nutzdateien. Dateiliste, ZIP-Struktur und Hashes werden vor dem Entpacken
validiert. Neuere Schema-Versionen und manipulierte Archive werden abgelehnt.
Format 1 bleibt als Legacy-Import mit Struktur-, SQLite- und Zählerprüfung
zulässig.

Aus einem sauberen Checkout:

```powershell
powershell -ExecutionPolicy Bypass -File tools/release/build-release.ps1
python tools/smoke_test.py
```

Der Release-Build testet Python, JavaScript und Go, baut und verifiziert den
lokalen Go-Server in einem temporären Ausgabeverzeichnis und erzeugt ein
deterministisches Developer-ZIP unter `build/release/`. Die Ausgabe ist
ignoriert; der Build verändert keine versionierten Dateien und hält den
Arbeitsbaum sauber. Die für den portablen Tour-Export benötigten
`tools/portable-server/server.exe` und `server.exe.sha256` bleiben versioniert,
werden vom Release-Build aber nicht überschrieben. Der Smoke-Test startet die
echte App auf einem freien Port mit temporärer
Laufzeitwurzel und prüft Startseite, Projekte, Diagnose, Backup und Portable
Export.

Bekannte v1.0-Risiken sind die externe Python-3-Voraussetzung, der fehlende
Installer, systemabhängige WebGL-/Codec-Unterstützung und temporärer
Speicherbedarf großer Backups oder Karten. Nächste Etappe ist Embedded Python
oder ein Windows-Installer.

## Portabler Tour-Export

`POST /api/export/portable-tour` validiert den JSON-Body und delegiert an
`core/portable_export.py`. Der Exporter liest ausschließlich das angeforderte
Projekt und dessen geordnete `project_media`-Zuordnungen. Hotspots werden nur
für exportierte Quellmedien übernommen; Panorama-Ziele außerhalb des
Exportumfangs werden verworfen. Videos, die aktive Offline-Karte und
projektgebundene GPX-Tracks sind separat schaltbar.

Beispiel:

```json
{
  "project_id": 1,
  "filename": "meine-tour",
  "include_videos": true,
  "include_map": true,
  "include_tracks": true
}
```

Die Antwort ist ein gestreamter ZIP-Download. Das temporäre Archiv wird im
Generator-`finally` sowie beim Schließen der Response entfernt. Der statische
Viewer stammt aus `portable_viewer/`; Drittbibliotheken werden ausschließlich
aus `static/lib/` in das Archiv kopiert. Dadurch bleibt der Viewer unabhängig
von Flask, ohne eine zweite Kopie der Bibliotheken im Repository zu pflegen.

Archivstruktur:

```text
portable-tour/
  index.html
  tour.json
  README.txt
  start-tour.bat
  server.exe
  assets/
    css/  js/  lib/
    media/  thumbnails/
    maps/  tracks/
```

### Sicherheitsmodell

- Die Projekt-ID wird serverseitig auf Existenz geprüft.
- Medien stammen ausschließlich aus dem zum Typ passenden
  `media/photos`- oder `media/videos`-Verzeichnis.
- Vorschaubilder und Karten stammen ausschließlich aus `media/thumbs`
  beziehungsweise `data/maps`.
- Absolute Pfade und `..`-Segmente werden abgelehnt. Nach Auflösung von
  symbolischen Links muss der Pfad weiterhin innerhalb des erlaubten
  Verzeichnisses liegen.
- Datenbankpfade werden nie als ZIP-Zielnamen verwendet. Archivnamen bestehen
  aus Datenbank-ID und bereinigtem Basisnamen.
- Fehlende oder unsichere Dateien werden protokolliert, im Manifest als nicht
  verfügbar markiert und nicht kopiert.
- `tour.json` enthält nur relative POSIX-Pfade.
- GPX werden aus den zum Projekt gehörenden Datenbankzeilen rekonstruiert;
  Tracks anderer Projekte werden nicht exportiert.

### Portabler Server und Viewer

Der Viewer lädt `tour.json` über den eigenen lokalen HTTP-Server und rendert Fotos
mit Marzipano, Videos sowie stereografische Projektionen mit Three.js und
Kartenoverlays mit Leaflet. MapLibre wird lokal mitgeliefert. Bei `file://`
zeigt `index.html` nur den Start-Hinweis.

Der Go-Quellcode liegt unter `tools/portable-server/`. Der Server verwendet
für HTTP ausschließlich die Standardbibliothek und für SQLite
`modernc.org/sqlite v1.53.0` (BSD-3-Clause; SQLite-Anteile Public Domain).
Die Abhängigkeit ist CGO-frei. `build.ps1` prüft das Modul unverändert mit
`-mod=readonly`, führt Tests aus, setzt `CGO_ENABLED=0`, baut eine
Windows-amd64-EXE mit `-trimpath` und entfernten Debugsymbolen und schreibt
`server.exe.sha256`. Mit `-OutDir <path>` werden EXE und Hash außerhalb des
Quellordners erzeugt; `-Tidy` führt bei bewusster Abhängigkeitspflege vorab
`go mod tidy` aus.

Der Exporter kopiert ausschließlich
`tools/portable-server/server.exe` zusammen mit `server.exe.sha256`. Der Hash
wird vor jedem Export geprüft. Fehlt eine Datei oder stimmt der Hash nicht,
wird kein Archiv erzeugt. Die vollständige Build- und Lizenzdokumentation steht in
`tools/portable-server/README.md`.

Der Server bindet nur `127.0.0.1`, wählt standardmäßig einen dynamischen Port,
öffnet danach den Standardbrowser und beendet sich sauber bei Strg+C. Der
Webroot ist auf das EXE-Verzeichnis begrenzt; aufgelöste Symlinks und
Junctions dürfen diesen nicht verlassen. Verzeichnisauflistung ist
deaktiviert. Sicherheits- und Cacheheader werden explizit gesetzt.

MBTiles werden unverändert exportiert. Der Server liest ausschließlich den
relativen Kartenpfad unter `assets/maps/` aus `tour.json`; Requests können
keinen Dateipfad vorgeben. Unterstützt werden Flat-`tiles` und normalisierte
`map`/`images`-Schemas, Rasterformate PNG/JPEG/WebP sowie PBF/MVT mit
TMS-zu-XYZ-Konvertierung und gzip-Kennzeichnung. Endpunkte:

- `GET /api/maps/metadata`
- `GET /api/maps/tiles/{z}/{x}/{y}`
- `GET /api/maps/style.json`

Leaflet verwendet den Tile-Endpunkt für Rasterkarten. MapLibre lädt den
lokal generierten Vector-Stil. Dieser enthält keine externen Glyph-, Sprite-,
Font- oder Style-URLs. GPS-Marker und GPX-Tracks liegen über beiden
Kartentypen; ohne Karte bleibt der neutrale Hintergrund verfügbar.

## Offline-MBTiles

Die Implementierung liegt in `core/mbtiles.py`. Imports werden bis maximal
5 GB in eine temporäre Datei unter `data/maps/` geschrieben, read-only als
SQLite geprüft und danach mit `os.replace` atomar auf einen UUID-Dateinamen
verschoben. Der vom Client gelieferte Dateiname wird nie als Speicherpfad
verwendet.

Validiert werden `metadata`, ein Flat-`tiles`- oder normalisiertes
`map`/`images`-Schema, mindestens eine Kachel und `format` aus `png`, `jpg`,
`jpeg`, `webp`, `pbf` oder `mvt`. `map_type` speichert die daraus abgeleitete
Renderer-Art `raster` oder `vector`. Alle Lesezugriffe auf MBTiles verwenden
SQLite-URI-Modus `mode=ro`.

MBTiles speichert Zeilen im TMS-Schema, Leaflet und MapLibre fragen XYZ ab. Der
Tile-Endpunkt rechnet deshalb:

```text
tms_y = (2 ** z - 1) - y
```

`map_sources` enthält ausschließlich Metadaten. Die partielle eindeutige
SQLite-Indizierung auf `active = 1` sichert zusätzlich zur API-Transaktion,
dass höchstens eine Quelle aktiv ist.

Bei PBF-Kacheln prüft der Tile-Endpunkt die gzip-Magic-Bytes `1f 8b`,
validiert die komprimierten Daten innerhalb der Größenlimits und setzt nur
dann `Content-Encoding: gzip`. Unkomprimierte PBF-Kacheln werden ohne
Encoding als `application/vnd.mapbox-vector-tile` ausgeliefert.

`metadata.json` wird defensiv gelesen. Erkannte `vector_layers` werden
gespeichert und in einen lokalen MapLibre-Style mit Background-, Fill-,
Line- und Circle-Layern umgesetzt. Der Style enthält absichtlich weder
Glyph- noch Sprite-URLs; Beschriftungen sind daher nicht Bestandteil des
automatischen Basisstils. MapLibre GL JS 5.24.0 und seine BSD-3-Clause-Lizenz
liegen unter `static/lib/maplibre/`.

Backups setzen im Manifest `includes_maps`. Nur bei `true` werden
serverseitige `.mbtiles`-Dateien unter `maps/` archiviert, validiert und beim
Restore zusammen mit dem Kartenverzeichnis atomar ausgetauscht.

Prüfungen:

```powershell
python -m unittest discover -s tests
python -m py_compile app.py core\mbtiles.py core\backup.py
node --check static\js\map.js
node --check static\js\offline_maps.js
node --check static\js\backup.js
git diff --check
```

## Ziel

Panorama Studio ist eine lokale Offline-Anwendung zur Präsentation und Verwaltung von 360°-Fotos und 360°-Videos.

## Branch-Modell

- `main`: stabile Releases
- `develop`: laufende Entwicklung
- `feature/*`: einzelne Arbeitspakete

## Lokaler Start

```powershell
cd C:\PanoramaStudioRepo
python app.py
```

## 360°-Video-Viewer

MP4-Dateien unter `media/videos` werden als equirektangulare 360°-Videos
gerendert. Der Viewer verwendet den lokalen Three.js-Modul-Build in
`static/lib`; zur Laufzeit werden keine Dateien von einem CDN geladen.

Steuerung:

- Ziehen oder Wischen: Blickrichtung ändern
- Mausrad oder Pinch: zoomen
- Pfeiltasten: Blickrichtung ändern
- Leertaste: Wiedergabe/Pause
- `+`, `-` und `Home`: Zoom beziehungsweise Ansicht zurücksetzen

Der Browser muss WebGL sowie den im MP4 verwendeten Video- und Audio-Codec
unterstützen.
