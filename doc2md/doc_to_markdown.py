#!/usr/bin/env python3
"""
Document to Markdown converter using docling-serve REST API.
Converts documents to Markdown and adds frontmatter metadata.
"""

import os
import re
import sys
import json
import time
import errno
import fcntl
import hashlib
import argparse
import contextlib
import warnings
import subprocess

# Suppress urllib3 NotOpenSSLWarning (system Python 3.9 links LibreSSL);
# stderr output makes the Automator Quick Action show an error dialog
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import requests
from pathlib import Path
from datetime import datetime


DOCLING_API = "http://localhost:5001"

# Wie lange auf docling-serve gewartet wird. Die alten 300 s reichten fuer echte
# Dokumente nicht: ein 62-Seiten-PDF braucht ~100 s ohne und ~210 s mit
# Bildbeschreibung — und sobald mehrere Jobs um die Worker konkurrieren, ist das
# ueberschritten. Die Quick Action laeuft detached, ein grosszuegiger Wert kostet
# also nichts ausser Geduld.
CONVERT_TIMEOUT = int(os.environ.get("DOC2MD_TIMEOUT", "1800"))
OLLAMA_API = "http://localhost:11434"
OLLAMA_MODEL = os.environ.get("DOC2MD_OLLAMA_MODEL", "qwen3:4b")

# Deterministic PII patterns — the RELIABLE anonymization floor (whole document).
# Namen stehen nicht hier: Regex erkennt sie nicht, das LLM liefert sie best-effort.
# Eine benannte Gruppe "v" heisst: nur dieser Teil ist PII, der Kontext davor
# ("geb.", "Personalnummer") bleibt lesbar stehen.
#
# Zwei Stufen, weil Namen dazwischen ersetzt werden: E-Mail und IBAN VOR den
# Namen (sonst zerschneidet ein Nachname wie "Kaya" die Adresse kaya@kaya-...),
# alles andere DANACH (sonst verschluckt "Adresse" einen Namen in derselben Zeile).
_PII_EARLY = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Za-z0-9]){11,30}\b"), "[iban]"),
]
_PII_LATE = [
    # Deutsche Straße + Hausnummer: "Bouchestraße 78", "Musterweg 3a".
    (re.compile(r"\b[A-ZÄÖÜ][\wäöüß.-]*(?:straße|strasse|str\.|weg|platz|allee|gasse|ring|damm|ufer)\s+\d+\s*[a-z]?\b"), "[adresse]"),
    # PLZ + Ort: "12435 Berlin".
    (re.compile(r"\b\d{5}\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.-]+(?:\s[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.-]+)?"), "[ort]"),
    # Geburtsdatum nur mit Kontext — ein nacktes Datum ist meist ein Termin.
    (re.compile(r"(?:\bgeb\.|\bgeboren(?:\s+am)?|\bGeburtsdatum:?|\bGeb\.-Datum:?)\s*"
                r"(?P<v>\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4})", re.I), "[geburtsdatum]"),
    # Personenbezogene Kennnummern, ebenfalls nur mit Schluesselwort davor.
    (re.compile(r"\b(?:Personal|Mitarbeiter|Kunden|Versicherten|Versicherungs|"
                r"Sozialversicherungs|SV-|Renten(?:versicherungs)?|Steuer|Ausweis|"
                r"Personalausweis|Reisepass|Pass|Matrikel|Patienten|Mitglieds)"
                r"(?:-?Nr\.?|-?Nummer|nummer|-?ID|-?Identifikationsnummer)\s*:?\s*"
                r"(?P<v>[A-Z0-9](?:[A-Z0-9/-]| (?=[A-Z0-9])){2,})"), "[kennung]"),
    # Telefon beginnt mit + oder 0 — sonst trifft das Muster Rechnungsnummern
    # ("2026-0815") und Zeitraeume.
    (re.compile(r"(?<![\w+])(?:\+|\(?0)[\d /()-]{5,}\d(?!\d)"), "[telefon]"),
]
_PII = _PII_EARLY + _PII_LATE


def _sub_pii(pat, text, replace):
    """Wendet ein PII-Muster an; bei Gruppe "v" wird nur diese ersetzt."""
    def repl(m):
        if "v" in pat.groupindex:
            s, e = m.span("v")
            return m.group(0)[:s - m.start()] + replace(m.group("v")) + m.group(0)[e - m.start():]
        return replace(m.group(0))
    return pat.subn(repl, text)


def scrub_pii(text: str):
    """Mask structured PII deterministically. Returns (text, count)."""
    n = 0
    for pat, placeholder in _PII:
        text, k = _sub_pii(pat, text, lambda _v, p=placeholder: p)
        n += k
    return text, n


_PII_MODES = ("off", "mask", "pseudo", "service", "auto")

# Anrede und Titel gehoeren nicht zum Namen: "Herr Dr. Oßwald" -> "Oßwald". Sie
# bleiben im Text stehen ("Herr Dr. [PERSON_2_NACHNAME]") — das ist unkritisch und
# haelt den Satz lesbar.
_NAME_PREFIX = re.compile(
    r"^(?:(?:Herr|Herrn|Frau|Hr\.|Fr\.|Dr\.|Prof\.|Dipl\.-\w+\.?|med\.|rer\.\s?nat\.|"
    r"Mag\.|Ing\.|Mr\.?|Mrs\.?|Ms\.?)\s*)+")


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name)).strip(" ,;:()\"'")
    return _NAME_PREFIX.sub("", name).strip()


