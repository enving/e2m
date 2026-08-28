#!/usr/bin/env bash
# Optimierter Docling-Wrapper mit Post-Processing
# Usage: ./docling_convert.sh <file.pdf> [options]
#   --vlm          VLM-Pipeline (Ollama granite-docling, besser für Zertifikate/Scans)
#   --force-ocr    OCR auch auf native Text erzwingen
#   --no-images    Ohne Bildbeschreibung (schneller)
#   --async        Async-Modus für große Dateien
#   --out <file>   Ausgabedatei (Standard: stdout)
#   --pages <n-m>  Nur Seiten n bis m (z.B. "1-5")

set -euo pipefail

BASE_URL="http://localhost:5001"
FILE=""
PIPELINE="standard"
FORCE_OCR="false"
DO_IMAGES="true"
ASYNC="false"
OUT=""
PAGES=""

# Args parsen
while [[ $# -gt 0 ]]; do
  case "$1" in
    --vlm) PIPELINE="vlm"; shift ;;
    --force-ocr) FORCE_OCR="true"; shift ;;
    --no-images) DO_IMAGES="false"; shift ;;
    --async) ASYNC="true"; shift ;;
    --out) OUT="$2"; shift 2 ;;
    --pages) PAGES="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 <file.pdf> [--vlm] [--force-ocr] [--no-images] [--async] [--out file] [--pages n-m]"
      exit 0 ;;
    *) FILE="$1"; shift ;;
  esac
done

if [[ -z "$FILE" ]]; then
  echo "Error: Keine Datei angegeben" >&2
  exit 1
fi

if [[ ! -f "$FILE" ]]; then
  echo "Error: Datei nicht gefunden: $FILE" >&2
  exit 1
fi

# Temp files cleanup
TMPFILES=""
cleanup() { [[ -n "$TMPFILES" ]] && rm -f $TMPFILES 2>/dev/null; true; }
trap cleanup EXIT

# Post-Processing
process_result() {
  python3 -c "
import sys, re, json

raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception as e:
    print('ERROR: Ungültige API-Antwort:', e, file=sys.stderr)
    print(raw[:500], file=sys.stderr)
    sys.exit(1)

if data.get('status') == 'failure':
    print('ERROR: Konvertierung fehlgeschlagen:', data.get('errors'), file=sys.stderr)
    sys.exit(1)

content = data.get('document', {}).get('md_content', '')
if not content:
    print('ERROR: Kein Inhalt in Antwort', file=sys.stderr)
    print(json.dumps(data, indent=2)[:500], file=sys.stderr)
    sys.exit(1)

# Nur Format-Bereinigung — KEINE inhaltlichen Korrekturen.
# OCR-Qualität kommt aus der Engine (ocrmac nativ), nicht aus Post-Processing.
content = re.sub(r'<end_of_utteran[a-z]*>?', '', content)  # SmolVLM EOS-Token-Artefakt
content = re.sub(r'\n{3,}', '\n\n', content)               # Doppelte Leerzeilen
content = content.strip()

print(content)
"
}

# === Pipeline-Konfiguration ===
if [[ "$PIPELINE" == "vlm" ]]; then
  # VLM via Ollama: als JSON options-Datei senden (Form-Encoding zerstört verschachteltes JSON)
  VLM_OPTIONS=$(mktemp /tmp/docling_vlm_XXXXXX.json)
  TMPFILES="$VLM_OPTIONS"
  cat > "$VLM_OPTIONS" << 'VLMEOF'
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
      "url": "http://host.docker.internal:11434/v1/chat/completions",
      "params": {"model": "ibm/granite-docling:258m", "temperature": 0.0, "max_tokens": 8192},
      "timeout": 180.0,
      "concurrency": 1
    },
    "scale": 2.0
  }
}
VLMEOF
  ENDPOINT="${BASE_URL}/v1/convert/file"
  CURL_ARGS=(
    -F "files=@${FILE}"
    -F "options=@${VLM_OPTIONS};type=application/json"
  )

else
  # Standard-Pipeline mit Tesserocr+Deutsch (server-seitig konfiguriert)
  ENDPOINT="${BASE_URL}/v1/convert/file"
  CURL_ARGS=(
    -F "files=@${FILE}"
    -F "to_format=md"
    -F "force_ocr=${FORCE_OCR}"
    -F "ocr_preset=auto"
    -F "pipeline=standard"
  )

  # Bilder
  if [[ "$DO_IMAGES" == "true" ]]; then
    CURL_ARGS+=(
      -F "do_picture_description=true"
      -F "include_images=true"
      -F "picture_description_area_threshold=0.005"
      -F "do_picture_classification=true"
    )
  fi

  # Seitenbereich
  if [[ -n "$PAGES" ]]; then
    START=$(echo "$PAGES" | cut -d'-' -f1)
    END=$(echo "$PAGES" | cut -d'-' -f2)
    CURL_ARGS+=(-F "page_range=[${START},${END}]")
  fi
fi

# === Konvertierung ===
if [[ "$ASYNC" == "true" ]]; then
  echo "Starte asynchrone Konvertierung von $FILE..." >&2

  TASK_ID=$(curl -s -X POST "${ENDPOINT}/async" \
    "${CURL_ARGS[@]}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))")

  if [[ -z "$TASK_ID" ]]; then
    echo "Error: Kein Task-ID erhalten" >&2
    exit 1
  fi

  echo "Task-ID: $TASK_ID" >&2

  while true; do
    STATUS=$(curl -s "${BASE_URL}/v1/status/poll/${TASK_ID}" \
      | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))")
    echo "Status: $STATUS" >&2
    if [[ "$STATUS" == "success" || "$STATUS" == "failure" ]]; then break; fi
    sleep 3
  done

  RESULT=$(curl -s "${BASE_URL}/v1/result/${TASK_ID}" | process_result)

else
  RESULT=$(curl -s -X POST "${ENDPOINT}" \
    --max-time 300 \
    "${CURL_ARGS[@]}" \
    | process_result)
fi

# === Ausgabe ===
if [[ -n "$OUT" ]]; then
  echo "$RESULT" > "$OUT"
  echo "Gespeichert: $OUT" >&2
else
  echo "$RESULT"
fi
