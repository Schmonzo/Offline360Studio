# Windows-Release

`build-release.ps1` erzeugt zwei vollständig offline nutzbare Paketvarianten.
Der Standard bleibt der bisherige Developer-Modus:

```powershell
powershell -ExecutionPolicy Bypass -File tools/release/build-release.ps1
powershell -ExecutionPolicy Bypass -File tools/release/build-release.ps1 -Mode dev
powershell -ExecutionPolicy Bypass -File tools/release/build-release.ps1 -Mode standalone
```

## Modi und Ausgaben

- `dev`: `PanoramaStudio-<version>-win64-dev.zip`. Auf dem Zielsystem werden
  Python 3 und die Pakete aus `app/requirements.txt` vorausgesetzt.
- `standalone`: `PanoramaStudio-<version>-win64-standalone.zip`. Das Paket
  enthält eine x64-Runtime und alle Python-Abhängigkeiten.

Zu jedem ZIP entsteht eine gleichnamige `.sha256`-Datei. Im Paket listet
`checksums.txt` alle Dateien, einschließlich Embedded Runtime,
`server.exe`, Server-Prüfsumme und Startdateien. ZIP-Zeitstempel und
Dateireihenfolge sind stabil; neu aufgelöste Python-Wheels können jedoch
plattform- oder Index-Metadaten enthalten.

## Embedded Python und Vertrauenskette

- Version: CPython 3.12.10, Windows embeddable package (64-bit)
- Quelle:
  `https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip`
- SHA-256:
  `4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3`
- Hashquelle: offizielles `.sigstore`-Bundle neben dem Python.org-Artefakt
- pip-Bootstrap: `https://bootstrap.pypa.io/get-pip.py`
- get-pip.py SHA-256:
  `a341e1a43e38001c551a1508a73ff23636a11970b61d901d9a1cad2a18f57055`
- Build-pip: 25.1.1

Python 3.12 wurde gegenüber 3.13 gewählt, weil es für die nativen
Requirements die konservativere Wheel-Kompatibilität bietet. Das
Embeddable-Paket enthält kein pip. Deshalb aktiviert der Build dessen
`python312._pth`, bootstrapped das hashgeprüfte pip und installiert die exakt
versionierten Requirements direkt nach `runtime/python/Lib/site-packages`.
Ein Importtest mit App-Core, Flask, Werkzeug, Pillow und den übrigen direkten
Requirements muss anschließend erfolgreich sein. Danach entfernt der Build
pip wieder aus der ausgelieferten Runtime.

Downloads erfolgen nur im Release-Build. Dateien unter
`tools/release/cache/` werden bei passendem Hash wiederverwendet. Ein falscher
Cache-Hash führt zum Löschen und erneuten Download; stimmt auch dessen Hash
nicht, bricht der Build ab. Cache und Ausgaben werden nicht eingecheckt.

## Paket- und Startmodell

Das Standalone-Paket enthält:

```text
PanoramaStudio-<version>-win64-standalone/
  app/
  runtime/python/
  data/
  media/
  logs/
  LICENSES/
  start-panorama-studio.bat
  README.txt
  VERSION.txt
  checksums.txt
```

Das Startskript wechselt in die Paketwurzel, setzt
`PANORAMA_STUDIO_RUNTIME_ROOT` sowie UTF-8- und Isolationsvariablen
und startet ausschließlich `runtime\python\python.exe app\app.py`. Die App
bindet nur an `127.0.0.1` und öffnet wie bisher optional den lokalen Browser.
Es gibt zur Laufzeit keine Downloads, externen HTTP-Aufrufe, Installation
oder pip-Ausführung.

## Voraussetzungen und Ablauf

Beide Modi verlangen einen sauberen Git-Arbeitsbaum sowie Python, Node.js und
Go für die Build-Prüfungen. Standalone muss auf Windows x64 gebaut werden und
benötigt Internet, sofern Runtime, Bootstrap oder Python-Pakete noch nicht
lokal verfügbar sind. Der Build:

1. führt Python-, JavaScript- und Go-Tests aus;
2. baut `portable-server.exe` reproduzierbar und prüft dessen SHA-256;
3. staged App und Laufzeitverzeichnisse;
4. ergänzt im Standalone-Modus Runtime und Requirements;
5. schreibt interne Checksums sowie das deterministische ZIP;
6. schreibt die externe ZIP-Prüfsumme und prüft, dass keine versionierte Datei
   verändert wurde.

Bekannte Einschränkungen: kein Installer oder Updater, nur Windows x64,
systemabhängige Browser-Codecs/WebGL und Netzwerkbedarf beim ersten
Standalone-Build. Die Anwendung und ihr Start bleiben vollständig offline.