def name_variants(names):
    """
    Macht aus den gefundenen Namen alle Schreibweisen, die im Text vorkommen koennen.
    Gibt [(schreibweise, schluessel)] zurueck, laengste Schreibweise zuerst.

    schluessel ist (person_index, teil): teil = "" fuer den vollen Namen,
    "NACHNAME"/"VORNAME" fuer einzeln stehende Teile. Ein Nachname, den zwei
    Personen teilen, ist mehrdeutig und bekommt einen eigenen Schluessel
    (None, "NACHNAME"), damit er keiner Person falsch zugeordnet wird.
    """
    cleaned = {_clean_name(n) for n in names or []}
    cleaned = {n for n in cleaned if len(n) >= 2}
    full = sorted((n for n in cleaned if " " in n), key=len, reverse=True)
    single = [n for n in cleaned if " " not in n]

    persons = list(full)
    parts = {}  # teilname -> set((person_index, rolle))
    for i, n in enumerate(persons):
        words = n.split(" ")
        parts.setdefault(words[-1], set()).add((i, "NACHNAME"))
        if len(words) > 1:
            parts.setdefault(words[0], set()).add((i, "VORNAME"))
    # Einzelnamen, die zu keiner vollen Person passen, sind eigene Personen.
    for n in single:
        if n not in parts:
            persons.append(n)

    variants = [(n, (i, "")) for i, n in enumerate(persons)]
    for part, owners in parts.items():
        if len(part) < 3 or part in persons:
            continue
        if len(owners) == 1:
            (i, role), = owners
            variants.append((part, (i, role)))
        else:
            role = sorted({r for _, r in owners})[0]
            variants.append((part, (None, role)))
    variants.sort(key=lambda v: len(v[0]), reverse=True)
    return variants


def _name_pattern(name: str):
    # Wortgrenzen, beliebiger Leerraum zwischen den Teilen (Tabellen, Umbrueche),
    # Genitiv-s erlaubt ("Brückners") — das s bleibt ausserhalb des Tokens.
    body = r"\s+".join(re.escape(w) for w in name.split(" "))
    return re.compile(rf"(?<![\w@.-]){body}(?=s?(?![\w@]))")


def pseudonymize(text: str, names=None):
    """
    PSEUDONYMISIEREN: PII durch konsistente, nummerierte Tokens ersetzen
    ([EMAIL_1], [PERSON_2], [PERSON_2_NACHNAME], ...). Gibt (text, mapping) zurueck,
    mapping = {token: original}.

    Unterschied zu scrub_pii(): derselbe Ausgangswert bekommt immer denselben Token.
    Dadurch bleibt erhalten, wer mit wem korrespondiert, und der Text laesst sich ueber
    das Mapping wieder herstellen. Genau deshalb ist das Mapping re-identifizierende
    Information und muss wie die Rohdaten geschuetzt werden — es ist Pseudonymisierung
    im Sinne von Art. 4 Nr. 5 DSGVO, keine Anonymisierung.
    """
    mapping = {}
    counters = {}
    reverse = {}

    def token_for(label, original):
        key = (label, original)
        if key in reverse:
            return reverse[key]
        counters[label] = counters.get(label, 0) + 1
        tok = f"[{label}_{counters[label]}]"
        mapping[tok] = original
        reverse[key] = tok
        return tok

    def structured(text, patterns):
        for pat, placeholder in patterns:
            label = placeholder.strip("[]").upper()
            text, _ = _sub_pii(pat, text, lambda v, _l=label: token_for(_l, v))
        return text

    text = structured(text, _PII_EARLY)

    # Personen-Tokens: der volle Name bestimmt die Nummer, Namensteile haengen
    # daran ("[PERSON_2]" und "[PERSON_2_NACHNAME]" sind dieselbe Person).
    variants = name_variants(names)
    person_tok = {}
    for variant, (idx, role) in variants:
        pat = _name_pattern(variant)
        if not pat.search(text):
            continue
        if idx is None:
            tok = token_for(role, variant)
        else:
            full = next(v for v, k in variants if k == (idx, ""))
            if idx not in person_tok:
                person_tok[idx] = token_for("PERSON", full)
            tok = person_tok[idx] if not role else f"{person_tok[idx][:-1]}_{role}]"
            mapping[tok] = variant
        text = pat.sub(tok, text)

    return structured(text, _PII_LATE), mapping


# Groesse der Textstuecke fuer die Namenserkennung. Das Modell sieht jedes Stueck
# einzeln; die Ueberlappung faengt Namen, die genau auf einer Grenze liegen.
_NAME_CHUNK = 4000
_NAME_OVERLAP = 200


def ollama_person_names(text: str, model: str = OLLAMA_MODEL) -> list:
    """
    Namenserkennung ueber das lokale LLM, fuer die lokalen PII-Modi — ueber das
    GANZE Dokument, in Stuecken.

    Ehrliche Grenzen: ein LLM ist kein NER-Modell. Es uebersieht Namen und erfindet
    gelegentlich welche. Der headroom-Dienst (--pii service) macht das mit einem
    echten NER-Modell.

    Ist Ollama nicht erreichbar, wird NICHT still weitergemacht: ein pseudonymisiertes
    Dokument mit allen Namen im Klartext ist schlimmer als gar keins.
    """
    names = []
    step = _NAME_CHUNK - _NAME_OVERLAP
    for start in range(0, max(len(text), 1), step):
        chunk = text[start:start + _NAME_CHUNK]
        prompt = (
            "Extrahiere ALLE Personennamen aus dem Text: volle Namen, aber auch "
            "einzeln stehende Nachnamen oder Vornamen (z. B. nach Herr/Frau). "
            "KEINE Firmen, Orte, Produkte, Behoerden. Gib jeden Namen exakt so "
            "zurueck, wie er im Text steht. Wenn keine Namen vorkommen: leere Liste. "
            'Antworte AUSSCHLIESSLICH mit JSON: {"names": ["..."]}.\n\n'
            f"--- TEXT ---\n{chunk}"
        )
        try:
            r = requests.post(
                f"{OLLAMA_API}/api/generate",
                json={"model": model, "prompt": prompt, "format": _NAMES_SCHEMA,
                      "stream": False, "think": False, "options": {"temperature": 0}},
                timeout=180,
            )
            r.raise_for_status()
            data = json.loads(r.json()["response"])
        except (requests.RequestException, KeyError, ValueError) as e:
            raise RuntimeError(
                f"Namenserkennung via Ollama ({model}) fehlgeschlagen: {e} — "
                "abgebrochen, statt Namen im Klartext zu lassen (--no-names erzwingt "
                "es ohne Namen)") from e
        names += [str(n).strip() for n in data.get("names", []) if str(n).strip()]
        if start + _NAME_CHUNK >= len(text):
            break
    # Nur Namen, die wirklich im Text stehen — erfundene fallen hier raus.
    return [n for n in dict.fromkeys(names) if _clean_name(n) and _clean_name(n) in text]


