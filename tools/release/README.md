# Windows-Release

`build-release.ps1` erzeugt zwei vollstÃ¤ndig offline nutzbare Paketvarianten.
Der Standard bleibt der bisherige Developer-Modus:

```powershell
powershell -ExecutionPolicy Bypass -File tools/release/build-release.ps1
powershell -ExecutionPolicy Bypass -File tools/release/build-release.ps1 -Mode dev
powershell -ExecutionPolicy Bypass -File tools/release/build-release.ps1 -Mode standalone
```

## Modi und Ausgaben

- `dev`: `Offline360Studio-<version>-win64-dev.zip`. Auf dem Zielsystem werden
  Python 3 und die Pakete aus `app/requirements.txt` vorausgesetzt.
- `standalone`: `Offline360Studio-<version>-win64-standalone.zip`. Das Paket
  enthÃ¤lt eine x64-Runtime und alle Python-AbhÃ¤ngigkeiten.

Zu jedem ZIP entsteht eine gleichnamige `.sha256`-Datei. Im Paket listet
`checksums.txt` alle Dateien, einschlieÃŸlich Embedded Runtime,
`server.exe`, Server-PrÃ¼fsumme und Startdateien. ZIP-Zeitstempel und
Dateireihenfolge sind stabil; neu aufgelÃ¶ste Python-Wheels kÃ¶nnen jedoch
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

Python 3.12 wurde gegenÃ¼ber 3.13 gewÃ¤hlt, weil es fÃ¼r die nativen
Requirements die konservativere Wheel-KompatibilitÃ¤t bietet. Das
Embeddable-Paket enthÃ¤lt kein pip. Deshalb aktiviert der Build dessen
`python312._pth`, bootstrapped das hashgeprÃ¼fte pip und installiert die exakt
versionierten Requirements direkt nach `runtime/python/Lib/site-packages`.
Ein Importtest mit App-Core, Flask, Werkzeug, Pillow und den Ã¼brigen direkten
Requirements muss anschlieÃŸend erfolgreich sein. Danach entfernt der Build
pip wieder aus der ausgelieferten Runtime.

Downloads erfolgen nur im Release-Build. Dateien unter
`tools/release/cache/` werden bei passendem Hash wiederverwendet. Ein falscher
Cache-Hash fÃ¼hrt zum LÃ¶schen und erneuten Download; stimmt auch dessen Hash
nicht, bricht der Build ab. Cache und Ausgaben werden nicht eingecheckt.

## Paket- und Startmodell

Das Standalone-Paket enthÃ¤lt:

```text
Offline360Studio-<version>-win64-standalone/
  app/
  runtime/python/
  data/
  media/
  logs/
  LICENSES/
  start-offline360-studio.bat
  README.txt
  VERSION.txt
  checksums.txt
```

Das Startskript wechselt in die Paketwurzel, setzt
`OFFLINE360_STUDIO_RUNTIME_ROOT` sowie UTF-8- und Isolationsvariablen
und startet ausschlieÃŸlich `runtime\python\python.exe app\app.py`. Die App
bindet nur an `127.0.0.1` und Ã¶ffnet wie bisher optional den lokalen Browser.
Es gibt zur Laufzeit keine Downloads, externen HTTP-Aufrufe, Installation
oder pip-AusfÃ¼hrung.

## Voraussetzungen und Ablauf

Beide Modi verlangen einen sauberen Git-Arbeitsbaum sowie Python, Node.js und
Go fÃ¼r die Build-PrÃ¼fungen. Standalone muss auf Windows x64 gebaut werden und
benÃ¶tigt Internet, sofern Runtime, Bootstrap oder Python-Pakete noch nicht
lokal verfÃ¼gbar sind. Der Build:

1. fÃ¼hrt Python-, JavaScript- und Go-Tests aus;
2. baut `portable-server.exe` reproduzierbar und prÃ¼ft dessen SHA-256;
3. staged App und Laufzeitverzeichnisse;
4. ergÃ¤nzt im Standalone-Modus Runtime und Requirements;
5. schreibt interne Checksums sowie das deterministische ZIP;
6. schreibt die externe ZIP-PrÃ¼fsumme und prÃ¼ft, dass keine versionierte Datei
   verÃ¤ndert wurde.

Bekannte EinschrÃ¤nkungen: kein Installer oder Updater, nur Windows x64,
systemabhÃ¤ngige Browser-Codecs/WebGL und Netzwerkbedarf beim ersten
Standalone-Build. Die Anwendung und ihr Start bleiben vollstÃ¤ndig offline.

