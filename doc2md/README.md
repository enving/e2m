# doc2md — keyboard-shortcut document converter

A thin macOS front-end for the Everything2Markdown `docling-serve` API: select
a file, hit a shortcut, get a `.md` with YAML frontmatter in the same folder.
Optionally anonymizes PII and tags the result — fully local, nothing leaves
the machine.

## Features

- **Multi-format** — PDF, DOCX, PPTX, HTML, images, and more
- **Finder Quick Action** — right-click → "Convert to Markdown"
- **Global keyboard shortcut** — via the Quick Action
- **Terminal command** — `doc2md file.pdf`
- **VSCode task + keybinding** — `Cmd+Shift+M`
- **Metadata frontmatter** — YAML with source path, timestamps, OKF `type` field
- **Optional `--enrich`** — local PII anonymization + Ollama topic tags

## Requirements

- `docling-serve` running (see the parent repo's `../start_docling_native.sh`
  or `../compose.yaml`)
- Python 3 with `requests` installed
- Optional: [Ollama](https://ollama.com) for `--enrich` tagging
- Optional: an anonymizer service for name-level `--enrich` masking — see
  below, not required (regex fallback covers email/IBAN/phone/address)

## Install

Start `docling-serve` first (see the parent repo's `README.md` — clone the
repo, run `./start_docling_native.sh`), then from inside this `doc2md/`
folder:

```bash
cd doc2md   # skip if you're already here
pip install requests
cp doc_to_markdown.py doc_to_markdown_dialog.py "$HOME/.local/bin/"
echo 'alias doc2md="python3 $HOME/.local/bin/doc_to_markdown.py"' >> ~/.zshrc
source ~/.zshrc
```

Try it once from the terminal to confirm it works before setting up the
Quick Action or VSCode keybinding below:

```bash
doc2md ~/Downloads/some-document.pdf
```

The repo copies are the source of truth; the `~/.local/bin/` copies are what
actually run (Quick Actions and VSCode tasks call fixed paths there). If you
edit `doc_to_markdown.py` later, re-run the `cp` step to redeploy it.

### Terminal

```bash
doc2md ~/Downloads/document.pdf
doc2md file1.pdf file2.docx file3.pptx
doc2md --enrich report.pdf   # + anonymization + tags, see below
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

## `--enrich`: anonymization + tags

```bash
doc2md --enrich report.pdf
```

Optional, **entirely local** — nothing leaves the machine. Runs anonymization
*before* tagging, so no unmasked name can leak into a tag:

1. **Anonymization** (masks exact spans only, never rewrites content):
   - Preferred: an anonymizer service on `http://localhost:8787`
     (`DOC2MD_ANON_URL`) — regex (IBAN/email/phone/address) plus NER for
     names. Not included in this repo (self-host your own; e.g.
     [headroom](https://github.com/headroomlabs-ai/headroom) is one such
     service) — point `DOC2MD_ANON_URL` at it. `POST /api/v1/anon/test`
     with `{"text": "..."}`, response `{"anonymized": "...", "entities_found": N}`.
   - Fallback if that's unreachable: deterministic regex only
     (email/IBAN/phone/German street+number, postal-code+city) — **no name
     detection** in this mode.
2. **Tags**: a local Ollama model (`gemma4:latest` by default, override with
   `DOC2MD_OLLAMA_MODEL`) reads the *already-anonymized* text and returns
   4–6 topic tags, one of which is the document type. Ollama only tags —
   it never rewrites saved content.

Honesty notes: the regex fallback catches no names; the LLM-NER path is
best-effort and only scans the first ~4000 characters per call. Manual
review stays necessary either way. The original filename (`source_file`,
`local_path`) is *not* anonymized — rename the source file first if it
contains a name.

## Testing

```bash
python3 test_doc_to_markdown.py   # frontmatter/sync-detection/regex-PII — no network
python3 test_anon_integrity.py    # anonymizer round-trip — skips if unreachable
```

## Troubleshooting

**docling-serve not reachable** — start it (see parent repo `README.md`),
then `curl http://localhost:5001/health`.

**Quick Action not in Finder menu** — System Settings → Keyboard → App
Shortcuts, check it's listed and configured for "Files and Folders".

**Conversion fails on a specific PDF** — some PDFs have a corrupted embedded
text layer; that's a source-file problem `force_ocr=true` (already the
default here) works around, not a converter bug.
