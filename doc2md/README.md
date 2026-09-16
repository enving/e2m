# doc2md — keyboard-shortcut document converter

A thin macOS front-end for the Everything2Markdown `docling-serve` API: select
a file, hit a shortcut, get a `.md` with YAML frontmatter in the same folder.
Optionally anonymizes PII and tags the result — fully local, nothing leaves
the machine.

## Features

- **Multi-format** — PDF, DOCX, PPTX, HTML, images, and more
- **Finder Quick Action** — right-click → "Convert to Markdown"
- **Keyboard shortcuts** — `Cmd+Shift+M` convert, `Cmd+Ctrl+M` convert + tag,
  `Cmd+Ctrl+Opt+M` convert + tag + pseudonymize (mapping goes to
  `~/Documents/doc2md-mappings/`, not next to the `.md`)
- **Right-click** → Quick Actions → the same three entries
- **Terminal command** — `doc2md file.pdf`
- **VSCode task + keybinding** — `Cmd+Shift+M`
- **Metadata frontmatter** — YAML with source path, timestamps, OKF `type` field
- **Optional `--tags`** — topic keywords from a local Ollama model
- **Optional `--pii`** — anonymize *or* pseudonymize, fully local

## Requirements

- `docling-serve` running. Set it up to start at login with the parent repo's
  `../install-docling-agent.sh` — otherwise the shortcuts fail as soon as the
  terminal that started the server is gone.
- Python 3 with `requests` installed
- Optional: [Ollama](https://ollama.com) for `--tags` and local name detection
  (`brew install ollama && brew services start ollama && ollama pull qwen3:4b`)
- Optional: an anonymizer service for name-level `--enrich` masking — see
  below, not required (regex fallback covers email/IBAN/phone/address)

## Install

The parent repo's installer does everything, including docling-serve:

```bash
cd ..            # repo root
./install.sh --with-ollama
```

If docling-serve is already running and you only want (or want to refresh)
doc2md itself:

```bash
/usr/bin/python3 -m pip install --user requests
./install-quick-actions.sh
```

That copies the converter to `~/.local/bin/`, creates the `doc2md` command
there, builds the three `.workflow` bundles and binds the shortcuts — it
replaces the manual Automator + System Settings walkthrough documented
below. Keep reading if you'd rather do it by hand or want to change what
the actions run.

Try it once from the terminal to confirm it works before setting up the
Quick Action or VSCode keybinding below:

```bash
doc2md ~/Downloads/some-document.pdf
```

The repo copies are the source of truth; the `~/.local/bin/` copies are what
actually run (Quick Actions and VSCode tasks call fixed paths there). If you
edit `doc_to_markdown.py` later, re-run `./install-quick-actions.sh` to redeploy it.

### Terminal

```bash
doc2md ~/Downloads/document.pdf
doc2md file1.pdf file2.docx file3.pptx
doc2md --tags report.pdf                      # + topic tags, content untouched
doc2md --pii pseudo --pii-map report.pdf      # + reversible pseudonymization
doc2md --pii mask report.pdf                  # + irreversible anonymization
doc2md --force-ocr scan.pdf                   # only for a broken text layer
doc2md --no-images big.pdf                    # ~2x faster, skips image descriptions
```

### Finder Quick Action + global shortcut (Automator)

1. Automator → File → New → **Quick Action**
2. Add a **"Run Shell Script"** action, "Pass input" = **as arguments**
3. Script:
   ```bash
   nohup python3 "$HOME/.local/bin/doc_to_markdown.py" --notify "$@" \
     >> "$HOME/Library/Logs/doc2md.log" 2>&1 &
   ```
   Must run detached (`nohup ... &`): Automator holds a file-coordination
   claim on the selected files while the action runs, so a synchronous read
   of a cloud-only OneDrive file fails with `[Errno 11] Resource deadlock
   avoided` and the download never starts. Result comes back as a macOS
   notification (`--notify`).
4. Save as **"Convert to Markdown"**, configured for Finder / files & folders
5. System Settings → Keyboard → Keyboard Shortcuts → App Shortcuts → **+**
   → All Applications → Menu Title "Convert to Markdown" → assign a shortcut

For a picker instead of a Finder selection, point the same Quick Action (or
a separate one) at `doc_converter.sh`, which opens a native file dialog via
`doc_to_markdown_dialog.py` — no macOS Accessibility permission required,
which matters on locked-down/enterprise Macs.

### VSCode

```bash
bash setup-vscode-keybinding.sh   # wires Cmd+Shift+M to the task in .vscode/tasks.json
```

Reload VSCode, open a file, press `Cmd+Shift+M`.

## Output format

```yaml
---
local_path: /Users/you/Downloads/report.pdf
source_file: report.pdf
converted: 2026-07-10T14:30:45.123456
original_modified: 2026-07-09T10:15:30
category:
status: imported
tags: []
---

# Document Title

Document content converted to Markdown...
```

For files inside a OneDrive/SharePoint-synced folder
(`~/Library/CloudStorage/...` or `~/OneDrive...`), a few extra fields are
added:

```yaml
type:                    # OKF concept type — fill in, e.g. Report, Onepager
sharepoint_link:         # empty — paste from SharePoint "Share → Copy link"
role: local-primary      # this local file is currently the primary copy
last_confirmed_synced: 2026-07-30
```

**Why two references?** `local_path` only works on this machine and breaks
on rename/move. `sharepoint_link` is SharePoint's GUID-based share link (not
the file path!) — it survives renames and most moves within the same
library, and is what you'd use for later automation (Graph API). It can't be
derived locally (OneDrive doesn't expose a resource ID in macOS extended
attributes), so it's a placeholder you paste once.

