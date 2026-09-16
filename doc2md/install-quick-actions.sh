#!/bin/bash
# Installiert die Finder Quick Actions fuer doc2md und belegt die Tastenkuerzel.
#
#   Cmd+Shift+M   "Convert to Markdown"             -> reine Konvertierung
#   Cmd+Ctrl+M    "Convert to Markdown with Tags"   -> + Verschlagwortung via Ollama
#   Cmd+Ctrl+Opt+M "Convert to Markdown pseudonymisiert" -> + Tags + Pseudonymisierung,
#                  Zuordnung nach ~/Documents/doc2md-mappings/ (nicht neben die .md)
#
# Ersetzt die Klickstrecke aus dem README (Automator -> Quick Action -> System-
# einstellungen): baut die .workflow-Bundles direkt und schreibt die Kuerzel an
# BEIDE Stellen, die macOS dafuer kennt: NSGlobalDomain/NSUserKeyEquivalents
# ("App-Kurzbefehle", haengt am Menuetitel) und pbs/NSServicesStatus ("Dienste",
# haengt am Dienst selbst). Nur das erste reichte nicht — das Kuerzel loeste im
# Finder zeitweise gar nichts aus, waehrend Rechtsklick weiter funktionierte.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"

echo "→ Converter nach ~/.local/bin/ deployen"
mkdir -p "$HOME/.local/bin"
cp "$REPO/doc_to_markdown.py" "$REPO/doc_to_markdown_dialog.py" "$HOME/.local/bin/"
chmod +x "$HOME/.local/bin/doc_to_markdown.py" "$HOME/.local/bin/doc_to_markdown_dialog.py"
# Befehl 'doc2md' fuers Terminal — ein Skript statt eines Shell-Alias, damit es
# in jeder Shell und fuer Coding-Agenten gleich funktioniert.
cat > "$HOME/.local/bin/doc2md" <<'SH'
#!/bin/sh
exec /usr/bin/python3 "$HOME/.local/bin/doc_to_markdown.py" "$@"
SH
chmod +x "$HOME/.local/bin/doc2md"

/usr/bin/python3 - "$@" <<'PYEOF'
import os
import plistlib
import shutil
import subprocess
import uuid
from pathlib import Path

# (Menuename, Converter-Flags, Tastenkuerzel)
# Kuerzel-Syntax von NSUserKeyEquivalents: @=Cmd $=Shift ^=Ctrl ~=Option.
# Der Menuename darf KEINE Klammern enthalten — `defaults write -dict-add`
# kann solche Schluessel nicht parsen.
ACTIONS = [
    ("Convert to Markdown",           "",       "@$m"),
    ("Convert to Markdown with Tags", "--tags", "@^m"),
    ("Convert to Markdown pseudonymisiert",
     '--tags --pii pseudo --pii-map-dir "$HOME/Documents/doc2md-mappings"', "@^~m"),
]

SCRIPT = r'''export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"
# Ohne das puffert Python stdout blockweise, sobald es in eine Datei geht — im
# Log stehen dann Fehler (stderr) vor den Statuszeilen, die ihnen vorausgingen.
export PYTHONUNBUFFERED=1
LOG="$HOME/Library/Logs/doc2md.log"
mkdir -p "$HOME/Library/Logs"

# Detached starten: Automator haelt sonst einen File-Coordination-Claim auf die
# Auswahl, und ein synchroner Read einer Cloud-only-OneDrive-Datei laeuft darin
# in [Errno 11] Resource deadlock avoided. Rueckmeldung kommt per --notify.
if [ "$#" -gt 0 ]; then
  nohup /usr/bin/python3 "$HOME/.local/bin/doc_to_markdown.py" --notify __FLAGS__ "$@" >> "$LOG" 2>&1 &
else
  # Keine Finder-Auswahl -> nativer Dateidialog (tkinter, keine Accessibility-Rechte noetig)
  nohup /usr/bin/python3 "$HOME/.local/bin/doc_to_markdown_dialog.py" __FLAGS__ >> "$LOG" 2>&1 &
fi
exit 0
'''


