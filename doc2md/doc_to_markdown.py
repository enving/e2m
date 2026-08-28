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
import argparse
import warnings
import subprocess

# Suppress urllib3 NotOpenSSLWarning (system Python 3.9 links LibreSSL);
# stderr output makes the Automator Quick Action show an error dialog
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import requests
from pathlib import Path
from datetime import datetime


DOCLING_API = "http://localhost:5001"
OLLAMA_API = "http://localhost:11434"
OLLAMA_MODEL = os.environ.get("DOC2MD_OLLAMA_MODEL", "gemma4:latest")

# Deterministic PII patterns — the RELIABLE anonymization floor (whole document).
# Names/addresses are not here: regex can't catch them; the LLM handles those
# best-effort. So this floor is "sicher" only for these structured identifiers.
_PII = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Za-z0-9]){11,30}\b"), "[iban]"),
    # Deutsche Straße + Hausnummer: "Bouchestraße 78", "Musterweg 3a".
    (re.compile(r"\b[A-ZÄÖÜ][\wäöüß.-]*(?:straße|strasse|str\.|weg|platz|allee|gasse|ring|damm|ufer)\s+\d+\s*[a-z]?\b"), "[adresse]"),
    # PLZ + Ort: "12435 Berlin".
    (re.compile(r"\b\d{5}\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.-]+(?:\s[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.-]+)?"), "[ort]"),
    (re.compile(r"(?<!\d)\+?\d[\d /()-]{6,}\d(?!\d)"), "[telefon]"),
]


def scrub_pii(text: str):
    """Mask structured PII deterministically. Returns (text, count)."""
    n = 0
    for pat, repl in _PII:
        text, k = pat.subn(repl, text)
        n += k
    return text, n


def ollama_tags(text: str, filename: str = "", model: str = OLLAMA_MODEL) -> list:
    """
    Local-LLM call → list of 4-6 topical tags, one of which is the document TYPE
    (lebenslauf, stellungnahme, …). Uses filename + content as hints. Best-effort:
    returns [] if Ollama is unreachable or the reply isn't valid JSON.
    Ollama's ONLY job here is tagging — it never rewrites the saved content. Call it
    on the already-anonymized text so no masked name can leak into a tag.
    """
    prompt = (
        "Vergib 4-6 kurze Themen-Schlagwörter (kleingeschrieben, deutsch) für das "
        "Dokument. GENAU EINES davon MUSS die Dokumentart sein, z.B. lebenslauf, "
        "anschreiben, stellungnahme, konzept, protokoll, rechnung, angebot, "
        "präsentation, vertrag, bericht. Nutze Dateiname UND Inhalt als Hinweise "
        "(engl. 'resume/cv' -> lebenslauf). KEINE Personennamen als Tag. "
        "Nur korrekte, existierende deutsche Wörter, keine erfundenen. "
        'Antworte AUSSCHLIESSLICH mit JSON: {"tags": ["...", ...]}.\n\n'
        f"Dateiname: {filename}\n--- INHALT ---\n{text[:6000]}"
    )
    try:
        r = requests.post(
            f"{OLLAMA_API}/api/generate",
            json={"model": model, "prompt": prompt, "format": "json",
                  "stream": False, "options": {"temperature": 0}},
            timeout=120,
        )
        r.raise_for_status()
        data = json.loads(r.json()["response"])
        return [str(t).strip().lower() for t in data.get("tags", []) if str(t).strip()][:6]
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


