#!/bin/bash
# Setup VSCode Keybinding für "Convert to Markdown"
# Cmd+Shift+M öffnet File Dialog und konvertiert

KEYBINDINGS_FILE="$HOME/Library/Application Support/Code/User/keybindings.json"

# Backup erstellen
if [ -f "$KEYBINDINGS_FILE" ]; then
    cp "$KEYBINDINGS_FILE" "$KEYBINDINGS_FILE.backup"
    echo "✅ Backup erstellt: $KEYBINDINGS_FILE.backup"
fi

# Wenn Datei nicht existiert, mit leerer JSON starten
if [ ! -f "$KEYBINDINGS_FILE" ]; then
    mkdir -p "$(dirname "$KEYBINDINGS_FILE")"
    echo "[]" > "$KEYBINDINGS_FILE"
fi

# Neues Keybinding hinzufügen
python3 << 'PYTHON_EOF'
import json
import os

keybindings_file = os.path.expanduser("~/Library/Application Support/Code/User/keybindings.json")

# Lese existierende Keybindings
try:
    with open(keybindings_file, 'r') as f:
        content = f.read().strip()
        keybindings = json.loads(content) if content else []
except Exception as e:
    print(f"❌ Fehler beim Lesen: {e}")
    keybindings = []

# Entferne altes Binding falls vorhanden
keybindings = [kb for kb in keybindings if kb.get("command") != "workbench.action.tasks.runTask" or kb.get("args") != "Convert to Markdown"]

# Füge neues Binding hinzu
new_binding = {
    "key": "cmd+shift+m",
    "command": "workbench.action.tasks.runTask",
    "args": "Convert to Markdown"
}

keybindings.append(new_binding)

# Schreibe zurück
with open(keybindings_file, 'w') as f:
    json.dump(keybindings, f, indent=2)

print("✅ VSCode Keybinding installiert:")
print("   Taste: Cmd+Shift+M")
print("   Aktion: Convert to Markdown")
print(f"   Datei: {keybindings_file}")
PYTHON_EOF

echo ""
echo "📝 Nächste Schritte:"
echo "   1. VSCode neuladen (Cmd+R) oder vollständig neu starten"
echo "   2. Eine Datei im Editor öffnen/wählen"
echo "   3. Drücke: Cmd+Shift+M"
echo "   4. Konvertierung lädt!"
