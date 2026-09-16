#!/bin/bash
# Everything2Markdown — Komplett-Installation in einem Schritt (macOS).
#
#   ./install.sh                 docling-serve + Autostart + Finder-Kuerzel + doc2md
#   ./install.sh --with-ollama   zusaetzlich Ollama + qwen3:4b (Schlagwoerter, Pseudonymisierung)
#   ./install.sh --uninstall     Autostart, Quick Actions und doc2md entfernen
#
# Idempotent: ein zweiter Lauf repariert, statt doppelt zu installieren.
# Laeuft ohne Rueckfragen durch — geeignet, um es von einem Coding-Agenten
# ausfuehren zu lassen (siehe AGENTS.md).
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
RUNTIME="$HOME/.local/share/doc2md"
VENV="$RUNTIME/docling-native"
DOCLING_VERSION="1.32.0"
OLLAMA_MODEL="qwen3:4b"

step() { printf '\n\033[1m→ %s\033[0m\n' "$*"; }
fail() { printf '\n❌ %s\n' "$*" >&2; exit 1; }

WITH_OLLAMA=0
case "${1:-}" in
  --with-ollama) WITH_OLLAMA=1 ;;
  --uninstall)
    "$REPO/install-docling-agent.sh" --uninstall || true
    rm -rf "$HOME/Library/Services/Convert to Markdown.workflow" \
           "$HOME/Library/Services/Convert to Markdown with Tags.workflow" \
           "$HOME/Library/Services/Convert to Markdown pseudonymisiert.workflow"
    # Die Kuerzel-Eintraege (NSUserKeyEquivalents, pbs) bleiben stehen: ohne den
    # Dienst sind sie wirkungslos, und sie einzeln zu loeschen geht an cfprefsd vorbei.
    /System/Library/CoreServices/pbs -flush 2>/dev/null || true
    rm -f "$HOME/.local/bin/doc2md" "$HOME/.local/bin/doc_to_markdown.py" \
          "$HOME/.local/bin/doc_to_markdown_dialog.py"
    echo "✅ Entfernt. Das venv (~2-4 GB) liegt noch unter $VENV —"
    echo "   loeschen mit: rm -rf \"$RUNTIME\""
    echo "   Pseudonymisierungs-Schluessel bleiben in ~/Documents/doc2md-mappings/."
    exit 0 ;;
  "") ;;
  *) fail "Unbekannte Option: $1 (erlaubt: --with-ollama, --uninstall)" ;;
esac

# ---------------------------------------------------------------- Voraussetzungen
step "Voraussetzungen pruefen"
[ "$(uname -s)" = "Darwin" ] || fail "Nur macOS. Auf Linux/Windows: 'docker compose up -d' (siehe README)."

# Die Quick Actions laufen mit /usr/bin/python3 — das kommt mit den Command Line Tools.
xcode-select -p >/dev/null 2>&1 || fail "Xcode Command Line Tools fehlen.
   Einmal ausfuehren: xcode-select --install   (Dialog bestaetigen, danach install.sh erneut starten)"

# docling-serve braucht Python >= 3.10; das System-Python ist 3.9. 3.12 zuerst: damit getestet.
PY=""
for c in python3.12 python3.13 python3.11 python3.10 \
         /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3,10))' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ] && [ ! -x "$VENV/bin/docling-serve" ]; then
  if command -v brew >/dev/null 2>&1; then
    step "Python 3.12 via Homebrew installieren"
    brew install python@3.12
    PY="$(brew --prefix)/bin/python3.12"
  else
    fail "Python 3.10-3.13 fehlt. Installieren: https://www.python.org/downloads/macos/
   (oder Homebrew von https://brew.sh, dann erneut ./install.sh)"
  fi
fi
echo "   macOS $(sw_vers -productVersion), $(uname -m), Python fuer docling: ${PY:-vorhandenes venv}"

# ---------------------------------------------------------------- docling-serve
if [ -x "$VENV/bin/docling-serve" ] && "$VENV/bin/python" -c "import docling_serve, ocrmac" 2>/dev/null; then
  step "docling-serve ist bereits installiert ($VENV)"
else
  step "docling-serve $DOCLING_VERSION + ocrmac installieren (einige GB, dauert einige Minuten)"
  mkdir -p "$RUNTIME"
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip >/dev/null
  "$VENV/bin/pip" install "docling-serve==$DOCLING_VERSION" ocrmac
fi

# ---------------------------------------------------------------- Autostart
step "Autostart einrichten (LaunchAgent) — erster Start laedt Modelle, bis ~5 min"
"$REPO/install-docling-agent.sh"

# ---------------------------------------------------------------- doc2md
step "doc2md: Abhaengigkeit 'requests' fuer das System-Python"
/usr/bin/python3 -c "import requests" 2>/dev/null \
  || /usr/bin/python3 -m pip install --user --quiet requests

step "doc2md: Befehl + Finder-Kuerzel installieren"
"$REPO/doc2md/install-quick-actions.sh"

# ---------------------------------------------------------------- Ollama (optional)
if [ "$WITH_OLLAMA" = 1 ]; then
  step "Ollama + $OLLAMA_MODEL (fuer Schlagwoerter und Namenserkennung)"
  if ! command -v ollama >/dev/null 2>&1; then
    command -v brew >/dev/null 2>&1 || fail "Ollama fehlt und Homebrew ist nicht da.
   Ollama von https://ollama.com installieren, dann: ./install.sh --with-ollama"
    brew install ollama
  fi
  curl -s -m 3 http://localhost:11434/api/tags >/dev/null 2>&1 \
    || { command -v brew >/dev/null 2>&1 && brew services start ollama; } \
    || { nohup ollama serve >/dev/null 2>&1 & }
  for _ in $(seq 1 20); do curl -s -m 2 http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
  ollama pull "$OLLAMA_MODEL"
fi

# ---------------------------------------------------------------- Abschluss
step "Selbsttest"
curl -s -m 5 http://localhost:5001/health | grep -q ok && echo "   ✅ docling-serve antwortet" \
  || echo "   ⚠️  docling-serve antwortet noch nicht — Log: ~/Library/Logs/docling-serve.log"
if curl -s -m 3 http://localhost:11434/api/tags 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
  echo "   ✅ Ollama mit $OLLAMA_MODEL — Schlagwoerter und Pseudonymisierung verfuegbar"
else
  echo "   ℹ️  Ohne Ollama: nur Cmd+Shift+M (reine Umwandlung). Nachruesten: ./install.sh --with-ollama"
fi
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "   ℹ️  ~/.local/bin fehlt im PATH — fuer den Befehl 'doc2md':"
     echo "      echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc" ;;
esac

cat <<'EOS'

Fertig. Datei im Finder markieren, dann:

  Cmd+Shift+M      in Markdown umwandeln
  Cmd+Ctrl+M       + Schlagwoerter            (braucht Ollama)
  Cmd+Ctrl+Opt+M   + Schlagwoerter + Pseudonymisierung (braucht Ollama)

Oder Rechtsklick → Schnelle Aktionen. Die .md landet neben der Originaldatei;
Rueckmeldung kommt als Mitteilung. Im Terminal: doc2md datei.pdf
EOS
