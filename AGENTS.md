# AGENTS.md — instructions for coding agents

This file is for AI coding agents (Claude Code, Codex, Cursor, OpenCode, …)
asked to **install Everything2Markdown for a user**, or to work on its code.
Developer notes and hard-won findings live in [`CLAUDE.md`](CLAUDE.md) and
[`doc2md/CLAUDE.md`](doc2md/CLAUDE.md) — read those before changing code.

## Installing for a user

The user is probably not a developer. They want: select a file in Finder,
press a shortcut, get a Markdown file next to it. Everything runs locally.

### 1. Check the machine

- **macOS only** for the full setup (Finder shortcuts, Apple Vision OCR).
  On Linux/Windows stop here and offer the Docker fallback
  (`docker compose up -d`, see README) — no shortcuts, worse German OCR.
- Needs ~6 GB free disk space (venv + models), more with Ollama (+2.5 GB).
- `xcode-select -p` must succeed. If not, ask the user to run
  `xcode-select --install` and confirm the dialog — you cannot click it.

### 2. Clone and run the installer

```bash
git clone https://github.com/enving/e2m.git ~/e2m
cd ~/e2m
./install.sh --with-ollama     # recommended: enables tags + pseudonymization
# ./install.sh                 # minimal: plain conversion only, no Ollama
```

- Clone **outside** `~/Documents`, `~/Desktop`, `~/Downloads` if you can
  (macOS privacy protection). It still works there — runtime files are copied
  to `~/.local/share/doc2md/` — but it avoids confusing permission prompts.
- The installer is **idempotent and non-interactive**. If it fails, fix the
  cause and simply run it again.
- The first run downloads several GB (pip + Docling models). Use a long
  timeout (≥ 20 min) or run it in the background and poll.
- The first server start loads models; the installer waits up to 5 minutes.
- **Corporate proxy:** export `HTTP_PROXY`/`HTTPS_PROXY` before running.
  `ollama pull` ignores proxies — see README → Troubleshooting.

### 3. Verify — do not skip

```bash
curl -s http://localhost:5001/health           # {"status":"ok"}
launchctl print gui/$(id -u)/com.doc2md.docling-serve | grep state   # running
doc2md --help >/dev/null && echo ok            # needs ~/.local/bin in PATH
```

Then convert a real file end to end:

```bash
printf '<meta charset="utf-8"><h1>Test</h1><p>Maßnahmen für Düsseldorf.</p>' > /tmp/e2m.html
textutil -convert docx /tmp/e2m.html -output /tmp/e2m-test.docx
doc2md /tmp/e2m-test.docx && cat /tmp/e2m-test.md    # frontmatter + text, umlauts intact
```

You **cannot** test the keyboard shortcut yourself (macOS blocks synthetic
keystrokes from agents). Ask the user to select a file in Finder and press
`Cmd+Shift+M`, then check `~/Library/Logs/doc2md.log` for a new `argv=` line.

### 4. Tell the user how to use it

| Shortcut | Finder right-click → Quick Actions | Result |
|---|---|---|
| `Cmd+Shift+M` | Convert to Markdown | `.md` next to the file |
| `Cmd+Ctrl+M` | Convert to Markdown with Tags | + topic tags (Ollama) |
| `Cmd+Ctrl+Opt+M` | Convert to Markdown pseudonymisiert | + tags + names, emails, phones, IBAN, addresses, birth dates, ID numbers replaced by tokens |

- A notification appears at start and end. Large PDFs take minutes
  (a few seconds per page); pressing again while it runs is ignored, not duplicated.
- Pseudonymization keys go to `~/Documents/doc2md-mappings/` — tell the user
  never to share that folder together with the `.md` files, and to skim the
  result before sharing: name detection is LLM-based and can miss a name.

### Known pitfalls (already solved — don't rediscover them)

| Symptom | Cause / fix |
|---|---|
| Shortcut does nothing, right-click works | Re-run `doc2md/install-quick-actions.sh`; it binds the key in both places macOS uses and restarts Finder. Apps opened before install need a restart. |
| "docling-serve läuft nicht" | `./install-docling-agent.sh` (re-run is safe) |
| `Operation not permitted` in docling-serve.log | venv/script inside `~/Documents` — the agent installer moves them; re-run it |
| `Bootstrap failed: 5: Input/output error` | old install script; current one waits for bootout — pull and re-run |
| Pseudonymized run aborts "Namenserkennung via Ollama … fehlgeschlagen" | intended: Ollama down → no file with names in clear. `brew services start ollama` |
| Garbled umlauts in *your* test file | your test file wasn't UTF-8 (e.g. `textutil` without `<meta charset>`), not the converter |

### Uninstall

```bash
./install.sh --uninstall          # removes autostart, Quick Actions, doc2md
rm -rf ~/.local/share/doc2md      # the venv, if the user wants the space back
```

## Working on the code

- Tests, no network: `cd doc2md && python3 test_pseudonymize.py && python3 test_doc_to_markdown.py`
- After editing `doc2md/doc_to_markdown.py`, redeploy with
  `doc2md/install-quick-actions.sh` — Finder runs the copy in `~/.local/bin/`.
- Fix OCR/conversion problems at the source (engine, resolution, model),
  never by regex-patching the Markdown output.
