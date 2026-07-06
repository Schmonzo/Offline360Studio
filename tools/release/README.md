# Windows-Release

`build-release.ps1` erzeugt ein reproduzierbares, vollständig offline nutzbares
Developer-ZIP. Der Build verlangt einen sauberen Git-Arbeitsbaum, führt alle
Python-, JavaScript- und Go-Prüfungen aus, baut und verifiziert den portablen
Server und schreibt das Ergebnis nach `build/release/`.

```powershell
powershell -ExecutionPolicy Bypass -File tools/release/build-release.ps1
```

Das Paket enthält noch keine Python-Runtime. Auf dem Zielsystem müssen Python 3
und die Abhängigkeiten aus `app/requirements.txt` vorhanden sein. Embedded
Python beziehungsweise ein Installer folgt in der nächsten Etappe. Das Skript
führt keine Downloads oder Installationen aus.
