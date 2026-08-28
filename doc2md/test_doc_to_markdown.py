"""Self-check for frontmatter, sync detection, and offline anonymization.
Run: python3 test_doc_to_markdown.py  (no network — Ollama/headroom not called)"""
from pathlib import Path
from doc_to_markdown import (
    is_synced, create_frontmatter, get_file_info, scrub_pii,
)


def test():
    # --- Cloud detection ---
    assert is_synced(Path("/Users/x/Library/CloudStorage/OneDrive-Contoso/a.pdf"))
    assert is_synced(Path("/Users/x/OneDrive - Contoso/a.pdf"))
    assert not is_synced(Path("/Users/x/Repos_lokal/a.pdf"))

    # --- Synced file gets stable-identity + type fields; local file does not ---
    fm_local = create_frontmatter(get_file_info(Path(__file__)))  # this file is NOT synced
    assert "local_path:" in fm_local and "sharepoint_link" not in fm_local, fm_local

    synced = {"local_path": "/x", "type": "", "sharepoint_link": "", "role": "local-primary"}
    out = create_frontmatter(synced)
    assert "sharepoint_link:  # SharePoint" in out, out       # empty link carries paste hint
    assert "type:  # OKF-Konzepttyp" in out, out              # empty type carries hint
    assert "role: local-primary" in out

    # --- Non-empty tags actually render (regression: used to always print []) ---
    assert "tags: [ki, schulung]" in create_frontmatter({"tags": ["ki", "schulung"]})
    assert "tags: []" in create_frontmatter({"tags": []})

    # --- Deterministic PII floor (regex-only fallback; names need headroom) ---
    s, n = scrub_pii("Mail max.muster@example.com IBAN DE44 5001 0517 5407 3249 31 Tel +49 30 1234567")
    assert "[email]" in s and "[iban]" in s and "[telefon]" in s, s
    assert n == 3, n
    assert "example.com" not in s and "5407" not in s

    # Phone directly before a sentence period must still be masked (edge case).
    s2, n2 = scrub_pii("Ruf +49 30 2020123. Danke.")
    assert "[telefon]. Danke." in s2 and n2 == 1, s2

    # German address floor (fallback when headroom is offline).
    s3, _ = scrub_pii("Bouchestraße 78, 12435 Berlin")
    assert "[adresse]" in s3 and "[ort]" in s3 and "Bouche" not in s3 and "Berlin" not in s3, s3
    # A money amount must NOT be mistaken for a postal code / phone.
    s4, n4 = scrub_pii("Kosten: 12.500,00 EUR.")
    assert s4 == "Kosten: 12.500,00 EUR." and n4 == 0, (s4, n4)

    print("ok")


if __name__ == "__main__":
    test()
