"""Unit-Check der lokalen PII-Modi — kein Netz, kein Ollama, kein docling.
Run: python3 test_pseudonymize.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from doc_to_markdown import pseudonymize, scrub_pii, _PII_MODES  # noqa: E402

TEXT = """# Projektbericht Q3

Ansprechpartner ist Erika Mustermann (erika@example.com, +49 30 5551234).
Rueckfragen an Max Mustermann (max@example.com, +49 30 5555678).
Zweite Mail von Erika: erika@example.com — gleiche Adresse wie oben.
Buero: Bouchestrasse 78, 12435 Berlin. IBAN DE89370400440532013000.

- Ümlaute äöü ß, Sonderzeichen <>&%$#.
"""

NAMES = ["Erika Mustermann", "Max Mustermann"]


def test_consistency():
    """Derselbe Wert -> derselbe Token; verschiedene Werte -> verschiedene Tokens."""
    out, mapping = pseudonymize(TEXT, NAMES)
    assert out.count("[EMAIL_1]") == 2, f"gleiche Mail nicht konsistent: {out}"
    assert "[EMAIL_2]" in out, "zweite, andere Mail bekam keinen eigenen Token"
    assert mapping["[EMAIL_1]"] == "erika@example.com"
    assert mapping["[EMAIL_2]"] == "max@example.com"
    assert mapping["[PERSON_1]"] in NAMES and mapping["[PERSON_2]"] in NAMES
    assert mapping["[PERSON_1]"] != mapping["[PERSON_2]"]
    print("ok — Tokens sind konsistent und unterscheidbar")


def test_reversible():
    """Genau das, was Pseudonymisierung von Anonymisierung trennt: umkehrbar."""
    out, mapping = pseudonymize(TEXT, NAMES)
    recon = out
    for tok, orig in mapping.items():
        recon = recon.replace(tok, orig)
    assert recon == TEXT, "Rueckbau ergibt nicht das Original"
    print(f"ok — {len(mapping)} Tokens, Rueckbau byte-identisch")


def test_no_pii_left():
    out, _ = pseudonymize(TEXT, NAMES)
    for leak in ["erika@example.com", "max@example.com", "Erika Mustermann",
                 "Max Mustermann", "DE89370400440532013000"]:
        assert leak not in out, f"nicht maskiert: {leak}"
    print("ok — keine der bekannten PII steht noch im Klartext")


def test_mask_is_lossy():
    """Gegenprobe: scrub_pii ist anonymisierend, NICHT pseudonymisierend."""
    out, n = scrub_pii(TEXT)
    assert out.count("[email]") == 3, "erwartet: alle Mails auf denselben Platzhalter"
    assert "Erika Mustermann" in out, "scrub_pii erkennt per Design keine Namen"
    print(f"ok — scrub_pii kollabiert {n} Stellen auf generische Platzhalter (Namen bleiben)")


def test_longest_name_first():
    """'Erika' darf 'Erika Mustermann' nicht vorher zerschneiden."""
    out, mapping = pseudonymize("Erika Mustermann und Erika.", ["Erika", "Erika Mustermann"])
    assert "Mustermann" not in out, f"Teilname zuerst ersetzt: {out}"
    print("ok — laengster Name zuerst ersetzt")


PROTOKOLL = """Teilnehmende: Dr. Malte Oßwald (0170 5550987), Jana Brückner.
Frau Brückner stellte den Zeitplan vor. Herr Dr. Oßwald nannte Rechnung Nr. 2026-0815.
Mail an kaya@kaya-consulting.example, Herr Kaya antwortet bis 30.09.2026.
Emma Schäfer (geb. 03.05.1991, Personalnummer 48213) wechselt ins Team.
- Malte Oßwald: Budgetfreigabe
"""


def test_name_variants():
    """Anrede + Nachname, Name ohne Titel: alles derselben Person zugeordnet."""
    names = ["Dr. Malte Oßwald", "Jana Brückner", "Herr Kaya", "Süleyman Kaya", "Emma Schäfer"]
    out, mapping = pseudonymize(PROTOKOLL, names)
    for leak in ["Oßwald", "Brückner", "Kaya ", "Schäfer", "Malte"]:
        assert leak not in out, f"nicht ersetzt: {leak!r} in {out}"
    person = next(t for t, v in mapping.items() if v == "Malte Oßwald")
    assert f"Herr Dr. {person[:-1]}_NACHNAME]" in out, out
    assert out.count(person) == 2, "voller Name ohne Titel nicht derselbe Token"
    print("ok — Nachnamen mit Anrede und Namen ohne Titel werden ersetzt")


def test_email_not_split_by_surname():
    out, mapping = pseudonymize(PROTOKOLL, ["Süleyman Kaya", "Herr Kaya"])
    assert mapping["[EMAIL_1]"] == "kaya@kaya-consulting.example", mapping
    print("ok — Nachname zerschneidet keine E-Mail-Adresse")


def test_birthdate_and_ids():
    out, mapping = pseudonymize(PROTOKOLL, [])
    assert "03.05.1991" not in out and "geb. [GEBURTSDATUM_1]" in out, out
    assert "48213" not in out and "Personalnummer [KENNUNG_1]" in out, out
    assert "30.09.2026" in out, "normales Datum faelschlich ersetzt"
    assert "2026-0815" in out, "Rechnungsnummer faelschlich als Telefon ersetzt"
    assert "0170 5550987" not in out
    print("ok — Geburtsdatum/Kennnummer ersetzt, Termin und Rechnungsnummer bleiben")


def test_shared_surname_is_not_attributed():
    """Zwei Mustermanns: 'Herr Mustermann' darf keiner Person zugeschlagen werden."""
    out, mapping = pseudonymize("Herr Mustermann kam.", NAMES)
    assert "Mustermann" not in out
    assert "[NACHNAME_1]" in out, out
    print("ok — mehrdeutiger Nachname bekommt eigenen Token")


def test_reversible_with_variants():
    out, mapping = pseudonymize(PROTOKOLL, ["Dr. Malte Oßwald", "Jana Brückner",
                                            "Süleyman Kaya", "Emma Schäfer"])
    recon = out
    for tok, orig in mapping.items():
        recon = recon.replace(tok, orig)
    assert recon == PROTOKOLL, recon
    print("ok — Rueckbau auch mit Namensteilen byte-identisch")


def test_modes_declared():
    assert _PII_MODES == ("off", "mask", "pseudo", "service", "auto")
    print("ok — PII-Modi wie dokumentiert")


if __name__ == "__main__":
    for fn in [test_consistency, test_reversible, test_no_pii_left,
               test_mask_is_lossy, test_longest_name_first, test_name_variants,
               test_email_not_split_by_surname, test_birthdate_and_ids,
               test_shared_surname_is_not_attributed, test_reversible_with_variants,
               test_modes_declared]:
        fn()
    print("\nalle Checks bestanden")