These frontmatter keys (`type`, `sharepoint_link`, `local_path`, `role`,
`last_confirmed_synced`, `tags`) intentionally match the Open Knowledge
Format (OKF) sync-key convention, so a converted `.md` and an OKF concept
stay interchangeable. OKF only hard-requires `type`; the extra keys are
ignored by generic OKF tooling.

### The sidecar pattern

A document often lives in two places: a `.docx` on SharePoint (the
collaboration surface) and a local `.md` (your working copy). `role`
disambiguates which one is the actual content:

| `role` | Content lives in | The `.md` contains |
|---|---|---|
| `local-primary` | the `.md` | full content — the `.md` is the only copy |
| `sharepoint-primary` | the `.docx` on SharePoint | metadata + working notes only |

The switch happens the first time you export to Word and upload — from then
on, stop editing body text in the `.md`; the `.docx` is truth and the `.md`
just tracks it.

`.claude/hooks/sharepoint_notice.py` (wired via `.claude/settings.json`)
reminds Claude Code of this before it edits a file with a `sharepoint_link`:
a warning if `role: sharepoint-primary` (don't trust this body as current
content), or a gentle heads-up if there's a linked counterpart otherwise.
It never blocks, and it's silent for files without this frontmatter.
Project hooks need a one-time approval on the next Claude Code start.

## Tagging and PII handling

Both are optional, both run **entirely locally**, and they are separate
switches — you can tag without touching the text, or mask without tagging.
When you use both, PII runs **first**, so the tagging model only ever sees
the already-masked text and no real name can leak into a tag.

### `--tags` — topic keywords

```bash
doc2md --tags report.pdf
```

A local Ollama model (`qwen3:4b` by default, override with
`DOC2MD_OLLAMA_MODEL`) reads the document and returns 4–6 German topic tags,
one of which is the document type. It writes only the `tags:` frontmatter
key — **the content is not modified**.

The request pins a JSON schema (`dokumentart` + `themen`) rather than asking
for "JSON" in the prompt, and the prompt contains no list of example document
types. Both matter with a 4B model: without the schema you get a well-formed
object with the wrong keys and zero tags, and with an example list in the
prompt the model copies that list verbatim whenever the document's opening
pages are thin.

Long documents are sampled from beginning, middle and end — the first 6000
characters of a 113-page PDF are just the cover and the table of contents.

### `--pii` — anonymize or pseudonymize

These are genuinely different things and the flag makes you pick:

| Mode | What it does | Reversible? | Are two people distinguishable? | Detects names? |
|---|---|---|---|---|
| `off` *(default)* | nothing | — | — | — |
| `mask` | **anonymize** — generic placeholders: `[email]`, `[telefon]` | no | **no** — both collapse to `[email]` | via Ollama, best-effort |
| `pseudo` | **pseudonymize** — consistent tokens: `[EMAIL_1]`, `[PERSON_2]` | yes, via `--pii-map` | yes | via Ollama, best-effort |
| `service` | delegate to a headroom anonymizer with a real NER model | per that service | per that service | yes, properly |
| `auto` | `service` if reachable, otherwise `pseudo` | | | |

`pseudo` is pseudonymization in the sense of Art. 4(5) GDPR: the same input
value always maps to the same token, so the document still tells you that
two different people were involved and who wrote to whom, and the mapping
restores the original exactly. `mask` throws that away permanently.

```bash
doc2md --pii pseudo --pii-map --tags bericht.pdf
```

`--pii-map` writes `bericht.pii-map.json` next to the `.md` with the
token → cleartext mapping, mode `0600`. **That file is re-identifying data**
— it is the reason the pseudonymized `.md` is not anonymous. Store it apart
from the `.md` and never share the two together. Without it, the tokens are
not resolvable.

`--pii-map-dir DIR` does the same but writes the mapping into `DIR` (mode
`0700`) as `<name>-<pathhash>.pii-map.json` — that is what the pseudonymize
Quick Action uses, so the `.md` and its key never end up in the same folder.

What `pseudo` replaces:

| Token | Source |
|---|---|
| `[PERSON_n]` | full name found by Ollama, titles stripped (`Dr. [PERSON_2]`) |
| `[PERSON_n_NACHNAME]`, `[PERSON_n_VORNAME]` | the same person's name part on its own (`Frau [PERSON_2_NACHNAME]`) |
| `[NACHNAME_n]` | a surname shared by several people — not attributed to either |
| `[EMAIL_n]`, `[IBAN_n]`, `[TELEFON_n]` | regex; phone must start with `+` or `0` |
| `[ADRESSE_n]`, `[ORT_n]` | street + number, postal code + city |
| `[GEBURTSDATUM_n]` | a date after `geb.`/`geboren`/`Geburtsdatum` — plain dates stay |
| `[KENNUNG_n]` | number after Personal-/Kunden-/Versicherten-/Steuer-/Ausweis-Nr. etc. |

