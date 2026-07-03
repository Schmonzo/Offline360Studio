# Panorama Studio

## Backup & Restore

Der Admin-Bereich kann lokale Projektdaten als ZIP exportieren und wiederherstellen.
Ein Backup enthält:

- `manifest.json` mit Format-, Versions- und Inhaltsangaben
- `README.txt`
- `panorama_studio.db` als konsistente SQLite-Kopie
- unterstützte Konfigurationsdateien aus `data/config/` unter `config/`
- optional Fotos, Videos und Vorschaubilder unter `media/`

`media_count` und `project_count` geben die Anzahl der Datensätze in der
SQLite-Datenbank an. `includes_media` zeigt an, ob auch die Mediendateien
enthalten sind.

`POST /api/backup/export` erwartet JSON mit `{"includes_media": false}` oder
`{"includes_media": true}`. `POST /api/backup/import` erwartet das ZIP im
Multipart-Feld `file`.

Die maximale ZIP-Größe und die maximale entpackte Größe betragen jeweils
10 GB. Vor jedem Restore wird unter `data/backups/` ein vollständiges
Sicherheitsbackup angelegt. Nach einem erfolgreichen Restore muss Panorama
Studio neu gestartet werden.

Backups ohne Medien lassen vorhandene Mediendateien beim Restore unverändert.
Backups mit Medien ersetzen das lokale Medienverzeichnis.
