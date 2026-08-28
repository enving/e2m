# doc2md

Keyboard-shortcut / Quick-Action front-end for the parent repo's
`docling-serve` (`../start_docling_native.sh`). See `README.md` for
end-user setup; this file is implementation notes.

## Files

| File | Purpose |
|---|---|
| `doc_to_markdown.py` | Main converter — REST client to docling-serve, frontmatter, `--enrich` (anonymize + tag) |
| `doc_to_markdown_dialog.py` | tkinter file picker — no Accessibility permission needed, works on locked-down Macs |
| `doc_converter.sh` | Launches the dialog picker detached, for the Quick Action |
| `.claude/hooks/sharepoint_notice.py` + `.claude/settings.json` | PreToolUse hook: warns before editing a file whose frontmatter marks it as a SharePoint sidecar |
| `.vscode/tasks.json` + `setup-vscode-keybinding.sh` | VSCode task + `Cmd+Shift+M` keybinding installer |
| `test_doc_to_markdown.py` | Frontmatter/sync-detection/regex-PII self-check, no network |
| `test_anon_integrity.py` | Anonymizer round-trip check, skips if the service is offline |

Deployment convention: `doc_to_markdown.py`/`doc_to_markdown_dialog.py` are
copied to `~/.local/bin/` — the repo copy alone isn't what Quick
Actions/VSCode invoke, since those need a path that doesn't depend on where
this repo happens to be checked out.

## Gotchas

- **Cloud-only files (OneDrive "Files On-Demand")**: reading from the
  Quick-Action/Finder context raises `[Errno 11] Resource deadlock avoided`
  before the file has downloaded. `read_file_with_retry()` triggers the
  download via a detached `launchctl submit` job (outside the blocked
  context) and retries.
- **Automator must run detached** (`nohup ... &`): Automator holds a
  file-coordination claim on selected files for as long as the action runs;
  a synchronous read inside that window hits the same EDEADLK. Feedback
  comes back via `--notify` → macOS notification instead of stdout.
- **Anonymize before tagging, always in that order**: tagging runs on the
  already-masked text so a real name can't leak into a tag. Neither step
  rewrites content — both only mask/label exact spans.
- **PDF text-layer corruption** (e.g. "nteagrität" instead of "Integrität")
  is a source-file problem, not fixable by the converter or by OCR.