def apply_pii(text: str, mode: str, detect_names: bool = True):
    """
    Fuehrt die gewaehlte PII-Strategie aus. Gibt (text, mapping, beschreibung) zurueck.

      off     - nichts.
      mask    - ANONYMISIEREN: generische Platzhalter ([email]). Nicht umkehrbar, und
                zwei verschiedene Personen fallen auf denselben Platzhalter zusammen.
      pseudo  - PSEUDONYMISIEREN: konsistente Tokens ([EMAIL_1]). Ueber das Mapping
                umkehrbar, Unterscheidbarkeit bleibt erhalten.
      service - headroom-Dienst (echtes NER fuer Namen). Bricht ab, wenn er fehlt.
      auto    - service, wenn erreichbar, sonst pseudo.
    """
    if mode == "off":
        return text, {}, "aus"

    if mode in ("service", "auto"):
        h = headroom_anonymize(text)
        if h is not None:
            masked, found = h
            return masked, {}, f"headroom-Dienst, {found} Treffer (inkl. Namen)"
        if mode == "service":
            raise RuntimeError(
                f"PII-Modus 'service' verlangt den headroom-Dienst, {ANON_URL} ist "
                "aber nicht erreichbar")
        mode = "pseudo"  # auto-Fallback

    names = ollama_person_names(text) if detect_names else []
    namenote = (f"{len(names)} Namen via Ollama (best-effort)" if detect_names
                else "KEINE Namenserkennung")

    if mode == "mask":
        for pat, placeholder in _PII_EARLY:
            text, _ = _sub_pii(pat, text, lambda _v, p=placeholder: p)
        for variant, _ in name_variants(names):
            text = _name_pattern(variant).sub("[person]", text)
        text, n = scrub_pii(text)
        return text, {}, f"anonymisiert, {n} strukturierte Stellen + {namenote}"

    text, mapping = pseudonymize(text, names)
    return text, mapping, f"pseudonymisiert, {len(mapping)} Tokens + {namenote}"


# Ollama unterstuetzt ein JSON-Schema als 'format'. Das blosse "json" reicht nicht:
# kleine Modelle spiegeln dann die Labels aus dem Prompt als Keys zurueck
# (beobachtet mit qwen3:4b: {"Dateiname": ..., "INHALT": ...} statt {"tags": [...]}).
# Dokumentart und Themen sind GETRENNTE Felder. Als eine gemeinsame tags-Liste
# mit einer Beispielaufzaehlung im Prompt ("z.B. lebenslauf, anschreiben, ...")
# schrieb qwen3:4b bei temperature 0 genau diese Beispiele ab, sobald der Anfang
# des Dokuments wenig inhaltliches Signal hatte — reproduzierbar, dreimal gleich.
# Ohne kopierbare Liste im Prompt gibt es nichts abzuschreiben.
_TAGS_SCHEMA = {
    "type": "object",
    "properties": {
        "dokumentart": {"type": "string"},
        "themen": {"type": "array", "items": {"type": "string"},
                   "minItems": 3, "maxItems": 5},
    },
    "required": ["dokumentart", "themen"],
}

_NAMES_SCHEMA = {
    "type": "object",
    "properties": {
        "names": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["names"],
}


def sample_text(text: str, budget: int = 6000) -> str:
    """
    Repraesentative Probe aus dem Dokument, nicht nur der Anfang.

    Bei einem 250-seitigen PDF sind die ersten 6000 Zeichen Titelseite und
    Inhaltsverzeichnis — daraus laesst sich nichts verschlagworten. Anfang, Mitte
    und Ende zu je einem Drittel treffen den tatsaechlichen Inhalt deutlich besser.
    """
    if len(text) <= budget:
        return text
    third = budget // 3
    mid = (len(text) - third) // 2
    return (text[:third]
            + "\n[...]\n" + text[mid:mid + third]
            + "\n[...]\n" + text[-third:])


def ollama_tags(text: str, filename: str = "", model: str = OLLAMA_MODEL) -> list:
    """
    Local-LLM call → list of 4-6 topical tags, one of which is the document TYPE
    (lebenslauf, stellungnahme, …). Uses filename + content as hints. Best-effort:
    returns [] if Ollama is unreachable or the reply isn't valid JSON.
    Ollama's ONLY job here is tagging — it never rewrites the saved content. Call it
    on the already-anonymized text so no masked name can leak into a tag.
    """
    prompt = (
        "Verschlagworte das Dokument unten.\n"
        "- dokumentart: die Gattung des Dokuments in EINEM kleingeschriebenen "
        "deutschen Wort, hergeleitet aus diesem konkreten Text.\n"
        "- themen: 3-5 kleingeschriebene deutsche Schlagwörter zum INHALT. "
        "Verwende Begriffe, die im Text tatsächlich vorkommen oder sich direkt "
        "daraus ergeben. Keine Personennamen, keine erfundenen Wörter, keine "
        "Wiederholung der dokumentart.\n"
        f"Der Dateiname lautet '{filename}'.\n\n"
        f"<dokument>\n{sample_text(text)}\n</dokument>"
    )
    try:
        r = requests.post(
            f"{OLLAMA_API}/api/generate",
            json={"model": model, "prompt": prompt, "format": _TAGS_SCHEMA,
                  "stream": False, "think": False, "options": {"temperature": 0}},
            timeout=180,
        )
        r.raise_for_status()
        data = json.loads(r.json()["response"])
        art = str(data.get("dokumentart", "")).strip().lower()
        themen = [str(t).strip().lower() for t in data.get("themen", []) if str(t).strip()]
        # Dokumentart zuerst, danach die Themen ohne Dubletten.
        out = ([art] if art else []) + [t for t in themen if t != art]
        return out[:6]
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"⚠️  Ollama-Tagging übersprungen ({model}): {e}", file=sys.stderr)
        return []