def convert_document(input_file: Path) -> str:
    """Convert document to markdown using docling-serve API."""
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    print(f"🔄 Converting: {input_file.name}")

    # Read file (with cloud-download retry) and send to API with optimized parameters
    file_bytes = read_file_with_retry(input_file)
    files = {'files': (input_file.name, file_bytes)}
    data = {
        'to_format': 'md',
        'force_ocr': 'true',
        'do_picture_description': 'true',
        'include_images': 'true',
        'picture_description_area_threshold': '0.005',
        'do_picture_classification': 'true',
        'do_table_structure': 'true',
        'table_mode': 'accurate',
        'images_scale': '2.0'
    }
    try:
        response = requests.post(
            f"{DOCLING_API}/v1/convert/file",
            files=files,
            data=data,
            timeout=300
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
        raise RuntimeError(f"Conversion timeout for {input_file.name}")
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


def process_file(input_file: Path, enrich: bool = False) -> bool:
    """Process a single document file."""
    try:
        # Validate file
        if not input_file.exists():
            print(f"❌ File not found: {input_file}", file=sys.stderr)
            return False

        # Get metadata before conversion
        metadata = get_file_info(input_file)

        # Convert to markdown
        markdown_content = convert_document(input_file)

        # Optional local-only enrichment (all local, nothing leaves the machine):
        #   1. Anonymize FIRST (headroom regex+NER incl. names; offline → regex-only
        #      floor, structured PII, NO names). Both just mask exact spans — no rewrite.
        #   2. Then tag the ALREADY-ANONYMIZED text, so no masked name leaks into a tag.
        #      Ollama only suggests tags; it never rewrites content.
        if enrich:
            h = headroom_anonymize(markdown_content)
            if h is not None:
                markdown_content, masked = h
                anon_src = "headroom"
            else:
                markdown_content, masked = scrub_pii(markdown_content)
                anon_src = "Regex-Fallback (headroom offline — nur strukturierte PII, KEINE Namen)"

            tags = ollama_tags(markdown_content, filename=input_file.stem)
            if tags:
                metadata["tags"] = tags
            print(f"   🔒 {masked} PII-Stelle(n) maskiert via {anon_src} · 🏷  {len(tags)} Tags")

        # Create frontmatter
        frontmatter = create_frontmatter(metadata)

        # Combine frontmatter and content
        full_content = frontmatter + markdown_content

        # Save to same directory as input file
        output_file = input_file.parent / f"{input_file.stem}.md"
        output_file.write_text(full_content, encoding="utf-8")

        print(f"✅ Saved: {output_file}")
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

Note: docling-serve must be running on localhost:5001
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
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Lokale Anreicherung: Tags via Ollama (DOC2MD_OLLAMA_MODEL, Default "
             "gemma4:latest) + PII-Anonymisierung. Anonymisierung nutzt bevorzugt "
             "den headroom-Dienst (DOC2MD_ANON_URL, Default http://localhost:8787); "
             "ist er offline, greift ein Regex+Ollama-Fallback (Namen best-effort). "
             "Alles lokal — kein Ersatz für eine manuelle Prüfung."
    )

    args = parser.parse_args()

    # Debug log: record invocations to diagnose Quick Action issues
    try:
        with open(os.path.expanduser("~/Library/Logs/doc2md.log"), "a") as log:
            log.write(f"{datetime.now().isoformat()} argv={sys.argv[1:]}\n")
    except OSError:
        pass

    # Resolve file paths with spaces
    file_args = resolve_file_paths(args.files)

    # Check if docling-serve is running
    print("🔍 Checking docling-serve on localhost:5001...")
    if not check_docling_service():
        print("❌ docling-serve is not running!", file=sys.stderr)
        print("   Start it with: ~/Repos_lokal/Everything2Markdown/start_docling_native.sh", file=sys.stderr)
        if args.notify:
            notify("❌ docling-serve läuft nicht — Server starten und erneut versuchen")
        sys.exit(1)
    print("✅ docling-serve is ready")

    # Process files
    input_files = [Path(f) for f in file_args]
    results = []

    print(f"\n📄 Processing {len(input_files)} file(s)...\n")

    for input_file in input_files:
        success = process_file(input_file, enrich=args.enrich)
        results.append((input_file.name, success))

    # Summary
    print(f"\n{'='*50}")
    successful = sum(1 for _, success in results if success)
    print(f"✨ Conversion complete: {successful}/{len(input_files)} successful")

    if args.notify:
        if successful == len(input_files):
            names = ", ".join(name for name, _ in results)
            notify(f"✅ Konvertiert: {names}"[:200])
        else:
            failed = ", ".join(name for name, ok in results if not ok)
            notify(f"❌ Fehlgeschlagen: {failed} — Details: ~/Library/Logs/doc2md.log"[:200])

    if successful < len(input_files):
        sys.exit(1)


if __name__ == "__main__":
    main()
