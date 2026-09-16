#!/bin/bash
# Startet docling-serve automatisch beim Login und haelt es am Leben.
#
# Ohne das laeuft der Server nur so lange wie das Terminal, in dem er gestartet
# wurde — und die doc2md-Shortcuts scheitern dann mit "docling-serve laeuft nicht".
#
#   ./install-docling-agent.sh            installieren + sofort starten
#   ./install-docling-agent.sh --uninstall  wieder entfernen
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.doc2md.docling-serve"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/docling-serve.log"
DOMAIN="gui/$(id -u)"

# Laufzeit-Ort ausserhalb der TCC-geschuetzten Ordner. Liegt das Repo unter
# ~/Documents, ~/Desktop oder ~/Downloads, bekommt ein LaunchAgent dort nur
# "Operation not permitted" — er darf das Start-Skript nicht einmal ausfuehren.
# Deshalb laufen Skript UND venv aus ~/.local/share, das Repo bleibt Quelle.
RUNTIME="$HOME/.local/share/doc2md"
VENV="$RUNTIME/docling-native"
LAUNCHER="$RUNTIME/start_docling_native.sh"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "✅ LaunchAgent entfernt. docling-serve startet nicht mehr automatisch."
  echo "   venv bleibt unter ~/.local/share/doc2md/ liegen."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs" "$RUNTIME"

# venv an den Laufzeit-Ort bringen, falls es noch im Repo liegt.
if [ ! -x "$VENV/bin/docling-serve" ]; then
  if [ -x "$REPO/docling-native/bin/docling-serve" ]; then
    echo "→ venv nach $VENV verschieben (raus aus dem TCC-geschuetzten Ordner)"
    mv "$REPO/docling-native" "$VENV"
    # Console-Scripts tragen den alten Pfad im Shebang.
    while IFS= read -r f; do
      sed -i '' "1s|^#\!$REPO/docling-native|#\!$VENV|" "$f"
    done < <(grep -rl "^#\!$REPO/docling-native" "$VENV/bin" 2>/dev/null || true)
    sed -i '' "s|$REPO/docling-native|$VENV|g" "$VENV/pyvenv.cfg" 2>/dev/null || true
  else
    echo "❌ Kein docling-serve venv gefunden — weder in $VENV noch in $REPO/docling-native." >&2
    echo "   Erst das venv anlegen (siehe README, Abschnitt Installation)." >&2
    exit 1
  fi
fi

"$VENV/bin/python" -c "import docling_serve" 2>/dev/null || {
  echo "❌ $VENV ist kaputt (docling_serve nicht importierbar)." >&2
  exit 1
}

# Start-Skript an den Laufzeit-Ort kopieren — das Repo selbst ist fuer launchd
# unerreichbar. Bei Aenderungen am Skript dieses Install-Skript erneut laufen lassen.
cp "$REPO/start_docling_native.sh" "$LAUNCHER"
chmod +x "$LAUNCHER"

# ProgramArguments zeigt auf das Start-Skript, nicht auf das Binary: dort stehen
# die OCR-/VLM-Env-Variablen, die docling-serve braucht.
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>/bin/bash</string>
		<string>$LAUNCHER</string>
	</array>
	<key>WorkingDirectory</key>
	<string>$RUNTIME</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>DOC2MD_VENV</key>
		<string>$VENV</string>
	</dict>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>ThrottleInterval</key>
	<integer>30</integer>
	<key>ProcessType</key>
	<string>Background</string>
	<key>StandardOutPath</key>
	<string>$LOG</string>
	<key>StandardErrorPath</key>
	<string>$LOG</string>
</dict>
</plist>
PLISTEOF

plutil -lint "$PLIST" >/dev/null

# bootout vor bootstrap, damit ein erneuter Lauf den Agent sauber ersetzt.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
# bootout ist asynchron: solange der alte Prozess noch herunterfaehrt, scheitert
# bootstrap mit "5: Input/output error". Also warten, bis der Dienst weg ist.
for _ in $(seq 1 30); do
  launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
  sleep 1
done
bootstrapped=0
for _ in 1 2 3; do
  if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then bootstrapped=1; break; fi
  sleep 3
done
[ "$bootstrapped" = 1 ] || { launchctl bootstrap "$DOMAIN" "$PLIST"; exit 1; }

echo "→ LaunchAgent installiert: $PLIST"
echo "→ warte auf docling-serve (laedt die Modelle, dauert beim ersten Mal ~90 s)"

for _ in $(seq 1 60); do
  if curl -s -m 3 http://localhost:5001/health >/dev/null 2>&1; then
    echo "✅ docling-serve laeuft und antwortet auf http://localhost:5001/health"
    echo "   Startet ab jetzt bei jedem Login automatisch."
    echo "   Log: $LOG"
    exit 0
  fi
  sleep 5
done

echo "⚠️  Nach 5 Minuten noch keine Antwort. Log pruefen: $LOG" >&2
exit 1
