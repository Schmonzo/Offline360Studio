# Panorama Studio

Die aktuelle Produktversion wird ausschließlich in `core/version.py` gepflegt.
App, Admin-Diagnose, Exporte, Backups und Release-Build lesen diese Quelle.

## Stabilisierung und Windows-Betrieb

Beim Start werden Daten- und Medienverzeichnisse, Schreibrechte, Datenbank,
Migrationen und der SHA-256-Hash des portablen Servers geprüft. Kritische
Fehler beenden den Start verständlich; ein fehlender portabler Server erzeugt
eine Warnung. Strukturierte Logs rotieren unter
`logs/panorama-studio.log` (5 × 5 MiB).

Der Adminbereich bietet eine Systemdiagnose mit Laufzeitversionen,
Schema-Version, gekürzten Pfaden, Speicherplatz, Objektzählern,
Schreibrechtstatus, Serverstatus und letzter Backup-Zeit. Der Bericht steht
auch unter `GET /api/diagnostics/report` als JSON bereit.

`start-panorama-studio.bat` arbeitet ohne Downloads oder automatische
Installation. Das aktuelle Windows-ZIP ist ein Developer-Paket: Python 3 und
die Pakete aus `requirements.txt` müssen vorhanden sein. Embedded Python oder
ein Installer ist die nächste Etappe.

## Portabler Offline-Tour-Export

Im Adminbereich erzeugt **Portable Tour exportieren** aus einem Projekt eine
eigenständige ZIP-Datei. Sie enthält Projektdaten als `tour.json`, einen
separaten statischen Viewer, lokale JavaScript-/CSS-Bibliotheken und die
ausgewählten Medien, GPX-Tracks und MBTiles. Der Viewer verwendet weder Flask
noch die Panorama-Studio-Datenbank und führt keine CDN-, API- oder sonstigen
Netzwerkzugriffe aus.

```text
portable-tour/
  index.html
  tour.json
  README.txt
  start-tour.bat
  server.exe
  assets/
    css/
    js/
    lib/
    media/
    thumbnails/
    maps/
    tracks/
```

Das direkte Öffnen von `index.html` über `file://` zeigt absichtlich einen
Hinweis, weil Browser lokale `fetch()`- und Modulzugriffe blockieren.
`start-tour.bat` startet die mitexportierte `server.exe`; der ausschließlich
auf `127.0.0.1` gebundene Server wählt einen freien Port und öffnet danach
den Standardbrowser. Die EXE wird reproduzierbar aus
`tools/portable-server/` gebaut. Fehlt sie, bricht der Export mit einem
Hinweis auf `build.ps1` ab. Beim Export erfolgen keine Downloads.

Fotos, 360°-Videos, Startansichten, Panorama- und Info-Hotspots,
Tiny Planet/Rabbit Hole, Galerie, Tastatursteuerung, GPS-Marker und
GPX-Linien werden vom statischen Viewer unterstützt. Raster- und
Vector-MBTiles werden einschließlich Metadaten exportiert. Der portable
Server liefert Flat- und normalisierte MBTiles über lokale Endpunkte aus.
Leaflet rendert Rasterkarten, MapLibre Vektorkarten; der lokale Vector-Stil
verwendet keine externen Fonts, Glyphs, Sprites oder Styles.

## Offline-Karten

Im Admin-Bereich lassen sich Raster-MBTiles (PNG, JPEG, WebP) und
Vector-MBTiles (PBF/MVT) als lokale Basiskarte importieren. Flat- und
normalisierte `map`/`images`-Schemas werden unterstützt. Die maximale
Importgröße beträgt 5 GB.

Die Dateien bleiben separat unter `data/maps/`; in
`data/panorama_studio.db` stehen nur Metadaten und der serverseitig erzeugte
Dateiname. Ohne aktive oder mit einer nicht verfügbaren Kartenquelle zeigt
die Karte weiterhin den neutralen Hintergrund. Rasterkarten, Medienmarker
und GPX verwenden Leaflet. Vektorkarten werden mit dem lokal eingebundenen
MapLibre GL JS gerendert; der automatisch erzeugte Basisstil benötigt keine
Fonts, Sprites oder externen URLs.

API:

- `GET /api/maps/sources`
- `POST /api/maps/sources/import` mit Multipart-Feld `file`
- `PATCH /api/maps/sources/<id>` mit `name` und/oder `active`
- `DELETE /api/maps/sources/<id>`
- `GET /api/maps/active`
- `GET /api/maps/tiles/<id>/<z>/<x>/<y>`
- `GET /api/maps/sources/<id>/style.json`

## Backup & Restore

Der Admin-Bereich kann lokale Projektdaten als ZIP exportieren und wiederherstellen.
Ein Backup enthält:

- `manifest.json` mit App-, Schema- und Formatversion sowie SHA-256 jeder Datei
- `README.txt`
- `panorama_studio.db` als konsistente SQLite-Kopie
- unterstützte Konfigurationsdateien aus `data/config/` unter `config/`
- optional Fotos, Videos und Vorschaubilder unter `media/`
- optional Offline-Karten unter `maps/`

`media_count` und `project_count` geben die Anzahl der Datensätze in der
SQLite-Datenbank an. `includes_media` zeigt an, ob auch die Mediendateien
enthalten sind.

`POST /api/backup/export` erwartet beispielsweise
`{"includes_media": false, "includes_maps": false}`.
`POST /api/backup/import` erwartet das ZIP im Multipart-Feld `file`.

Die maximale ZIP-Größe und die maximale entpackte Größe betragen jeweils
10 GB. Vor jedem Restore wird unter `data/backups/` ein vollständiges
Sicherheitsbackup angelegt. Nach einem erfolgreichen Restore muss Panorama
Studio neu gestartet werden.

Backups ohne Medien lassen vorhandene Mediendateien beim Restore unverändert.
Backups mit Medien ersetzen das lokale Medienverzeichnis.

Das aktuelle Backupformat prüft Dateiliste und Prüfsummen vollständig vor dem
Entpacken. Manipulierte oder unvollständige Archive sowie Backups mit neuerer
Schema-Version werden abgelehnt. Legacy-Backups des bisherigen Formats bleiben
lesbar, soweit Datenbank- und Inhaltsprüfung erfolgreich sind.

## Datenbankmigrationen

`core/migrations/` enthält geordnete additive Migrationen.
`schema_migrations` protokolliert jede erfolgreich abgeschlossene Migration
genau einmal. Migrationen laufen transaktional und idempotent; automatische
Downgrades gibt es nicht. Aktueller Stand ist Schema 3 (`initial`,
`gps_and_maps`, `portable_export`).

## Windows-Release

`tools/release/build-release.ps1` verlangt einen sauberen Git-Arbeitsbaum,
zeigt Branch und zentrale Version, führt Python-, JavaScript- und Go-Tests aus,
baut und prüft `portable-server` und erzeugt ein deterministisches ZIP unter
`build/release/`. Alle Laufzeitassets sind lokal.

Bekannte v1.0-Risiken: Python ist noch nicht eingebettet, Browser-Codecs und
WebGL sind systemabhängig, große Medien-/MBTiles-Bestände benötigen
ausreichend temporären Speicher, und es gibt noch keinen Installer.

Offline-Karten werden nur gesichert und beim Restore ersetzt, wenn
`includes_maps` im Manifest `true` ist. Diese Option ist wegen der
potenziell großen Dateien standardmäßig deaktiviert.