ANON_URL = os.environ.get("DOC2MD_ANON_URL", "http://localhost:8787")


def headroom_anonymize(text: str, url: str = ANON_URL):
    """
    Anonymize via the headroom anonymizer service (POST /api/v1/anon/test) — the
    tested engine: regex patterns (IBAN/ISIN/email/phone/IP/credit-card) plus the
    configured NER backend (spaCy/Ollama) for names, with consistent tokens.
    Returns (anonymized_text, entities_found) or None if the service is offline
    (Colima/Docker container down) so the caller can fall back.
    """
    try:
        r = requests.post(f"{url}/api/v1/anon/test", json={"text": text}, timeout=180)
        r.raise_for_status()
        d = r.json()
        return d["anonymized"], d.get("entities_found", 0)
    except (requests.RequestException, KeyError, ValueError):
        return None


def check_docling_service() -> bool:
    """Check if docling-serve is running."""
    try:
        response = requests.get(f"{DOCLING_API}/health", timeout=5)
        return response.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


DOCLING_AGENT = "com.doc2md.docling-serve"


def _docling_process_running() -> bool:
    """Laeuft ueberhaupt ein docling-serve-Prozess? (Antwortet noch nicht heisst
    nicht, dass keiner startet — die Modelle brauchen beim Start ~90 s.)"""
    try:
        r = subprocess.run(["pgrep", "-f", "docling-serve run"],
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_docling_service(wait_seconds: int = 240) -> bool:
    """
    Antwortet docling-serve nicht, den Dienst selbst hochfahren und warten.

    Ohne das scheitert die Quick Action einfach mit einer Notification, sobald der
    Server aus irgendeinem Grund weg ist — und aus dem Finder heraus ist das eine
    Sackgasse, weil es dort kein Terminal gibt, um ihn zu starten.

    Drei Stufen, von sanft nach grob:
      1. `launchctl kickstart` — der Agent ist geladen, laeuft nur gerade nicht.
      2. `launchctl bootstrap` — der Agent wurde ausgehaengt (`bootout`), die
         plist liegt aber noch da.
      3. Das Start-Skript direkt und detached — der Agent wurde nie installiert.
         Der Server stirbt dann mit der Sitzung, aber diese Konvertierung laeuft.

    Weitergeschaltet wird anhand des Prozesses, nicht der Uhr: `launchctl kickstart`
    liefert auch dann Exit 0, wenn es faktisch nichts gestartet hat. Wartete man
    darauf den vollen Timeout ab, stuende der Nutzer vier Minuten vor einer
    Stufe, die nie funktionieren wird. Erscheint binnen SPAWN_GRACE kein Prozess,
    war die Stufe wirkungslos — naechste.
    """
    if check_docling_service():
        return True

    SPAWN_GRACE = 10   # Sekunden, bis ein Prozess sichtbar sein muss
    print("⏳ docling-serve antwortet nicht — starte den Dienst...")
    domain = f"gui/{os.getuid()}"
    plist = Path.home() / "Library" / "LaunchAgents" / f"{DOCLING_AGENT}.plist"
    launcher = Path.home() / ".local" / "share" / "doc2md" / "start_docling_native.sh"

    attempts = [("kickstart", ["launchctl", "kickstart", f"{domain}/{DOCLING_AGENT}"])]
    if plist.is_file():
        attempts.append(("bootstrap", ["launchctl", "bootstrap", domain, str(plist)]))
    if launcher.is_file():
        attempts.append(("direkt", ["/bin/bash", str(launcher)]))

    deadline = time.time() + wait_seconds

    for label, cmd in attempts:
        try:
            if label == "direkt":
                # Detached: der Server soll den Converter ueberleben.
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            else:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                if r.returncode != 0:
                    print(f"   {label}: {(r.stderr or '').strip()}", file=sys.stderr)
                    continue
        except (OSError, subprocess.SubprocessError) as e:
            print(f"   {label}: {e}", file=sys.stderr)
            continue

        # Stufe 1: kam ueberhaupt ein Prozess hoch?
        spawned = False
        for _ in range(SPAWN_GRACE):
            time.sleep(1)
            if check_docling_service():
                print(f"✅ docling-serve gestartet ({label})")
                return True
            if _docling_process_running():
                spawned = True
                break
        if not spawned:
            print(f"   {label}: kein Prozess gestartet", file=sys.stderr)
            continue

        # Stufe 2: Prozess laeuft — jetzt darf er sich Zeit zum Modellladen nehmen.
        print(f"   {label}: Prozess laeuft, warte auf die Modelle...")
        while time.time() < deadline:
            time.sleep(3)
            if check_docling_service():
                print(f"✅ docling-serve gestartet ({label})")
                return True
            if not _docling_process_running():
                print(f"   {label}: Prozess wieder weg", file=sys.stderr)
                break
        else:
            print(f"   {label}: kein /health innerhalb des Zeitbudgets", file=sys.stderr)
            return False

    return False


def read_file_with_retry(input_file: Path, attempts: int = 30, delay: float = 2.0) -> bytes:
    """
    Read file contents, retrying on EDEADLK.

    Cloud-only files (OneDrive/iCloud "Files On-Demand") raise
    [Errno 11] Resource deadlock avoided when read from the Finder /
    Quick Action context while not yet downloaded. The first read
    attempt triggers materialization; retry until the download finishes.
    """
    label = f"doc2md-download-{os.getpid()}"
    triggered = False
    try:
        for attempt in range(attempts):
            try:
                return input_file.read_bytes()
            except OSError as e:
                if e.errno != errno.EDEADLK:
                    raise
                if not triggered:
                    # Reads from the Quick Action / Finder context neither succeed
                    # nor start the download. A launchd job runs outside that
                    # context, so its read materializes the file.
                    print(f"☁️  Cloud-only file, triggering download: {input_file.name}")
                    subprocess.run(
                        ["launchctl", "submit", "-l", label,
                         "-o", "/dev/null", "-e", "/dev/null",
                         "--", "/bin/cat", str(input_file)],
                        capture_output=True, timeout=30,
                    )
                    triggered = True
                time.sleep(delay)
    finally:
        if triggered:
            subprocess.run(["launchctl", "remove", label], capture_output=True)
    raise RuntimeError(
        f"Cloud file did not download in time ({int(attempts * delay)}s): {input_file.name}. "
        f"Right-click the file in Finder and choose 'Download Now', then retry."
    )


def has_text_layer(markdown: str, min_chars: int = 50) -> bool:
    """
    Grober Test, ob die Konvertierung einen brauchbaren Text-Layer gefunden hat.

    Bildplatzhalter und Markdown-Syntax zaehlen nicht als Text: ein reiner Scan
    liefert Markdown, das fast nur aus '![Image](...)' besteht.
    """
    stripped = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown)   # Bilder raus
    stripped = re.sub(r"[#*_`|<>\-\s]", "", stripped)          # Markdown-Syntax raus
    return len(stripped) >= min_chars


