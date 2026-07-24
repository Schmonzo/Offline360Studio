# Offline360 Studio Developer Guide

## v1-Stabilisierung

`core/version.py` ist die einzige Produktversionsquelle. App, Diagnose,
Exporter, Backup und Release-Build importieren beziehungsweise lesen sie.
`GET /api/version` liefert den unverÃ¤nderten Wert an den App-Header; das
Frontend ergÃ¤nzt ausschlieÃŸlich fÃ¼r die Anzeige ein `v`-PrÃ¤fix. Bei einem
fehlgeschlagenen Abruf zeigt der Header keine konkrete Fallback-Version.
Das Datenbankschema liegt unter `core/migrations/`; `migrate()` legt
`schema_migrations` an und fÃ¼hrt jede offene Migration in einer eigenen
Transaktion aus. Migrationen sind additiv, idempotent und datenerhaltend.
Automatische Downgrades sind nicht vorgesehen. Schema-Version 3 ist aktuell.

`startup_check()` prÃ¼ft Verzeichnisse, Schreibzugriff, Datenbank/Migrationen
und portable-server-Hash. Kritische Fehler verhindern den Start; ein fehlender
Exportserver ist eine Warnung. `OFFLINE360_STUDIO_RUNTIME_ROOT` setzt fÃ¼r Tests
die Wurzel von `data/`, `media/` und `logs/`.

`GET /api/diagnostics` liefert den gekÃ¼rzten Diagnosebericht,
`GET /api/diagnostics/report` denselben Inhalt als Download. Das Rotationslog
hat 5 MiB und fÃ¼nf Backups. Logs dÃ¼rfen keine Benutzerinhalte, Geheimnisse
oder vollstÃ¤ndigen sensitiven Pfade enthalten.

Backupformat 2 enthÃ¤lt App- und Schema-Version sowie SHA-256 fÃ¼r alle
Nutzdateien. Dateiliste, ZIP-Struktur und Hashes werden vor dem Entpacken
validiert. Neuere Schema-Versionen und manipulierte Archive werden abgelehnt.
Format 1 bleibt als Legacy-Import mit Struktur-, SQLite- und ZÃ¤hlerprÃ¼fung
zulÃ¤ssig.

Aus einem sauberen Checkout:

```powershell
powershell -ExecutionPolicy Bypass -File tools/release/build-release.ps1 -Mode dev
powershell -ExecutionPolicy Bypass -File tools/release/build-release.ps1 -Mode standalone
python tools/smoke_test.py
```

Der Release-Build testet Python, JavaScript und Go, baut und verifiziert den
lokalen Go-Server in einem temporÃ¤ren Ausgabeverzeichnis und erzeugt unter
`build/release/` wahlweise ein deterministisches Developer- oder
Standalone-ZIP. `-Mode dev` ist der Standard und behÃ¤lt die externe
Python-Voraussetzung. `-Mode standalone` entpackt das offizielle
CPython-3.12.10-Embeddable-Paket nach `runtime/python`, aktiviert dessen
lokales `Lib/site-packages`, bootstrapped das SHA-256-geprÃ¼fte `get-pip.py`
nur im Build und installiert die gepinnten Requirements in die Runtime.
AnschlieÃŸend prÃ¼ft die eingebettete Runtime die zentralen Imports und der
Build entfernt pip wieder aus dem Endnutzerpaket.

Der Download-Cache liegt unter `tools/release/cache/`. Eine Datei wird nur bei
passendem fest dokumentiertem SHA-256 wiederverwendet; ein beschÃ¤digter Cache
wird verworfen und erneut geladen. Der Cache, Staging-Ausgaben und Release-ZIPs
sind ignoriert. Der Build verÃ¤ndert keine versionierten Dateien und hÃ¤lt den
Arbeitsbaum sauber. Die fÃ¼r den portablen Tour-Export benÃ¶tigten
`tools/portable-server/server.exe` und `server.exe.sha256` bleiben versioniert,
werden vom Release-Build aber nicht Ã¼berschrieben. Der Smoke-Test startet die
echte App auf einem freien Port mit temporÃ¤rer
Laufzeitwurzel und prÃ¼ft Startseite, Projekte, Diagnose, Backup und Portable
Export.

Im Paket setzt das Startskript `OFFLINE360_STUDIO_RUNTIME_ROOT` auf die
Paketwurzel. Dadurch verwenden Migrationen, Backup/Restore, MBTiles, Medien
und Logs die Verzeichnisse `data/`, `media/` und `logs/` auÃŸerhalb von
`app/`. Es gibt beim Start keine Installations-, pip- oder Downloadlogik.

