# Panorama Studio v0.3.1

Lokale Offline-Web-App für Insta360-/360°-Fotos und MP4-Videos.

## Start

1. ZIP entpacken, z. B. nach `C:\PanoramaStudio`
2. Einmalig `install_requirements.bat` ausführen
3. Danach `start.bat` starten
4. Browser öffnet `http://127.0.0.1:5000`

## Medien

- Fotos: `media/photos/`
- Videos: `media/videos/`
- Projektordner sind möglich, z. B. `media/photos/Island 2026/0001.jpg`

## Neu in v0.3.1

- Projekt-Gruppierung
- Statistik-Dashboard
- Suche über Titel, Projekt, Kategorie, Beschreibung und Pfad
- Filter nach Projekt, Kategorie, Medientyp und Favoriten
- Listen- und Kachelansicht
- Kategorien im Admin-Panel
- Upload direkt in wählbares Projekt
- bestehende v0.2-Datenbank wird automatisch migriert

## Tastatur im Viewer

- `+` hineinzoomen
- `-` herauszoomen
- `H` Home
- `F` Vollbild
- `C` Cinematic/Auto-Rotation


## v0.3.1 Bugfix

- Behebt den schwarzen Bildschirm beim Wechsel zwischen mehreren Panoramen.
- Marzipano-Instanz wird beim Szenenwechsel sauber neu initialisiert.
- Zoom-Anzeige und Cinematic Mode werden beim Wechsel korrekt zurückgesetzt.
