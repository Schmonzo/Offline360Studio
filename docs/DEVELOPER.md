# Panorama Studio Developer Guide

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