If Ollama is unreachable, `mask`/`pseudo` **abort** instead of writing a
file with every name in cleartext.

### Honest limits

- **Name detection in the local modes is best-effort.** `mask` and `pseudo`
  use the LLM as a stand-in for NER, chunk by chunk over the whole document
  (one call per ~4000 characters — long documents take noticeably longer). It
  can miss names; invented ones are dropped because only names that literally
  occur in the text are used. Only `service` uses a real NER
  model. Add `--no-names` to skip it entirely and mask only structured PII
  (email, IBAN, phone, street address, postal code + city) — that part is
  deterministic regex and reliable.
- **Manual review stays necessary in every mode.**
- **The filename is never masked.** `source_file` and `local_path` keep the
  original name — rename the source file first if it contains a name.
- The `service` mode needs an anonymizer on `http://localhost:8787`
  (`DOC2MD_ANON_URL`), not included in this repo; self-host your own, e.g.
  [headroom](https://github.com/headroomlabs-ai/headroom). It must answer
  `POST /api/v1/anon/test` with `{"text": "..."}` →
  `{"anonymized": "...", "entities_found": N}`. If it is not reachable,
  `--pii service` fails loudly rather than quietly downgrading.

## How long it takes

Conversion is not instant, and the shortcut only notifies you when it
*starts* and when it *finishes* — there is no progress bar in between.
Measured on a 62-page, 5.3 MB PDF:

| Pages | default (with image descriptions) | `--no-images` |
|---|---|---|
| 62 | 211 s | 103 s |
| 113 | 365 s | — |

Roughly 3.4 s per page with image descriptions, 1.7 s without. The shortcut
tells you the estimate up front: the start notification reads
`⏳ Konvertiere report.pdf — 113 Seiten, ca. 7 min`. Page count comes from
Spotlight (`mdls`), so a file Spotlight hasn't indexed gets no estimate.

Image description runs a local VLM once per picture — that is the expensive
part, and it is what turns a chart into a sentence instead of a placeholder.
Drop it with `--no-images` when you just want the text.

The request timeout is **30 minutes** (`DOC2MD_TIMEOUT`, seconds). It used to
be 300 s, which a document like the one above blows through as soon as
anything else is competing for the server's workers.

Pressing the shortcut again while a file is still converting does **not**
start a second run — the second one sees the lock and exits. Without that,
three impatient keypresses put three jobs on two workers and all three ran
into the timeout.

## OCR

OCR is **not** forced by default. The converter uses the PDF's existing text
layer and only re-runs with OCR (ocrmac / Apple Vision) when that produced
essentially nothing — i.e. for scans. Forcing OCR on a native text PDF makes
the result *worse*, not better: you trade a perfect text layer for OCR
errors like `D8.07.2026` instead of `08.07.2026`.

```bash
doc2md --force-ocr scan.pdf   # only when the embedded text layer is corrupt
doc2md --no-ocr native.pdf    # never OCR; image-based PDFs come out empty
```

## Testing

```bash
python3 test_doc_to_markdown.py   # frontmatter/sync-detection/regex-PII — no network
python3 test_pseudonymize.py      # PII modes: consistency + reversibility — no network
python3 test_anon_integrity.py    # headroom round-trip — skips if unreachable
```

## Troubleshooting

**docling-serve not reachable** — the converter tries to start it itself
(`launchctl kickstart` → `bootstrap` → direct launch) and waits for the models
to load, so a one-off "server is down" usually resolves on its own within a
minute. If it reports it could not be started, the LaunchAgent is missing:
run the parent repo's `./install-docling-agent.sh` once. Check with
`curl http://localhost:5001/health` and
`tail ~/Library/Logs/docling-serve.log`.

**Quick Action not in Finder menu** — System Settings → Keyboard → App
Shortcuts, check it's listed and configured for "Files and Folders".

**Garbled text from a PDF that clearly has selectable text** — its embedded
text layer is corrupt. Re-run with `--force-ocr` to bypass it. This is a
source-file problem, not a converter bug.

**Empty or near-empty output** — the PDF is image-based and the OCR fallback
didn't trigger or found nothing. Force it with `--force-ocr` and check that
docling-serve started with ocrmac (parent repo's `start_docling_native.sh`).

**`--tags` returns nothing** — check Ollama: `curl localhost:11434/api/tags`.
The model in `DOC2MD_OLLAMA_MODEL` (default `qwen3:4b`) must be pulled.

**Shortcut does nothing** — the keystroke only reaches apps started *after*
it was registered; restart the app (`killall Finder` for the Finder). Verify
with `defaults read NSGlobalDomain NSUserKeyEquivalents`.