def convert_document(input_file: Path, force_ocr=None,
                     describe_images: bool = True) -> str:
    """
    Convert document to markdown using docling-serve API.

    force_ocr=None (Default) heisst: erst den vorhandenen Text-Layer nehmen und nur
    dann OCR nachziehen, wenn dabei praktisch nichts herauskam. Frueher stand hier
    hart force_ocr=true — das wirft bei nativen Text-PDFs einen perfekten Text-Layer
    weg und ersetzt ihn durch OCR-Fehler ("D8.07.2026" statt "08.07.2026"), siehe
    die Warnung in der CLAUDE.md des Parent-Repos. True/False erzwingt den Modus.
    """
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    print(f"🔄 Converting: {input_file.name}")

    # Read file (with cloud-download retry) and send to API with optimized parameters
    file_bytes = read_file_with_retry(input_file)

    def _convert(use_ocr: bool) -> str:
        return _post_convert(input_file, file_bytes, use_ocr, describe_images)

    if force_ocr is None:
        markdown = _convert(False)
        if has_text_layer(markdown):
            return markdown
        print("   ↪ kein brauchbarer Text-Layer — ziehe OCR (ocrmac) nach")
        return _convert(True)

    return _convert(bool(force_ocr))


def _post_convert(input_file: Path, file_bytes: bytes, use_ocr: bool,
                  describe_images: bool = True) -> str:
    """Ein einzelner /v1/convert/file-Aufruf."""
    files = {'files': (input_file.name, file_bytes)}
    data = {
        'to_format': 'md',
        'force_ocr': 'true' if use_ocr else 'false',
        'do_table_structure': 'true',
        'table_mode': 'accurate',
    }
    # Bildbeschreibung ist der teure Teil: pro Bild laeuft ein VLM. Gemessen an
    # einem 62-Seiten-PDF: 103 s ohne, 211 s mit. Der Zugewinn sind Beschreibungen
    # von Diagrammen/Abbildungen, die sonst als Platzhalter im Markdown stehen.
    if describe_images:
        data.update({
            'do_picture_description': 'true',
            'include_images': 'true',
            'picture_description_area_threshold': '0.005',
            'do_picture_classification': 'true',
            'images_scale': '2.0',
        })
    try:
        response = requests.post(
            f"{DOCLING_API}/v1/convert/file",
            files=files,
            data=data,
            timeout=CONVERT_TIMEOUT
        )

        if response.status_code != 200:
            print(f"❌ API error: {response.status_code}", file=sys.stderr)
            print(f"   {response.text}", file=sys.stderr)
            raise RuntimeError(f"Docling API error: {response.status_code}")

        # Get markdown from response
        result = response.json()

        # Extract markdown from document
        if 'document' in result and 'md_content' in result['document']:
            markdown_content = result['document']['md_content']
        elif 'document' in result and 'markdown' in result['document']:
            markdown_content = result['document']['markdown']
        elif 'markdown' in result:
            markdown_content = result['markdown']
        else:
            raise RuntimeError(f"Invalid API response - no markdown found")

        if markdown_content is None:
            errs = result.get('errors') or []
            msgs = "; ".join(e.get('error_message', str(e)) for e in errs)
            raise RuntimeError(f"Server-side conversion failed: {msgs or result.get('status', 'unknown')}")

        return markdown_content

    except requests.Timeout:
        raise RuntimeError(
            f"Conversion timeout for {input_file.name} nach {CONVERT_TIMEOUT}s "
            f"(DOC2MD_TIMEOUT erhoehen oder --no-images fuer weniger Rechenlast)")
    except requests.RequestException as e:
        raise RuntimeError(f"API request failed: {e}")