Bekannte v1.0-Risiken sind der fehlende Installer, systemabhÃ¤ngige
WebGL-/Codec-UnterstÃ¼tzung und temporÃ¤rer Speicherbedarf groÃŸer Backups oder
Karten. Das Standalone-Paket unterstÃ¼tzt Windows x64; der Standalone-Build
benÃ¶tigt bei leerem Cache Netzwerkzugriff.

## Portabler Tour-Export

`POST /api/export/portable-tour` validiert den JSON-Body und delegiert an
`core/portable_export.py`. Der Exporter liest ausschlieÃŸlich das angeforderte
Projekt und dessen geordnete `project_media`-Zuordnungen. Hotspots werden nur
fÃ¼r exportierte Quellmedien Ã¼bernommen; Panorama-Ziele auÃŸerhalb des
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

Die Antwort ist ein gestreamter ZIP-Download. Das temporÃ¤re Archiv wird im
Generator-`finally` sowie beim SchlieÃŸen der Response entfernt. Der statische
Viewer stammt aus `portable_viewer/`; Drittbibliotheken werden ausschlieÃŸlich
aus `static/lib/` in das Archiv kopiert. Dadurch bleibt der Viewer unabhÃ¤ngig
von Flask, ohne eine zweite Kopie der Bibliotheken im Repository zu pflegen.

Archivstruktur:

```text
portable-tour/
  index.html
  tour.json
  README.txt
  VERSION.txt
  start-tour.bat
  server.exe
  assets/
    css/  js/  lib/
    media/  thumbnails/
    maps/  tracks/
```

### Sicherheitsmodell

- Die Projekt-ID wird serverseitig auf Existenz geprÃ¼ft.
- Medien stammen ausschlieÃŸlich aus dem zum Typ passenden
  `media/photos`- oder `media/videos`-Verzeichnis.
- Vorschaubilder und Karten stammen ausschlieÃŸlich aus `media/thumbs`
  beziehungsweise `data/maps`.
- Absolute Pfade und `..`-Segmente werden abgelehnt. Nach AuflÃ¶sung von
  symbolischen Links muss der Pfad weiterhin innerhalb des erlaubten
  Verzeichnisses liegen.
- Datenbankpfade werden nie als ZIP-Zielnamen verwendet. Archivnamen bestehen
  aus Datenbank-ID und bereinigtem Basisnamen.
- Fehlende oder unsichere Dateien werden protokolliert, im Manifest als nicht
  verfÃ¼gbar markiert und nicht kopiert.
- `tour.json` enthÃ¤lt nur relative POSIX-Pfade.
- GPX werden aus den zum Projekt gehÃ¶renden Datenbankzeilen rekonstruiert;
  Tracks anderer Projekte werden nicht exportiert.

### Portabler Server und Viewer

Der Viewer lÃ¤dt `tour.json` Ã¼ber den eigenen lokalen HTTP-Server und rendert Fotos
mit Marzipano, Videos sowie stereografische Projektionen mit Three.js und
Kartenoverlays mit Leaflet. MapLibre wird lokal mitgeliefert. Bei `file://`
zeigt `index.html` nur den Start-Hinweis.

Der Go-Quellcode liegt unter `tools/portable-server/`. Der Server verwendet
fÃ¼r HTTP ausschlieÃŸlich die Standardbibliothek und fÃ¼r SQLite
`modernc.org/sqlite v1.53.0` (BSD-3-Clause; SQLite-Anteile Public Domain).
Die AbhÃ¤ngigkeit ist CGO-frei. `build.ps1` prÃ¼ft das Modul unverÃ¤ndert mit
`-mod=readonly`, fÃ¼hrt Tests aus, setzt `CGO_ENABLED=0`, baut eine
Windows-amd64-EXE mit `-trimpath` und entfernten Debugsymbolen und schreibt
`server.exe.sha256`. Mit `-OutDir <path>` werden EXE und Hash auÃŸerhalb des
Quellordners erzeugt; `-Tidy` fÃ¼hrt bei bewusster AbhÃ¤ngigkeitspflege vorab
`go mod tidy` aus.

Der Exporter kopiert ausschlieÃŸlich
`tools/portable-server/server.exe` zusammen mit `server.exe.sha256`. Der Hash
wird vor jedem Export geprÃ¼ft. Fehlt eine Datei oder stimmt der Hash nicht,
wird kein Archiv erzeugt. Die vollstÃ¤ndige Build- und Lizenzdokumentation steht in
`tools/portable-server/README.md`.

