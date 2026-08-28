#!/usr/bin/env python3
"""
PreToolUse hook (Edit|Write): if the target file has a non-empty
`sharepoint_link` in its YAML frontmatter, remind Claude that a SharePoint
counterpart exists and when it was last confirmed synced. Informational only —
never blocks. Silent for everything else.
"""
import sys
import json


def frontmatter(path):
    """Return the top --- YAML block as a flat {key: value} dict, or {}."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            if f.readline().strip() != "---":
                return {}
            out = {}
            for line in f:
                if line.strip() == "---":
                    break
                if ":" in line and not line.startswith((" ", "\t", "#")):
                    k, _, v = line.partition(":")
                    out[k.strip()] = v.split("#")[0].strip()  # drop inline comment
            return out
    except (OSError, UnicodeDecodeError):
        return {}


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    path = data.get("tool_input", {}).get("file_path")
    if not path:
        return

    fm = frontmatter(path)
    role = fm.get("role", "")
    link = fm.get("sharepoint_link", "")
    synced = fm.get("last_confirmed_synced") or "unbekannt"

    if role == "sharepoint-primary":
        # Sidecar: the .docx on SharePoint holds the content, the .md only metadata.
        msg = (
            "⚠️ Diese .md ist ein Sidecar (role: sharepoint-primary) — NICHT die "
            "Inhaltsquelle. Der eigentliche Text lebt in der SharePoint-Datei: "
            f"{link or '(sharepoint_link fehlt!)'}\n"
            f"Zuletzt bestätigt synchron: {synced}. Hier NUR Metadaten/Arbeitsnotizen "
            "pflegen — keinen Fließtext schreiben und den .md-Body nicht als aktuellen "
            "Inhalt vertrauen."
        )
    elif link:
        # local-primary with a counterpart link: gentle reminder to check first.
        msg = (
            f"ℹ️ Diese Datei hat einen SharePoint-Counterpart (zuletzt bestätigt synchron: {synced}).\n"
            f"Stabiler Link: {link}\n"
            "Vor dem Bearbeiten ggf. dort auf neuere Änderungen prüfen und nach dem "
            "Speichern 'last_confirmed_synced' im Frontmatter aktualisieren."
        )
    else:
        return  # local-primary without a link → nothing to say
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        }
    }))


if __name__ == "__main__":
    main()