# OneDrive/SharePoint synced-folder roots on macOS
CLOUD_MARKERS = ("/Library/CloudStorage/", "/OneDrive")


def is_synced(path: Path) -> bool:
    """True if the file lives in a OneDrive/SharePoint synced folder."""
    return any(m in str(path) for m in CLOUD_MARKERS)


def get_file_info(file_path: Path) -> dict:
    """Get file metadata."""
    resolved = file_path.resolve()
    stat = file_path.stat()
    modified_time = datetime.fromtimestamp(stat.st_mtime)

    info = {
        "local_path": str(resolved),      # this Mac only — breaks on rename/move/other machines
        "source_file": file_path.name,
        "converted": datetime.now().isoformat(),
        "original_modified": modified_time.isoformat(),
    }

    # For SharePoint/OneDrive files, the stable identity is the GUID share link
    # (SharePoint → Freigeben → Link kopieren), which survives renames/moves.
    # It can't be derived locally — no resource-ID in xattrs — so it's a
    # placeholder the user pastes once. Graph API could auto-fill it later.
    if is_synced(resolved):
        info["type"] = ""                 # OKF-Konzepttyp — vom Nutzer füllen
        info["sharepoint_link"] = ""
        info["role"] = "local-primary"    # lokale .md ist (noch) die führende Kopie
        info["last_confirmed_synced"] = datetime.now().strftime("%Y-%m-%d")

    info.update({"category": "", "status": "imported", "tags": []})
    return info


# Inline-Kommentare für leere Platzhalter-Felder (Hilfe im erzeugten Frontmatter).
FIELD_HINTS = {
    "sharepoint_link": "SharePoint → Freigeben → Link kopieren",
    "type": "OKF-Konzepttyp, z.B. Stellungnahme / Schulungskonzept / Onepager",
}


def create_frontmatter(metadata: dict) -> str:
    """Create YAML frontmatter."""
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(str(v) for v in value)}]")
        elif isinstance(value, str) and value == "":
            comment = FIELD_HINTS.get(key)
            lines.append(f"{key}:" + (f"  # {comment}" if comment else ""))
        else:
            lines.append(f"{key}: {value}")
    lines.append("---\n")
    return "\n".join(lines)


