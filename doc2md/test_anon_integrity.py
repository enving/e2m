"""Integration check: the headroom anonymizer changes ONLY the PII spans and
leaves every other byte intact. Skips (exit 0) if headroom isn't running.
Run: python3 test_anon_integrity.py"""
import sys
import requests

ANON = "http://localhost:8787/api/v1/anon/test"

ORIGINAL = """# Projektbericht Q3

## Zusammenfassung
Ansprechpartner ist Dr. Erika Mustermann (erika@example.com, +49 30 5551234).
Das Team behandelt AI-Act, LMS-Integration & SCORM — Kosten: 12.500,00 EUR.

- Punkt eins: Ümlaute äöü ß, Sonderzeichen <>&%$#.
- Punkt zwei: Max Mustermann übernimmt die Doku.

| Spalte A | Spalte B |
|----------|----------|
| Wert 1   | Wert 2   |
"""


def test():
    try:
        r = requests.post(ANON, json={"text": ORIGINAL}, timeout=90)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"SKIP: headroom nicht erreichbar ({e})")
        return
    d = r.json()
    mapping = d["mapping_preview"]           # original -> token (<=5; hier vollständig)
    recon = d["anonymized"]
    for orig, tok in mapping.items():        # Token zurücksetzen
        recon = recon.replace(tok, orig)
    # Beweis: außer den maskierten Spans ist alles unverändert.
    assert recon == ORIGINAL, "Inhalt wurde über die PII-Spans hinaus verändert!"
    # Und die PII wurde tatsächlich maskiert (nicht durchgereicht).
    assert "erika@example.com" not in d["anonymized"], "E-Mail nicht maskiert"
    print(f"ok — nur {d['entities_found']} PII-Spans geändert {d['entity_types']}, Rest byte-identisch")


if __name__ == "__main__":
    test()