Der Server bindet nur `127.0.0.1`, wÃ¤hlt standardmÃ¤ÃŸig einen dynamischen Port,
Ã¶ffnet danach den Standardbrowser und beendet sich sauber bei Strg+C. Der
Webroot ist auf das EXE-Verzeichnis begrenzt; aufgelÃ¶ste Symlinks und
Junctions dÃ¼rfen diesen nicht verlassen. Verzeichnisauflistung ist
deaktiviert. Sicherheits- und Cacheheader werden explizit gesetzt.

MBTiles werden unverÃ¤ndert exportiert. Der Server liest ausschlieÃŸlich den
relativen Kartenpfad unter `assets/maps/` aus `tour.json`; Requests kÃ¶nnen
keinen Dateipfad vorgeben. UnterstÃ¼tzt werden Flat-`tiles` und normalisierte
`map`/`images`-Schemas, Rasterformate PNG/JPEG/WebP sowie PBF/MVT mit
TMS-zu-XYZ-Konvertierung und gzip-Kennzeichnung. Endpunkte:

- `GET /api/maps/metadata`
- `GET /api/maps/tiles/{z}/{x}/{y}`
- `GET /api/maps/style.json`

Leaflet verwendet den Tile-Endpunkt fÃ¼r Rasterkarten. MapLibre lÃ¤dt den
lokal generierten Vector-Stil. Dieser enthÃ¤lt keine externen Glyph-, Sprite-,
Font- oder Style-URLs. GPS-Marker und GPX-Tracks liegen Ã¼ber beiden
Kartentypen; ohne Karte bleibt der neutrale Hintergrund verfÃ¼gbar.

## Offline-MBTiles

Die Implementierung liegt in `core/mbtiles.py`. Imports werden bis maximal
5 GB in eine temporÃ¤re Datei unter `data/maps/` geschrieben, read-only als
SQLite geprÃ¼ft und danach mit `os.replace` atomar auf einen UUID-Dateinamen
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

`map_sources` enthÃ¤lt ausschlieÃŸlich Metadaten. Die partielle eindeutige
SQLite-Indizierung auf `active = 1` sichert zusÃ¤tzlich zur API-Transaktion,
dass hÃ¶chstens eine Quelle aktiv ist.

Bei PBF-Kacheln prÃ¼ft der Tile-Endpunkt die gzip-Magic-Bytes `1f 8b`,
validiert die komprimierten Daten innerhalb der GrÃ¶ÃŸenlimits und setzt nur
dann `Content-Encoding: gzip`. Unkomprimierte PBF-Kacheln werden ohne
Encoding als `application/vnd.mapbox-vector-tile` ausgeliefert.

`metadata.json` wird defensiv gelesen. Erkannte `vector_layers` werden
gespeichert und in einen lokalen MapLibre-Style mit Background-, Fill-,
Line- und Circle-Layern umgesetzt. Der Style enthÃ¤lt absichtlich weder
Glyph- noch Sprite-URLs; Beschriftungen sind daher nicht Bestandteil des
automatischen Basisstils. MapLibre GL JS 5.24.0 und seine BSD-3-Clause-Lizenz
liegen unter `static/lib/maplibre/`.

Backups setzen im Manifest `includes_maps`. Nur bei `true` werden
serverseitige `.mbtiles`-Dateien unter `maps/` archiviert, validiert und beim
Restore zusammen mit dem Kartenverzeichnis atomar ausgetauscht.

PrÃ¼fungen:

```powershell
python -m unittest discover -s tests
python -m py_compile app.py core\mbtiles.py core\backup.py
node --check static\js\map.js
node --check static\js\offline_maps.js
node --check static\js\backup.js
git diff --check
```

## Ziel

Offline360 Studio ist eine lokale Offline-Anwendung zur PrÃ¤sentation und Verwaltung von 360Â°-Fotos und 360Â°-Videos.

## Branch-Modell

- `main`: stabile Releases
- `develop`: laufende Entwicklung
- `feature/*`: einzelne Arbeitspakete

## Lokaler Start

```powershell
cd C:\path\to\Offline360Studio
python app.py
```

## 360Â°-Video-Viewer

MP4-Dateien unter `media/videos` werden als equirektangulare 360Â°-Videos
gerendert. Der Viewer verwendet den lokalen Three.js-Modul-Build in
`static/lib`; zur Laufzeit werden keine Dateien von einem CDN geladen.

Steuerung:

- Ziehen oder Wischen: Blickrichtung Ã¤ndern
- Mausrad oder Pinch: zoomen
- Pfeiltasten: Blickrichtung Ã¤ndern
- Leertaste: Wiedergabe/Pause
- `+`, `-` und `Home`: Zoom beziehungsweise Ansicht zurÃ¼cksetzen

Der Browser muss WebGL sowie den im MP4 verwendeten Video- und Audio-Codec
unterstÃ¼tzen.