def process_file(input_file: Path, pii_mode: str = "off", do_tags: bool = False,
                 write_map: bool = False, map_dir=None, detect_names: bool = True,
                 force_ocr=None, describe_images: bool = True) -> bool:
    """Process a single document file."""
    try:
        # Validate file
        if not input_file.exists():
            print(f"❌ File not found: {input_file}", file=sys.stderr)
            return False

        # Get metadata before conversion
        metadata = get_file_info(input_file)

        # Convert to markdown
        markdown_content = convert_document(input_file, force_ocr=force_ocr,
                                            describe_images=describe_images)

        # Optional local-only steps (all local, nothing leaves the machine).
        # Reihenfolge ist bewusst: PII ZUERST, dann taggen — so sieht das Tagging-Modell
        # nur den bereits maskierten Text und kein echter Name kann in einen Tag lecken.
        pii_map = {}
        if pii_mode != "off":
            markdown_content, pii_map, pii_desc = apply_pii(
                markdown_content, pii_mode, detect_names=detect_names)
            print(f"   🔒 PII: {pii_desc}")

        if do_tags:
            tags = ollama_tags(markdown_content, filename=input_file.stem)
            if tags:
                metadata["tags"] = tags
            print(f"   🏷  {len(tags)} Tags: {', '.join(tags) if tags else '—'}")

        # Create frontmatter
        frontmatter = create_frontmatter(metadata)

        # Combine frontmatter and content
        full_content = frontmatter + markdown_content

        # Save to same directory as input file
        output_file = input_file.parent / f"{input_file.stem}.md"
        output_file.write_text(full_content, encoding="utf-8")

        print(f"✅ Saved: {output_file}")

        # Das Mapping ist re-identifizierende Information — nur auf ausdruecklichen
        # Wunsch schreiben, und dann mit 0600 statt der Standard-umask.
        if pii_map and (write_map or map_dir):
            if map_dir:
                # Getrennt von der .md ablegen. Der Pfad-Hash verhindert, dass zwei
                # gleichnamige Dateien aus verschiedenen Ordnern sich ueberschreiben.
                map_dir = Path(map_dir).expanduser()
                map_dir.mkdir(parents=True, exist_ok=True)
                os.chmod(map_dir, 0o700)
                tag = hashlib.sha1(str(input_file.resolve()).encode()).hexdigest()[:8]
                map_file = map_dir / f"{input_file.stem}-{tag}.pii-map.json"
            else:
                map_file = input_file.parent / f"{input_file.stem}.pii-map.json"
            map_file.write_text(json.dumps(pii_map, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            os.chmod(map_file, 0o600)
            print(f"   🗝  Mapping: {map_file}")
            print("      ⚠️  Enthaelt die PII im Klartext — nicht mit der .md zusammen teilen.")
        elif pii_map:
            print("   ℹ️  Tokens sind ohne Mapping nicht mehr aufloesbar (--pii-map zum Sichern).")

        if metadata.get("sharepoint_link") == "":
            print("   ↪ SharePoint-Datei: 'sharepoint_link' im Frontmatter noch leer — "
                  "in SharePoint 'Freigeben → Link kopieren' und einfügen (überlebt Umbenennen).")
        return True

    except Exception as e:
        print(f"❌ Error processing {input_file.name}: {e}", file=sys.stderr)
        return False


def resolve_file_paths(args_list):
    """
    Handle file paths with spaces by reconstructing them.
    Tries to match consecutive args into valid file paths.
    """
    resolved = []
    i = 0
    while i < len(args_list):
        current_path = args_list[i]

        # Try to combine with following args if current doesn't exist
        while i + 1 < len(args_list) and not Path(current_path).exists():
            current_path = f"{current_path} {args_list[i + 1]}"
            i += 1
            if Path(current_path).exists():
                break

        resolved.append(current_path)
        i += 1

    return resolved


# Gemessen auf diesem Mac (M-Serie, MPS): 62 Seiten in 211 s mit bzw. 103 s ohne
# Bildbeschreibung. Nur fuer die Erwartungshaltung gedacht, nicht fuer Planung.
SECONDS_PER_PAGE = {True: 3.4, False: 1.7}
# Fixkosten pro Auftrag (Upload, Pipeline-Aufbau, Antwort) — ohne die ist die
# Schaetzung bei kurzen Dokumenten um ein Vielfaches zu optimistisch.
BASE_SECONDS = 8


def pdf_page_count(path: Path):
    """
    Seitenzahl eines PDFs via Spotlight, oder None.

    Bewusst nur `mdls`: das liest die Metadaten, ohne die Datei anzufassen — bei
    einer Cloud-only-OneDrive-Datei wuerde ein echter Read hier denselben EDEADLK
    ausloesen, den read_file_with_retry() umgeht. Nicht indizierte Dateien
    (z. B. unter /tmp) liefern (null); dann gibt es eben keine Schaetzung.
    """
    if path.suffix.lower() != ".pdf":
        return None
    try:
        r = subprocess.run(
            ["mdls", "-name", "kMDItemNumberOfPages", "-raw", str(path)],
            capture_output=True, text=True, timeout=10)
        n = int(r.stdout.strip())
        return n if n > 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def duration_hint(files, describe_images: bool) -> str:
    """'113 Seiten, ca. 6 min' — oder '' wenn die Seitenzahl unbekannt ist."""
    pages = [pdf_page_count(f) for f in files]
    if not any(pages):
        return ""
    total = sum(n for n in pages if n)
    secs = BASE_SECONDS + total * SECONDS_PER_PAGE[describe_images]
    if secs < 90:
        eta = f"ca. {max(10, round(secs / 10) * 10)} s"
    else:
        eta = f"ca. {round(secs / 60)} min"
    return f"{total} {'Seite' if total == 1 else 'Seiten'}, {eta}"


LOCK_DIR = Path.home() / "Library" / "Caches" / "doc2md" / "locks"


@contextlib.contextmanager
def file_lock(target: Path):
    """
    Exklusiver Lock pro Eingabedatei. Liefert True, wenn er geholt wurde.

    Grosse PDFs laufen Minuten und melden sich erst am Ende — mehrfaches Druecken
    des Shortcuts ist die natuerliche Reaktion darauf. Drei parallele Jobs auf
    zwei docling-Workern liefen genau so in den Timeout, alle drei. flock loest
    sich mit dem Prozess: keine Stale Locks, kein Aufraeumen noetig.
    """
    fh = None
    try:
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(str(target.resolve()).encode()).hexdigest()[:16]
        fh = open(LOCK_DIR / f"{key}.lock", "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Schon gesperrt — oder der Lock liess sich nicht anlegen. Im zweiten Fall
        # lieber konvertieren als blockieren.
        if fh is not None:
            fh.close()
            yield False
            return
        yield True
        return
    try:
        yield True
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def notify(message: str):
    """Show a macOS notification (best effort)."""
    safe = message.replace('\\', '').replace('"', "'")
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe}" with title "Convert to Markdown"'],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Convert documents to Markdown using docling-serve API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python doc_to_markdown.py document.pdf
  python doc_to_markdown.py file1.pdf file2.docx file3.pptx
  python doc_to_markdown.py "My Document.pdf"

  # nur verschlagworten, Inhalt bleibt unveraendert:
  python doc_to_markdown.py --tags bericht.pdf

  # pseudonymisieren (umkehrbare Tokens) + Mapping sichern + verschlagworten:
  python doc_to_markdown.py --pii pseudo --pii-map --tags bericht.pdf

  # anonymisieren (generische Platzhalter, nicht umkehrbar):
  python doc_to_markdown.py --pii mask bericht.pdf

Note: docling-serve must be running on localhost:5001
      --tags und die Namenserkennung brauchen zusaetzlich Ollama (localhost:11434)
        """
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Document file(s) to convert (PDF, DOCX, PPTX, HTML, etc.)"
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Show macOS notification with the result (used by the Quick Action)"
    )
    ocr = parser.add_mutually_exclusive_group()
    ocr.add_argument(
        "--force-ocr",
        action="store_true",
        help="OCR erzwingen, auch wenn ein Text-Layer da ist. Nur fuer PDFs mit "
             "kaputtem Text-Layer sinnvoll — sonst verschlechtert es das Ergebnis."
    )
    ocr.add_argument(
        "--no-ocr",
        action="store_true",
        help="Nie OCR. Bildbasierte PDFs liefern dann (fast) leeres Markdown."
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Bildbeschreibung weglassen. Etwa doppelt so schnell (gemessen an einem "
             "62-Seiten-PDF: 103 s statt 211 s), dafuer stehen Diagramme und "
             "Abbildungen nur als Platzhalter im Markdown."
    )
    parser.add_argument(
        "--tags",
        action="store_true",
        help="Verschlagwortung durch ein lokales Ollama-Modell (DOC2MD_OLLAMA_MODEL, "
             "Default qwen3:4b). Schreibt nur 'tags' ins Frontmatter — der Inhalt "
             "bleibt unveraendert."
    )
    parser.add_argument(
        "--pii",
        choices=_PII_MODES,
        default="off",
        help="Wie mit personenbezogenen Daten im konvertierten Text verfahren wird. "
             "off (Default): unveraendert. "
             "mask: ANONYMISIEREN — generische Platzhalter ([email]), nicht umkehrbar, "
             "verschiedene Personen werden ununterscheidbar. "
             "pseudo: PSEUDONYMISIEREN — konsistente Tokens ([EMAIL_1]), umkehrbar "
             "ueber --pii-map. "
             "service: headroom-Dienst (DOC2MD_ANON_URL, Default localhost:8787) mit "
             "echtem NER; bricht ab, wenn er nicht laeuft. "
             "auto: service wenn erreichbar, sonst pseudo."
    )
    parser.add_argument(
        "--pii-map",
        action="store_true",
        help="Bei --pii pseudo zusaetzlich '<name>.pii-map.json' mit der "
             "Token→Klartext-Zuordnung ablegen (Rechte 0600). Ohne diese Datei sind "
             "die Tokens nicht mehr aufloesbar."
    )
    parser.add_argument(
        "--pii-map-dir",
        metavar="DIR",
        help="Wie --pii-map, legt die Zuordnung aber in DIR ab (Rechte 0700) statt "
             "neben die .md — so landen .md und Schluessel nicht versehentlich "
             "zusammen in einem geteilten Ordner."
    )
    parser.add_argument(
        "--no-names",
        action="store_true",
        help="Namenserkennung via Ollama in den lokalen PII-Modi abschalten. Dann "
             "werden ausschliesslich strukturierte PII erkannt (E-Mail, IBAN, Telefon, "
             "Adresse) — schneller, aber Namen bleiben im Klartext stehen."
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Kurzform fuer '--pii auto --tags' (Rueckwaertskompatibilitaet)."
    )

    args = parser.parse_args()

    force_ocr = True if args.force_ocr else (False if args.no_ocr else None)
    pii_mode = args.pii
    do_tags = args.tags
    if args.enrich:
        do_tags = True
        if pii_mode == "off":
            pii_mode = "auto"

    # Debug log: record invocations to diagnose Quick Action issues
    try:
        with open(os.path.expanduser("~/Library/Logs/doc2md.log"), "a") as log:
            log.write(f"{datetime.now().isoformat()} argv={sys.argv[1:]}\n")
    except OSError:
        pass

    # Resolve file paths with spaces
    file_args = resolve_file_paths(args.files)

    # Check if docling-serve is running — und notfalls selbst hochfahren.
    print("🔍 Checking docling-serve on localhost:5001...")
    if not check_docling_service():
        if args.notify:
            notify("⏳ Starte docling-serve — die Konvertierung läuft gleich weiter")
        if not ensure_docling_service():
            print("❌ docling-serve is not running and could not be started!",
                  file=sys.stderr)
            print("   Einmalig einrichten: ./install-docling-agent.sh im Parent-Repo",
                  file=sys.stderr)
            print("   Oder manuell: ./start_docling_native.sh", file=sys.stderr)
            if args.notify:
                notify("❌ docling-serve nicht startbar — ./install-docling-agent.sh ausführen")
            sys.exit(1)
    else:
        print("✅ docling-serve is ready")

    # Process files
    input_files = [Path(f) for f in file_args]
    results = []

    print(f"\n📄 Processing {len(input_files)} file(s)...\n")

    # Sofort Rueckmeldung geben: eine grosse PDF laeuft Minuten, und ohne dieses
    # Signal wirkt der Shortcut wie kaputt (und wird nochmal gedrueckt).
    hint = duration_hint(input_files, not args.no_images)
    if hint:
        print(f"   {hint} — Rückmeldung kommt erst am Ende")
    if args.notify:
        names = ", ".join(f.name for f in input_files)
        notify(f"⏳ Konvertiere {names}" + (f" — {hint}" if hint else "")[:200])

    skipped = []
    for input_file in input_files:
        with file_lock(input_file) as acquired:
            if not acquired:
                print(f"⏭  {input_file.name}: läuft bereits — übersprungen")
                skipped.append(input_file.name)
                continue
            success = process_file(
                input_file,
                pii_mode=pii_mode,
                do_tags=do_tags,
                write_map=args.pii_map,
                map_dir=args.pii_map_dir,
                detect_names=not args.no_names,
                force_ocr=force_ocr,
                describe_images=not args.no_images,
            )
        results.append((input_file.name, success))

    if skipped:
        print(f"⏭  Bereits laufend, übersprungen: {', '.join(skipped)}")
        if args.notify and not results:
            notify(f"⏭  Läuft bereits: {', '.join(skipped)}"[:200])
            return

    # Summary
    print(f"\n{'='*50}")
    successful = sum(1 for _, success in results if success)
    print(f"✨ Conversion complete: {successful}/{len(results)} successful")

    if args.notify:
        if successful == len(results):
            names = ", ".join(name for name, _ in results)
            notify(f"✅ Konvertiert: {names}"[:200])
        else:
            failed = ", ".join(name for name, ok in results if not ok)
            notify(f"❌ Fehlgeschlagen: {failed} — Details: ~/Library/Logs/doc2md.log"[:200])

    if successful < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
