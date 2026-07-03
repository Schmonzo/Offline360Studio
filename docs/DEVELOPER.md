# Panorama Studio Developer Guide

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
