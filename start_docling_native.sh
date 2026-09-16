#!/usr/bin/env bash
# Startet docling-serve NATIV auf macOS (statt Docker).
# Vorteile: Apple Vision OCR (ocrmac, beste deutsche Texterkennung) + MPS-GPU.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"

# Wo liegt das venv? Reihenfolge: explizit gesetzt > im Repo > Service-Ort.
#
# Der Service-Ort ist NICHT optional-hübsch, sondern notwendig: liegt das Repo
# unter ~/Documents (oder ~/Desktop, ~/Downloads), darf ein LaunchAgent dort
# wegen macOS TCC nichts ausführen — "Operation not permitted", noch bevor das
# Skript startet. ~/.local/share ist nicht TCC-geschützt.
if [ -n "${DOC2MD_VENV:-}" ]; then
  VENV="$DOC2MD_VENV"
elif [ -x "$REPO/docling-native/bin/docling-serve" ]; then
  VENV="$REPO/docling-native"
else
  VENV="$HOME/.local/share/doc2md/docling-native"
fi

if [ ! -x "$VENV/bin/docling-serve" ]; then
  echo "docling-serve nicht gefunden in $VENV — siehe README, Abschnitt Installation." >&2
  exit 1
fi

# Docker-Variante stoppen falls sie läuft (Port 5001 Konflikt)
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^docling-serve$'; then
  echo "Stoppe Docker-Docling (Port 5001)..."
  docker stop docling-serve >/dev/null
fi

# Proxy für Modell-Downloads (HuggingFace) — bei Bedarf anpassen/setzen
export HTTPS_PROXY="${HTTPS_PROXY:-}"
export HTTP_PROXY="${HTTP_PROXY:-}"
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1}"

# === Docling-Konfiguration ===
export DOCLING_SERVE_ENABLE_UI=true
export DOCLING_SERVE_ENABLE_REMOTE_SERVICES=true
export DOCLING_SERVE_MAX_SYNC_WAIT=600
export DOCLING_SERVE_ENG_LOC_NUM_WORKERS=2
export DOCLING_SERVE_LOAD_MODELS_AT_BOOT=true

# OCR: Apple Vision Framework (ocrmac) — beste Engine für Deutsch auf dem Mac.
# "auto" wählt auf macOS automatisch ocrmac, wir machen es explizit:
export DOCLING_SERVE_DEFAULT_OCR_KIND=ocrmac
export DOCLING_SERVE_CUSTOM_OCR_PRESETS='{"auto":{"kind":"ocrmac","lang":["de-DE","en-US"],"recognition":"accurate"}}'
export DOCLING_SERVE_ALLOW_CUSTOM_OCR_CONFIG=true

# VLM: granite-docling via Ollama (nativ = localhost)
export DOCLING_SERVE_ALLOW_CUSTOM_VLM_CONFIG=true
export DOCLING_SERVE_ALLOW_CUSTOM_PICTURE_DESCRIPTION_CONFIG=true

# Picture Description: SmolVLM lokal (nutzt MPS-GPU nativ!)
export DOCLING_SERVE_DEFAULT_PICTURE_DESCRIPTION_PRESET=smolvlm

export UVICORN_HOST=0.0.0.0
export UVICORN_PORT=5001

echo "Starte docling-serve nativ (ocrmac + MPS)..."
exec "$VENV/bin/docling-serve" run --host 0.0.0.0 --port 5001
