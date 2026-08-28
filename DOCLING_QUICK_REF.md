# Docling-Serve – Quick Reference

**Stand: 2026-07-11 — Native Architektur (ocrmac + MPS)**

## Start / Stop

```bash
# Starten (stoppt automatisch Docker-Container falls aktiv)
./start_docling_native.sh

# Log verfolgen
tail -f /tmp/docling-native.log

# Status prüfen
curl -s http://localhost:5001/health | jq '.'

# Stoppen
pkill -f docling-serve
```

## Status-Checks

```bash
# Health-Check
curl http://localhost:5001/health

# Swagger-Doku
open http://localhost:5001/docs

# Ollama-Modelle prüfen
ollama list | grep -E "granite|gemma"

# Port 5001 belegt?
lsof -i :5001
```

## Wichtigste API-Calls

### Standard-Konvertierung (native PDFs — Text-Layer vorhanden)

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@dokument.pdf" \
  -F "to_format=md" \
  --output result.md
```

> Kein `force_ocr` bei nativen PDFs — der Text-Layer ist besser als OCR.

### Bildbasiertes / gescanntes PDF (kein Text-Layer)

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@scan.pdf" \
  -F "to_format=md" \
  -F "force_ocr=true" \
  --output result.md
```

> `force_ocr=true` nur hier. Bei nativen PDFs entstehen sonst Fehler wie „D8.07.2026"
> statt „08.07.2026" (OCR liest Pixel statt Text-Layer).

### Mit Bildbeschreibung (SmolVLM, empfohlen für Dokumente mit Logos/Grafiken)

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@dokument.pdf" \
  -F "to_format=md" \
  -F "do_picture_description=true" \
  -F "include_images=true" \
  -F "picture_description_area_threshold=0.005" \
  --output result.md
```

### Zertifikat / komplexes Layout (VLM-Pipeline)

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@zertifikat.pdf" \
  -F "to_format=md" \
  -F "pipeline=vlm" \
  -F "vlm_pipeline_preset=smoldocling"
```

## Aktuelle Systemkonfiguration

| Komponente | Wert |
|---|---|
| Server | docling-serve 1.26, nativ (venv `./docling-native/`) |
| Port | 5001 |
| OCR-Engine | ocrmac (Apple Vision Framework) |
| OCR-Sprachen | `de-DE` + `en-US`, recognition=accurate |
| OCR-Preset-Override | `auto` → ocrmac (transparent für alle Clients) |
| GPU | MPS (Metal) für Layout-/Tabellen-Modelle |
| Ollama-Modelle | `ibm/granite-docling:258m`, `granite3.3-vision:2b`, `gemma4` |

## Troubleshooting

### Port 5001 belegt — „Connection refused" oder „Address already in use"

```bash
# Prüfen was auf Port 5001 läuft
lsof -i :5001

# Docker-Container noch aktiv?
docker ps | grep docling

# Falls ja: stoppen
docker compose down
# Dann neu starten:
./start_docling_native.sh
```

### Ollama nicht erreichbar

```bash
# Läuft Ollama?
curl http://localhost:11434/api/tags

# Falls nicht: starten
ollama serve &
```

### Ollama kann Modelle nicht pullen (Firmenproxy)

Ollama liest keine Proxy-Umgebungsvariablen. Workaround:
```bash
# GGUF von HuggingFace über Proxy laden
curl -x http://your-proxy:port -L -o modell.gguf https://huggingface.co/...

# Modell anlegen
ollama create mein-modell -f Modelfile
```

### Schlechte OCR-Qualität bei deutschen Texten

Der Server konfiguriert `auto` als ocrmac mit `de-DE`+`en-US` — keine Aktion nötig.
Falls trotzdem Probleme: Log prüfen (`tail -f /tmp/docling-native.log`) und sicherstellen,
dass `start_docling_native.sh` den Server gestartet hat (nicht Docker).

### Conversion läuft, aber Umlaute fehlen/falsch

Prüfen: Wird der native Server verwendet oder noch ein alter Docker-Container?
```bash
lsof -i :5001   # Prozess sollte "Python" aus ./docling-native/ sein, nicht Docker
```

## Dateien

| Datei | Zweck |
|---|---|
| `start_docling_native.sh` | Startet nativen docling-serve (ocrmac + MPS) |
| `docling_convert.sh` | CLI-Wrapper für Konvertierungen |
| `DOCLING_API.md` | Vollständige API-Referenz |
| `openwebui-docling-params.json` | Docling-Optionen für OpenWebUI |
| `compose.yaml` | Docker-Fallback (gestoppt, veraltet) |

## Docker-Fallback (nicht empfohlen)

Die Docker-Variante (`compose.yaml`, Tesseract-OCR) ist gestoppt und liefert
für Deutsch deutlich schlechtere Ergebnisse (kein ocrmac, kein MPS).
Nur im absoluten Notfall:

```bash
docker compose up -d
docker compose down
docker logs -f docling-serve
```

---

**Letztes Update:** 2026-07-11  
**OCR:** ocrmac (Apple Vision) — `de-DE`+`en-US`  
**GPU:** MPS (Metal)  
**Modelle (Ollama):** ibm/granite-docling:258m, granite3.3-vision:2b, gemma4
