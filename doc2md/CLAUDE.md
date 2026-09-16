# doc2md

Keyboard-shortcut / Quick-Action front-end for the parent repo's
`docling-serve` (`../start_docling_native.sh`). See `README.md` for
end-user setup; this file is implementation notes.

## Files

| File | Purpose |
|---|---|
| `doc_to_markdown.py` | Main converter — REST client to docling-serve, frontmatter, `--tags` (Ollama), `--pii` (off/mask/pseudo/service/auto) |
| `doc_to_markdown_dialog.py` | tkinter file picker — no Accessibility permission needed, works on locked-down Macs |
| `doc_converter.sh` | Launches the dialog picker detached, for the Quick Action |
| `.claude/hooks/sharepoint_notice.py` + `.claude/settings.json` | PreToolUse hook: warns before editing a file whose frontmatter marks it as a SharePoint sidecar |
| `.vscode/tasks.json` + `setup-vscode-keybinding.sh` | VSCode task + `Cmd+Shift+M` keybinding installer |
| `install-quick-actions.sh` | Builds the three Finder Quick Actions (plain, tags, pseudonymized) and binds their shortcuts in NSUserKeyEquivalents and pbs |
| `test_doc_to_markdown.py` | Frontmatter/sync-detection/regex-PII self-check, no network |
| `test_anon_integrity.py` | headroom round-trip check, skips if the service is offline |
| `test_pseudonymize.py` | Local PII modes: token consistency, reversibility, mask-is-lossy — no network |

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
- **PII before tagging, always in that order**: tagging runs on the
  already-masked text so a real name can't leak into a tag. Neither step
  rewrites content — both only mask/label exact spans.
- **`mask` vs `pseudo` is not cosmetic.** `mask` (`scrub_pii`) is
  *anonymisation*: every email becomes `[email]`, so two people collapse into
  the same placeholder and nothing is recoverable. `pseudo` (`pseudonymize`)
  is *pseudonymisation* per Art. 4(5) GDPR: consistent numbered tokens,
  distinctness preserved, reversible through the mapping — which makes that
  mapping re-identifying data, hence `--pii-map` opt-in and mode 0600.
  `test_pseudonymize.py` pins both properties.
- **Ollama needs a JSON *schema*, not `format: "json"`.** With the bare
  string, qwen3:4b mirrored the prompt's own labels back as keys
  (`{"Dateiname": …, "INHALT": …}`) and tagging silently returned `[]`.
  `_TAGS_SCHEMA`/`_NAMES_SCHEMA` constrain the shape. Reasoning models also
  need `"think": false` or the trace pollutes the response.
- **Never enumerate examples the model can copy.** The tag prompt used to list
  ten document types ("z.B. lebenslauf, anschreiben, stellungnahme, …"). On a
  document whose opening pages carry little signal, qwen3:4b returned exactly
  that list — deterministically, three runs identical. Fixed by splitting the
  schema into `dokumentart` + `themen` and dropping the enumeration: with no
  list in the prompt there is nothing to copy.
- **Sample the document, don't just take the head.** `sample_text()` takes
  beginning, middle and end. The first 6000 characters of a 113-page PDF are
  the cover and the table of contents — worthless for tagging.
- **Name detection is best-effort.** The local modes use the LLM as a stand-in
  NER, chunked over the whole document; it can miss names. Name parts
  (`Frau Brückner`) are derived from the full names in `name_variants()` and
  get `[PERSON_n_NACHNAME]` tokens so the mapping stays reversible. Missing
  Ollama aborts — never write a "pseudonymized" file with names in clear. Only `--pii service` (headroom) uses a real NER model. Manual review
  stays necessary in every mode.
- **Never force OCR unconditionally.** `convert_document(force_ocr=None)`
  converts using the text layer first and only re-runs with OCR when the
  result is essentially empty (`has_text_layer()`). The old hardcoded
  `force_ocr=true` shredded native text PDFs — that is what the parent
  CLAUDE.md warns about.
- **PDF text-layer corruption** (e.g. "nteagrität" instead of "Integrität")
  is a source-file problem, not fixable by the converter or by OCR.
- **Real documents need minutes, not seconds.** 62 pages / 5.3 MB measured at
  ~210 s with image descriptions, ~100 s with `--no-images`; the per-picture
  VLM is the cost. The old 300 s `requests` timeout was below that as soon as
  jobs queued — now `CONVERT_TIMEOUT` (`DOC2MD_TIMEOUT`, default 1800 s).
- **Feedback must come at the start, not only at the end.** The Quick Action
  is silent while it works; a user who gets nothing back presses again. That
  is how three jobs ended up on two workers, all timing out. `--notify` now
  fires once when the run begins, and `file_lock()` (flock, so it dies with
  the process — no stale locks) makes the second keypress a no-op.
- **"Started" alone was not enough** — the next question is always "how long?".
  `duration_hint()` puts a page count and an estimate into that first
  notification. Page count via `mdls` *only*: a real read here would hit the
  same EDEADLK on cloud-only OneDrive files that `read_file_with_retry()`
  exists to avoid. Calibration (M-series, MPS): 62 p / 211 s and 113 p / 365 s
  with descriptions → ~3.4 s per page, ~1.7 s without, plus ~8 s fixed.
- **The server must be a LaunchAgent, not a terminal process.** Started by
  hand it dies with the session and every shortcut then fails from the Finder,
  where there is no terminal to fix it. `../install-docling-agent.sh` installs
  `com.doc2md.docling-serve` (RunAtLoad + KeepAlive).
- **The runtime cannot live under `~/Documents`.** macOS TCC denies a
  LaunchAgent execution there outright (`Operation not permitted`), so venv and
  a copy of the start script go to `~/.local/share/doc2md/`. The repo stays the
  source; re-run the installer after changing `start_docling_native.sh`.
- **`ensure_docling_service()` advances on process presence, not on a timer.**
  `launchctl kickstart` returns exit 0 even when it started nothing — waiting
  out the full timeout on that stage cost four minutes before the next
  fallback got its turn. Now a stage that spawns no process within 10 s is
  abandoned immediately; only a stage with a live process gets the long wait
  for model loading.