def build(name: str, flags: str) -> Path:
    bundle = Path.home() / "Library" / "Services" / f"{name}.workflow"
    action = {
        "action": {
            "AMAccepts": {"Container": "List", "Optional": True,
                          "Types": ["com.apple.cocoa.string"]},
            "AMActionVersion": "2.0.3",
            "AMApplication": ["Automator"],
            "AMParameterProperties": {k: {} for k in (
                "COMMAND_STRING", "CheckedForUserDefaultShell", "inputMethod",
                "shell", "source")},
            "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
            "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
            "ActionName": "Run Shell Script",
            "ActionParameters": {
                "COMMAND_STRING": SCRIPT.replace("__FLAGS__", flags),
                "CheckedForUserDefaultShell": True,
                "inputMethod": 1,          # 1 = Eingabe "als Argumente uebergeben"
                "shell": "/bin/zsh",
                "source": "",
            },
            "BundleIdentifier": "com.apple.RunShellScript",
            "CFBundleVersion": "2.0.3",
            "CanShowSelectedItemsWhenRun": False,
            "CanShowWhenRun": True,
            "Category": ["AMCategoryUtilities"],
            "Class Name": "RunShellScriptAction",
            "InputUUID": str(uuid.uuid4()).upper(),
            "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
            "OutputUUID": str(uuid.uuid4()).upper(),
            "UUID": str(uuid.uuid4()).upper(),
            "UnlocalizedApplications": ["Automator"],
            "arguments": {
                "0": {"default value": "", "name": "COMMAND_STRING",
                      "required": "0", "type": "0", "uuid": "0"},
                "1": {"default value": False, "name": "CheckedForUserDefaultShell",
                      "required": "0", "type": "0", "uuid": "1"},
                "2": {"default value": 0, "name": "inputMethod",
                      "required": "0", "type": "0", "uuid": "2"},
                "3": {"default value": "", "name": "source",
                      "required": "0", "type": "0", "uuid": "3"},
                "4": {"default value": "/bin/sh", "name": "shell",
                      "required": "0", "type": "0", "uuid": "4"},
            },
            "isViewVisible": 1,
            "location": "309.000000:253.000000",
            "nibPath": "/System/Library/Automator/Run Shell Script.action/"
                       "Contents/Resources/Base.lproj/main.nib",
        },
        "isViewVisible": 1,
    }

    wflow = {
        "AMApplicationBuild": "528",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [action],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {},
            "applicationPaths": [],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 11,
            "processesInput": 0,
            "serviceApplicationBundleID": "",
            "serviceApplicationPath": "",
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": 0,
            "useAutomaticInputType": 0,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }

    # Kein NSRequiredContext: so bietet auch eine App ausserhalb des Finders den
    # Dienst an, sofern sie eine Datei als Auswahl liefern kann.
    info = {
        "CFBundleName": name,
        "NSServices": [{
            "NSMenuItem": {"default": name},
            "NSMessage": "runWorkflowAsService",
            "NSSendFileTypes": ["public.item"],
        }],
    }

    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "Contents").mkdir(parents=True)
    with open(bundle / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info, f)
    with open(bundle / "Contents" / "document.wflow", "wb") as f:
        plistlib.dump(wflow, f)
    return bundle


for name, flags, key in ACTIONS:
    print(f"→ Quick Action: {build(name, flags)}")

# pbs kennt den neuen Dienst erst nach einem Flush; das Kuerzel wiederum wird
# erst nach dem naechsten Flush im Services-Menue wirksam.
subprocess.run(["/System/Library/CoreServices/pbs", "-flush"], check=False)
for name, flags, key in ACTIONS:
    subprocess.run(["defaults", "write", "NSGlobalDomain", "NSUserKeyEquivalents",
                    "-dict-add", name, key], check=True)
    subprocess.run(["defaults", "write", "pbs", "NSServicesStatus", "-dict-add",
                    f'"(null) - {name} - runWorkflowAsService"',
                    "{enabled_context_menu = 1; enabled_services_menu = 1; "
                    f'key_equivalent = "{key}";}}'], check=True)
    print(f"→ Kuerzel: {key}  ->  {name}")
subprocess.run(["/System/Library/CoreServices/pbs", "-flush"], check=False)
PYEOF

echo "→ Finder neu starten, damit das Kuerzel sofort greift"
killall Finder 2>/dev/null || true

cat <<'EOS'

Fertig.

  Cmd+Shift+M   Konvertieren
  Cmd+Ctrl+M    Konvertieren + verschlagworten (braucht Ollama)
  Cmd+Ctrl+Opt+M Konvertieren + verschlagworten + pseudonymisieren
                Zuordnung: ~/Documents/doc2md-mappings/ (nicht mit der .md teilen)

Ohne Finder-Auswahl oeffnet sich ein Dateidialog.
Schon laufende Apps kennen das Kuerzel erst nach einem Neustart der App.
Log: ~/Library/Logs/doc2md.log

Deinstallieren:
  rm -rf ~/Library/Services/"Convert to Markdown".workflow \
         ~/Library/Services/"Convert to Markdown with Tags".workflow \
         ~/Library/Services/"Convert to Markdown pseudonymisiert".workflow
  defaults delete NSGlobalDomain NSUserKeyEquivalents
  defaults delete pbs NSServicesStatus
EOS
