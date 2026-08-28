# Docling-Serve API Dokumentation

**Endpoint:** `http://localhost:5001`  
**Version:** v1.26 (docling-serve, nativ auf macOS)  
**Stand:** 2026-07-11

Dieses Dokument enthält alle nicht-offensichtlichen Parameter und Optimierungen die in gängigen Clients (OpenWebUI etc.) nicht sichtbar sind.

---

## Inhaltsverzeichnis

1. [Basis-Endpunkte](#endpunkte)
2. [Optimale Basis-Anfrage](#optimale-basis-anfrage)
3. [OCR-Konfiguration](#ocr-konfiguration)
4. [Bildanalyse & Vision](#bildanalyse--vision)
5. [Pipeline-Wahl](#pipeline-wahl)
6. [Ausgabeformate](#ausgabeformate)
7. [Performance](#performance)
8. [Bekannte Artefakte & Fixes](#bekannte-artefakte--fixes)
9. [Chunking für RAG](#chunking-für-rag)
10. [Async für große Dateien](#async-für-große-dateien)

---

## Endpunkte

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `POST` | `/v1/convert/file` | Synchrone Konvertierung (Datei-Upload) |
| `POST` | `/v1/convert/file/async` | Asynchrone Konvertierung (gibt task_id zurück) |
| `POST` | `/v1/convert/source` | Konvertierung per URL/S3 |
| `POST` | `/v1/convert/source/batch` | Batch-Konvertierung mehrerer URLs |
| `GET`  | `/v1/result/{task_id}` | Ergebnis eines async Tasks |
| `GET`  | `/v1/status/poll/{task_id}` | Status eines async Tasks |
| `POST` | `/v1/chunk/hierarchical/file` | Hierarchisches Chunking (für RAG) |
| `POST` | `/v1/chunk/hybrid/file` | Hybrid-Chunking (für RAG) |
| `GET`  | `/v1/memory/stats` | Speichernutzung des Servers |
| `GET`  | `/health` | Health-Check |
| `GET`  | `/version` | Version-Info |

---

## Optimale Basis-Anfrage

### Standard-Konvertierung (native PDFs mit eingebetteten Bildern)

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@document.pdf" \
  -F "to_format=md" \
  -F "do_picture_description=true" \
  -F "include_images=true" \
  -F "picture_description_area_threshold=0.005" \
  -F "do_picture_classification=true"
```

### Gescannte Dokumente (force OCR)

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@scanned.pdf" \
  -F "to_format=md" \
  -F "force_ocr=true" \
  -F "do_picture_description=true" \
  -F "include_images=true" \
  -F "picture_description_area_threshold=0.005"
```

### Zertifikate / Formulare (VLM-Pipeline für komplexes Layout)

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@certificate.pdf" \
  -F "to_format=md" \
  -F "pipeline=vlm" \
  -F "vlm_pipeline_preset=granite_docling"
```

### Alles aktiviert (maximale Qualität, langsamer)

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@document.pdf" \
  -F "to_format=md" \
  -F "do_picture_description=true" \
  -F "include_images=true" \
  -F "picture_description_area_threshold=0.005" \
  -F "do_picture_classification=true" \
  -F "do_table_structure=true" \
  -F "table_mode=accurate" \
  -F "do_formula_enrichment=false" \
  -F "images_scale=2.0"
```

---

## OCR-Konfiguration

### Aktuelle Server-Konfiguration (nativ, ocrmac)

Der Server überschreibt das `"auto"` OCR-Preset mit **ocrmac (Apple Vision Framework)** + Deutsch+Englisch, recognition=accurate. Das passiert automatisch über die Umgebungsvariable `DOCLING_SERVE_CUSTOM_OCR_PRESETS` in `start_docling_native.sh` — kein Extra-Parameter nötig.

```
DOCLING_SERVE_CUSTOM_OCR_PRESETS='{"auto":{"kind":"ocrmac","lang":["de-DE","en-US"],"recognition":"accurate"}}'
```

ocrmac nutzt das **Apple Vision Framework** und liefert mit Abstand die beste OCR-Qualität für deutschen Text. Die in Container-OCR typischen Fehler wie „MaBnahmen", „nat den", „Dusseldorf" treten nicht auf.

### Parameter

| Parameter | Default | Werte | Beschreibung |
|-----------|---------|-------|--------------|
| `ocr_preset` | `"auto"` | `auto`, `ocrmac`, `tesserocr`, `easyocr`, `rapidocr` | OCR-Engine. `auto` = ocrmac+Deutsch (unser Custom-Override) |
| `do_ocr` | `true` | `true/false` | OCR generell ein/aus |
| `force_ocr` | `false` | `true/false` | OCR auch auf native Text-PDFs erzwingen — **nur für bildbasierte PDFs** |
| `ocr_lang` | (server) | `["de-DE","en-US"]` | Sprachen für OCR |

> **Wichtig zu `force_ocr`:** Nur für bildbasierte PDFs (kein Text-Layer) verwenden.
> Bei nativen Text-PDFs entstehen durch erzwungene OCR Fehler wie „D8.07.2026" statt
> „08.07.2026" aus dem Text-Layer. Die Standard-Pipeline liest den Text-Layer direkt —
> das ist präziser als jede OCR.

### Direkte OCR-Engine-Auswahl (überschreibt Server-Default)

```bash
# Server-Default nutzen (ocrmac de-DE+en-US) — nichts angeben, läuft automatisch

# Explizit ocrmac mit anderen Sprachen:
-F "ocr_custom_config={\"kind\":\"ocrmac\",\"lang\":[\"de-DE\"],\"recognition\":\"accurate\"}"

# Für reine englische Dokumente:
-F "ocr_custom_config={\"kind\":\"ocrmac\",\"lang\":[\"en-US\"]}"
```

### Docker-Fallback (Tesseract — nicht empfohlen)

Die Docker-Variante (`compose.yaml`) nutzt `tesserocr` mit `tessdata_best`. Sie liefert
für Deutsch deutlich schlechtere Ergebnisse als ocrmac (kein Apple Vision, kein MPS).
Nur im absoluten Notfall aktivieren.

### Warum nicht `auto` aus der Box?

`auto` wählt normalerweise **RapidOCR** (chinesisch-fokussiert, keine deutschen Umlaute).
Unser Server-Override ersetzt das mit ocrmac+Deutsch. Der `"auto"` Name bleibt gleich —
Clients müssen **nichts** ändern.

---

## Bildanalyse & Vision

### Parameter

| Parameter | Default | Beschreibung |
|-----------|---------|--------------|
| `do_picture_description` | `false` | **Bilder beschreiben aktivieren** (SmolVLM-256M) |
| `include_images` | `true` | Bild-Crops in Ausgabe einbetten |
| `picture_description_area_threshold` | `0.05` | Minimale Bildgröße (% der Seite) für Beschreibung. **Default 5% ist oft zu hoch!** |
| `do_picture_classification` | `false` | Bilder klassifizieren (Logo, Signature, Chart etc.) |
| `generate_picture_images` | (intern) | Seiten als Bilder rendern für Vision-Modelle |
| `images_scale` | `2.0` | Auflösung der gerenderten Bilder (2.0 = doppelte Auflösung) |
| `include_page_images` | `false` | Komplette Seiten als Bild einbetten |
| `image_export_mode` | `placeholder` | `placeholder`, `embedded`, `referenced` |

### Empfohlene Werte für Dokumente mit Logos/Signaturen

```bash
-F "do_picture_description=true"
-F "include_images=true"
-F "picture_description_area_threshold=0.005"   # 0.5% statt 5%
-F "do_picture_classification=true"             # Logo/Signature/Chart Labels
```

### Picture Description Presets (auf diesem Server)

| Preset | Modell | Beschreibung |
|--------|--------|--------------|
| `smolvlm` | SmolVLM-256M (lokal) | **Default** – schnell, 256M, generische Beschreibungen |
| `granite_vision` | granite3.3-vision:2b | Braucht Ollama-Modell `granite3.3-vision:2b` |
| `pixtral` | Pixtral-12B | Groß, sehr gut – braucht VRAM |
| `qwen` | Qwen2.5-VL-3B | Mehrsprachig – MLX oder Transformers |

### Bild-Beschreibung mit Gemma4 via Ollama (Custom Config)

```bash
CUSTOM='{"engine_options":{"engine_type":"api_ollama","url":"http://localhost:11434/v1/chat/completions","params":{"model":"gemma4:latest","max_tokens":256},"timeout":60,"concurrency":1},"model_spec":{"name":"gemma4","default_repo_id":"google/gemma-4","prompt":"Describe this image in detail.","response_format":"plaintext","api_overrides":{},"stop_strings":[],"max_new_tokens":256,"temperature":0},"prompt":"Describe this image concisely."}'

curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@document.pdf" \
  -F "to_format=md" \
  -F "picture_description_custom_config=${CUSTOM}"
```

> **Hinweis:** `picture_description_custom_config` übergibt die Konfiguration direkt per Request. Server-seitige Preset-Overrides funktionieren nicht zuverlässig (Deserialisierungs-Bug in Docling-Jobkit).

---

## Pipeline-Wahl

### Standard-Pipeline (`pipeline=standard`)

Nutzt Layout-Analyse + OCR + Tabellenerkennung. Gut für:
- Native PDFs mit eingebettetem Text
- Dokumente mit Tabellen
- Strukturierte Reports

```bash
-F "pipeline=standard"
```

### VLM-Pipeline (`pipeline=vlm`)

Verarbeitet **jede Seite als Bild** mit einem Vision-Modell. Gut für:
- Gescannte Dokumente
- Zertifikate, Formulare
- Komplexes Layout das OCR nicht erfasst

```bash
# Mit IBM Granite-Docling via Ollama (unser Server-Default):
-F "pipeline=vlm" \
-F "vlm_pipeline_preset=granite_docling"

# Custom VLM (z.B. SmolDocling):
-F "pipeline=vlm" \
-F "vlm_pipeline_preset=smoldocling"
```

### VLM-Pipeline Presets

| Preset | Modell | Größe | Beschreibung |
|--------|--------|-------|--------------|
| `granite_docling` | ibm/granite-docling:258m | 521 MB | **Server-Default** – via Ollama |
| `smoldocling` | SmolDocling-256M | 256 MB | Ähnlich Granite, leichter |
| `granite_vision` | granite-vision-3.3:2b | 2B | Bessere Bildverständnis |
| `pixtral` | Pixtral-12B | 12B | Sehr gut für Layout |
| `qwen` | Qwen2.5-VL-3B | 3B | Mehrsprachig |
| `dolphin` | Dolphin | - | Experimentell |
| `got_ocr` | GOT-OCR | - | OCR-fokussiert |
| `deepseek_ocr` | DeepSeek-OCR | - | Sehr gutes OCR via Ollama |

### Custom VLM via Ollama

> ⚠️ **Wichtig:** `vlm_pipeline_custom_config` als Form-Feld bricht wegen Shell-Escaping. Immer als JSON-Options-Datei senden!

```bash
# 1. Options-Datei erstellen
cat > /tmp/vlm_opts.json << 'EOF'
{
  "pipeline": "vlm",
  "to_formats": ["md"],
  "vlm_pipeline_custom_config": {
    "model_spec": {
      "name": "Granite-Docling-Ollama",
      "default_repo_id": "ibm-granite/granite-docling-258M",
      "prompt": "Convert this page to docling.",
      "response_format": "doctags"
    },
    "engine_options": {
      "engine_type": "api",
      "url": "http://localhost:11434/v1/chat/completions",
      "params": {"model": "ibm/granite-docling:258m", "temperature": 0.0, "max_tokens": 8192},
      "timeout": 180.0,
      "concurrency": 1
    },
    "scale": 2.0
  }
}
EOF

# 2. Als options-File senden
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@document.pdf" \
  -F "options=@/tmp/vlm_opts.json;type=application/json"
```

### VLM Preset-Namen

> ⚠️ `vlm_pipeline_preset=granite_docling` funktioniert **nicht** direkt – das ist der interne Default-Name.  
> Erlaubte Preset-Namen: `default`, `smoldocling`, `deepseek_ocr`, `granite_vision`, `pixtral`, `qwen`, etc.  
> `default` → nutzt den konfigurierten Server-Default (= granite_docling via Ollama bei uns)

```bash
# Richtig: "default" verwenden
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@document.pdf" \
  -F "pipeline=vlm" \
  -F "vlm_pipeline_preset=smoldocling"  # Kleinere Alternative
```

---

## Ausgabeformate

### Gleichzeitig mehrere Formate

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@document.pdf" \
  -F "to_format=md" \
  -F "to_format=json"
```

### Alle verfügbaren Formate

| Format | Beschreibung |
|--------|--------------|
| `md` | Markdown (Standard) |
| `json` | Docling-JSON mit vollständiger Struktur |
| `html` | HTML mit Styling |
| `text` | Reiner Text |
| `doctags` | Docling-interne Tags |
| `doclang` | DocLang-Format |

### Seitenumbruch-Markierung

```bash
# Jede Seite mit Trennlinie
-F "md_page_break_placeholder=---"

# Mit Seitennummer
-F "md_page_break_placeholder=<!-- Page -->"
```

### Seitenbereich

```bash
# Nur Seiten 1-5
-F "page_range=[1,5]"

# Nur Seite 3
-F "page_range=[3,3]"
```

---

## Performance

### Timeout-Konfiguration

```bash
# Timeout pro Dokument (Sekunden)
-F "document_timeout=120"
```

### Tabellenerkennung

```bash
# Schneller (weniger genau)
-F "table_mode=fast"

# Genauer (Standard)
-F "table_mode=accurate"

# Zellen-Matching deaktivieren (bei merged cells)
-F "table_cell_matching=false"
```

### Speichernutzung prüfen

```bash
curl http://localhost:5001/v1/memory/stats | jq '.'
```

### Konverter-Cache leeren

```bash
# Cache leeren (wenn Modelle neu geladen werden sollen)
curl http://localhost:5001/v1/clear/converters
curl http://localhost:5001/v1/clear/results
```

---

## Bekannte Artefakte & Fixes

### 1. SmolVLM `<end_of_utteranc` Artefakt

**Problem:** SmolVLM generiert `<end_of_utterance>` als EOS-Token, der manchmal abgeschnitten wird. Das ist ein reines Format-Artefakt des Modells.

**Empfehlung:** Das Artefakt ist harmlos und selten. Falls es stört, als Issue an das Docling-Projekt melden — Post-Processing-Patches am Output sind Projekt-Policy gemäß kein anerkannter Fix.

### 2. Schlechte OCR-Qualität / fehlende Umlaute

**Ursache (behoben):** Die frühere Docker-Variante mit Container-Tesseract-OCR lieferte für Deutsch schlechte Ergebnisse. Typische Fehler waren: „MaBnahmen", „nat den", „Dusseldorf". Diese Ursache (Container-OCR ohne German-support + kein Apple Vision) ist durch die native Architektur mit ocrmac vollständig behoben.

**Projekt-Policy:** OCR-Qualitätsprobleme werden an der Quelle behoben (Engine-Wahl,
Auflösung, Modellwahl) — **nicht** durch Regex-Korrekturen am Markdown-Output.
Kein Overfitting auf einzelne Test-PDFs.

Falls weiterhin Qualitätsprobleme auftreten: sicherstellen, dass der native Server läuft
(`lsof -i :5001` → Prozess sollte Python aus `./docling-native/` sein, nicht Docker).

### 3. Bilder werden nicht beschrieben (zu klein)

**Problem:** Standard-Threshold `0.05` = 5% der Seite. Logos in Kopfzeilen sind oft kleiner.

**Fix:**

```bash
-F "picture_description_area_threshold=0.005"   # 0.5% statt 5%
```

### 4. Tabellen werden nicht erkannt

**Fix:**

```bash
-F "do_table_structure=true" \
-F "table_mode=accurate" \
-F "table_cell_matching=true"
```

### 5. Datumsfehler bei nativen PDFs (z.B. „D8.07.2026")

**Ursache:** `force_ocr=true` bei einem PDF mit vorhandenem Text-Layer. OCR liest Pixel
statt den präzisen Text-Layer zu verwenden.

**Fix:** `force_ocr` bei nativen PDFs weglassen. Nur bei bildbasierten PDFs (kein Text-Layer)
ist `force_ocr=true` sinnvoll.

---

## Chunking für RAG

### Hierarchisches Chunking

Beibehaltung der Dokumenthierarchie (ideal für RAG mit Kontext).

```bash
curl -X POST http://localhost:5001/v1/chunk/hierarchical/file \
  -F "files=@document.pdf" \
  -F "to_format=md" \
  | jq '.chunks[] | {text: .text, page: .meta.page_no}'
```

### Hybrid Chunking

Kombination aus hierarchisch und sliding-window.

```bash
curl -X POST http://localhost:5001/v1/chunk/hybrid/file \
  -F "files=@document.pdf" \
  -F "to_format=md"
```

### Chunking + Konvertierung zusammen

```bash
# Erst konvertieren, dann chunken:
curl -X POST http://localhost:5001/v1/chunk/hierarchical/file \
  -F "files=@document.pdf" \
  -F "to_format=md" \
  -F "do_picture_description=true" \
  -F "include_images=true" \
  -F "picture_description_area_threshold=0.005"
```

---

## Async für große Dateien

Für Dokumente > 50 Seiten oder mit vielen Bildern.

### 1. Job starten

```bash
TASK_ID=$(curl -s -X POST http://localhost:5001/v1/convert/file/async \
  -F "files=@large_document.pdf" \
  -F "to_format=md" \
  -F "do_picture_description=true" \
  | jq -r '.task_id')
echo "Task: $TASK_ID"
```

### 2. Status pollen

```bash
curl -s http://localhost:5001/v1/status/poll/$TASK_ID | jq '.status'
# "pending" | "running" | "success" | "failure"
```

### 3. Ergebnis holen

```bash
curl -s http://localhost:5001/v1/result/$TASK_ID \
  | jq -r '.document.md_content'
```

### Vollständiges Async-Skript

```bash
#!/bin/bash
PDF="$1"
BASE_URL="http://localhost:5001"

# Start
echo "Starting conversion of $PDF..."
TASK_ID=$(curl -s -X POST $BASE_URL/v1/convert/file/async \
  -F "files=@$PDF" \
  -F "to_format=md" \
  -F "do_picture_description=true" \
  -F "include_images=true" \
  -F "picture_description_area_threshold=0.005" \
  | jq -r '.task_id')

# Poll
while true; do
  STATUS=$(curl -s $BASE_URL/v1/status/poll/$TASK_ID | jq -r '.status')
  echo "Status: $STATUS"
  if [ "$STATUS" = "success" ] || [ "$STATUS" = "failure" ]; then
    break
  fi
  sleep 3
done

# Result
if [ "$STATUS" = "success" ]; then
  curl -s $BASE_URL/v1/result/$TASK_ID \
    | jq -r '.document.md_content'
else
  echo "Conversion failed"
  curl -s $BASE_URL/v1/result/$TASK_ID | jq '.errors'
fi
```

---

## OpenWebUI-Integration

### Aktuelle Konfiguration (`openwebui-docling-params.json`)

```json
{
  "options": "{\"pipeline\":\"standard\",\"to_formats\":[\"md\"],\"do_picture_description\":true,\"generate_picture_images\":true,\"picture_description_area_threshold\":0.005,\"ocr_preset\":\"auto\"}"
}
```

### Alternative: VLM-Pipeline für besseres Layout

```json
{
  "options": "{\"pipeline\":\"vlm\",\"to_formats\":[\"md\"],\"vlm_pipeline_custom_config\":{\"model_spec\":{\"name\":\"Granite-Docling-Ollama\",\"default_repo_id\":\"ibm-granite/granite-docling-258M\",\"prompt\":\"Convert this page to docling.\",\"response_format\":\"doctags\"},\"engine_options\":{\"engine_type\":\"api\",\"url\":\"http://localhost:11434/v1/chat/completions\",\"params\":{\"model\":\"ibm/granite-docling:258m\",\"temperature\":0.0,\"max_tokens\":8192},\"timeout\":180.0,\"concurrency\":1},\"scale\":2.0}}"
}
```

> Hinweis: Beim nativen Setup ist Ollama über `http://localhost:11434` erreichbar.
> `host.docker.internal` ist nur in Docker-Netzwerken nötig.

---

## Server-Konfiguration (nativ, start_docling_native.sh)

### Was wir geändert haben (vs. Upstream-Default)

| Setting | Upstream-Default | Unser Wert | Grund |
|---------|-----------------|------------|-------|
| OCR-Engine | `rapidocr` (auto) | `ocrmac de-DE+en-US, accurate` | Apple Vision, beste Deutsch-Qualität |
| OCR-Laufzeit | Container (Tesseract) | nativ macOS (Apple Vision) | ocrmac funktioniert nur nativ |
| GPU | CPU (Docker, kein GPU-Passthrough) | MPS (Metal, nativ) | Layout- und Tabellen-Modelle |
| SmolVLM | nicht geladen | geladen (MPS) | Bilder beschreiben |
| UI | disabled | enabled | Web-Interface |
| Workers | 1 | 2 | Parallelverarbeitung |
| Batch sizes | 1 | 4 | Throughput |

### OCR Override Mechanismus (nativ)

```bash
DOCLING_SERVE_CUSTOM_OCR_PRESETS='{"auto":{"kind":"ocrmac","lang":["de-DE","en-US"],"recognition":"accurate"}}'
```

Da alle Clients standardmäßig `ocr_preset=auto` senden, überschreiben wir das `"auto"` Preset mit ocrmac+Deutsch. Clients müssen **nichts** ändern.

### Wichtige Env-Variablen (aus start_docling_native.sh)

| Variable | Wert | Zweck |
|---|---|---|
| `DOCLING_SERVE_CUSTOM_OCR_PRESETS` | `{"auto":{"kind":"ocrmac",...}}` | ocrmac als Default für alle Requests |
| `DOCLING_SERVE_ENG_LOC_NUM_WORKERS` | `2` | Parallele Konvertierungen |
| `DOCLING_SERVE_LOAD_MODELS_AT_BOOT` | `true` | Modelle beim Start laden |

### Docker-Fallback (compose.yaml — nicht empfohlen)

Die Docker-Variante ist in `compose.yaml` konfiguriert (Tesseract + tessdata_best).
Docker auf macOS hat kein GPU-Passthrough (kein Metal im Container) und ocrmac
funktioniert nicht im Container. Für Deutsch liefert die Docker-Variante
deutlich schlechtere Ergebnisse. Nur im Notfall:

```bash
docker compose up -d
docker compose down
```

---

## Quick-Reference

```bash
# Basis (gut für die meisten Dokumente)
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@doc.pdf" \
  -F "to_format=md" \
  -F "do_picture_description=true" \
  -F "include_images=true" \
  -F "picture_description_area_threshold=0.005"

# Gescanntes Dokument
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@scanned.pdf" \
  -F "to_format=md" \
  -F "force_ocr=true"

# Zertifikat / komplexes Layout
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@certificate.pdf" \
  -F "pipeline=vlm" \
  -F "vlm_pipeline_preset=granite_docling"

# Für RAG (mit Chunking)
curl -X POST http://localhost:5001/v1/chunk/hierarchical/file \
  -F "files=@doc.pdf" \
  -F "to_format=md"

# Nur bestimmte Seiten
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@doc.pdf" \
  -F "to_format=md" \
  -F "page_range=[1,10]"
```
