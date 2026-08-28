# Everything2Markdown

Dokumenten-Konvertierung (PDF/DOCX → Markdown) mit Docling für Knowledge-Management/RAG.
Umgebung: MacBook Apple Silicon (32 GB), ggf. Firmen-Proxy (siehe `HTTP_PROXY`/`HTTPS_PROXY` in `start_docling_native.sh`), Ollama läuft nativ auf dem Host.

## Arbeitsweise für Claude

- Aktuelles Modell dieser Sessions: **Fable 5**. Delegiere Recherche-, Such- und Routineaufgaben
  wann immer möglich an **Subagenten mit schwächeren Modellen** (z. B. `model: haiku`),
  statt sie selbst im Hauptkontext zu erledigen.
- **Kein Output-Post-Processing als "Fix"**: OCR-/Konvertierungsfehler werden an der Quelle
  behoben (Engine, Auflösung, Modellwahl), nicht durch Regex-Korrekturen am Markdown.
  Kein Overfitting auf einzelne Test-PDFs.
- Test-Dokument für Qualitätsvergleiche: ein bildbasiertes, gescanntes deutsches PDF
  (300-DPI-Scan, deutsche Umlaute — fast kein Text-Layer), z. B. ein eingescanntes Zertifikat.

## Architektur (Stand 2026-07-11)

**Docling-serve läuft NATIV auf macOS, nicht mehr in Docker.**

Grund: Docker auf dem Mac hat kein GPU-Passthrough (kein Metal im Linux-Container) und
`ocrmac` (Apple Vision Framework — mit Abstand beste OCR für Deutsch) funktioniert nur nativ.
Der Wechsel von Container-Tesseract auf natives ocrmac hat die deutschen OCR-Fehler
(„MaBnahmen", „nat den", „Dusseldorf") vollständig beseitigt.

| Komponente | Wo | Details |
|---|---|---|
| docling-serve 1.26 | nativ, Port 5001 | venv: `./docling-native/`, Start: `./start_docling_native.sh` |
| OCR | ocrmac (Apple Vision) | `de-DE`+`en-US`, recognition=accurate; via Custom-Preset auf `"auto"` gemappt |
| GPU | MPS (Metal) | torch.backends.mps aktiv für Layout-/Tabellen-Modelle |
| Ollama | nativ, Port 11434 | `ibm/granite-docling:258m`, `granite3.3-vision:2b`, `gemma4` |
| Docker-Variante | gestoppt, `compose.yaml` | Fallback; Container-OCR ist für Deutsch deutlich schlechter |

### Start / Stop

```bash
./start_docling_native.sh          # stoppt automatisch den Docker-Container (Port-Konflikt)
# Log: /tmp/docling-native.log
```

### Wichtige Erkenntnisse (nicht erneut ausprobieren)

- `ocr_preset="auto"` wird von Clients default gesendet → Server-seitiger Override via
  `DOCLING_SERVE_CUSTOM_OCR_PRESETS='{"auto":{...}}'` greift ohne Client-Änderung.
- Server-seitige `DOCLING_SERVE_CUSTOM_PICTURE_DESCRIPTION_PRESETS` mit `api_ollama`-Engine
  werden von docling-jobkit nicht sauber deserialisiert (dict statt Options-Objekt) —
  Ollama-VLMs für Bildbeschreibung nur per Request-`picture_description_custom_config`
  oder als JSON-`options`-Datei mitschicken.
- Verschachtelte JSON-Configs (`vlm_pipeline_custom_config`) **nie als Form-Feld** senden
  (Shell-Escaping zerstört sie) — immer `-F "options=@file.json;type=application/json"`.
- `vlm_pipeline_preset=granite_docling` ist nicht erlaubt; der interne Default heißt im
  Request `default`. Erlaubte Namen: `default`, `smoldocling`, `granite_vision`, `pixtral`, …
- granite-docling (258M) skaliert Bilder intern auf feste Encoder-Auflösung —
  `scale` > 2.0 bringt dort nichts.
- Docling rendert für Tesseract-OCR hartkodiert mit scale=3 (216 DPI).
- Ollama liest keine Proxy-Env-Variablen; `ollama pull` scheitert am Firmenproxy.
  Workaround: GGUF von HuggingFace per `curl -x <proxy>` laden, `ollama create` mit Modelfile.
- HuggingFace-Downloads im Repo unter `/tmp/granite-vision/` (GGUF + mmproj) — bei Bedarf
  wiederverwendbar.

### Dateien

| Datei | Zweck |
|---|---|
| `start_docling_native.sh` | Startet nativen docling-serve (ocrmac + MPS) |
| `docling_convert.sh` | CLI-Wrapper für Konvertierungen (`--vlm`, `--force-ocr`, `--async`, `--pages`) |
| `DOCLING_API.md` | Vollständige API-Referenz inkl. nicht-offensichtlicher Parameter |
| `DOCLING_ERKENNTNISSE.md` | Test-Erkenntnisse + Specs/Empfehlungen für zukünftiges zentrales Hosting (Ubuntu/GPU) |
| `compose.yaml` | Docker-Fallback (gestoppt); enthält Tesseract-Setup mit `./tessdata/` |
| `openwebui-docling-params.json` | Docling-Optionen für die OpenWebUI-Integration |
| `docling-native/` | Python-venv der nativen Installation (nicht committen) |

### Standard-API-Call

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@dokument.pdf" \
  -F "to_format=md" \
  -F "do_picture_description=true" \
  -F "include_images=true" \
  -F "picture_description_area_threshold=0.005"
# force_ocr=true nur für bildbasierte PDFs; bei nativen Text-PDFs weglassen
# (sonst OCR-Fehler wie "D8.07.2026" statt Text-Layer-korrektem "08.07.2026")
```
