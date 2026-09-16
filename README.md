# Everything2Markdown

PDF/DOCX-to-Markdown conversion stack built on [Docling](https://github.com/docling-project/docling-serve), tuned for knowledge-management/RAG pipelines. Runs natively on macOS for best OCR and GPU performance; Docker fallback available for other platforms.

## Goal

Two problems, one pipeline — and no coding required to use it:

**Sensitive data shouldn't have to leave your computer to become useful to AI.**
The usual way to make a document searchable or usable by an AI tool is to
upload it to a cloud service first — a scanned contract, an HR file, a
certificate with someone's name and address on it. That upload is exactly
the moment personal or confidential data leaves your control. This project
moves that step onto your own Mac instead: the scan-to-text conversion runs
locally, and the optional anonymization step (blacking out names, emails,
IBANs, addresses) also runs locally, *before* the text ever reaches a cloud
AI model. If you choose not to use a cloud AI at all, nothing ever leaves
your machine.

**Turning a folder of PDFs into a usable, searchable knowledge base is
normally a lot of manual work.** Copying text out of scans, cleaning it up,
tagging it, giving it consistent structure — that's hours of tedious work
per document. Here it's one keyboard shortcut: select a file, press a key
combination, and a few seconds later you have a clean, tagged, search-ready
document — no terminal, no coding, no manual copy-pasting.

## What you get

| Shortcut (Finder, file selected) | Right-click → Quick Actions | Result |
|---|---|---|
| `Cmd+Shift+M` | Convert to Markdown | clean `.md` with YAML frontmatter next to the original |
| `Cmd+Ctrl+M` | Convert to Markdown with Tags | + topic tags from a local AI model |
| `Cmd+Ctrl+Opt+M` | Convert to Markdown pseudonymisiert | + tags + personal data replaced by tokens (`[PERSON_1]`, `[EMAIL_2]`, `[IBAN_1]` …), reversible via a key file kept apart |

Plus `doc2md file.pdf` in the terminal, a VSCode keybinding, and a local
HTTP API (`http://localhost:5001`) for OpenWebUI or your own scripts.
Works for PDF (native and scanned), DOCX, PPTX, HTML and images.

## Install

**Requirements:** macOS (Apple Silicon or Intel), ~6 GB free disk space
(+2.5 GB for the AI model), Xcode Command Line Tools
(`xcode-select --install` if you don't have them).

### Easiest: let your coding agent do it

Paste this into Claude Code, Codex, Cursor or any coding agent with terminal access:

> Install https://github.com/enving/e2m on my Mac. Clone it, follow its
> `AGENTS.md`, verify that a test conversion works, and then tell me how to use
> the keyboard shortcuts.

[`AGENTS.md`](AGENTS.md) contains the checks, the verification steps and
the known pitfalls, so the agent does not have to guess.

### Or yourself, in the terminal

```bash
git clone https://github.com/enving/e2m.git ~/e2m
cd ~/e2m
./install.sh --with-ollama
```

That one command:

1. creates a Python venv in `~/.local/share/doc2md/` and installs
   docling-serve 1.32 + `ocrmac` (Apple Vision OCR),
2. registers a LaunchAgent so the server starts at every login,
3. installs the `doc2md` command and the three Finder Quick Actions with
   their shortcuts,
4. with `--with-ollama`: installs [Ollama](https://ollama.com) via Homebrew
   and pulls `qwen3:4b` for tags and name detection.

The first run downloads several GB and takes a while; running it again is
safe and repairs a broken install. Leave out `--with-ollama` if you only
want plain conversion. `./install.sh --uninstall` removes it again.

**Behind a corporate proxy?** `export HTTP_PROXY=… HTTPS_PROXY=…` first.

Check it works:

```bash
curl http://localhost:5001/health     # {"status":"ok"}
doc2md ~/Downloads/some-document.pdf  # writes some-document.md next to it
```

### What happens under the hood (manual setup)

<details>
<summary>Step by step, if you'd rather not run the installer</summary>

```bash
# 1. venv OUTSIDE ~/Documents — macOS privacy protection (TCC) forbids a
#    LaunchAgent from executing anything under ~/Documents, ~/Desktop, ~/Downloads
python3.12 -m venv ~/.local/share/doc2md/docling-native
~/.local/share/doc2md/docling-native/bin/pip install "docling-serve==1.32.0" ocrmac

# 2. start at login (also copies start_docling_native.sh next to the venv)
./install-docling-agent.sh
#    status: launchctl print gui/$(id -u)/com.doc2md.docling-serve
#    log:    tail -f ~/Library/Logs/docling-serve.log
#    manual start instead: ./start_docling_native.sh

# 3. doc2md command + Finder Quick Actions + shortcuts
/usr/bin/python3 -m pip install --user requests
./doc2md/install-quick-actions.sh

# 4. optional: local AI model for tags and pseudonymization
brew install ollama && brew services start ollama && ollama pull qwen3:4b
```

`start_docling_native.sh` configures ocrmac for German + English, Metal
(MPS) GPU acceleration and stops a Docker `docling-serve` container if one
occupies port 5001. For VLM-based layout analysis you can additionally pull
`ibm/granite-docling:258m` and `granite3.3-vision:2b`; see `DOCLING_API.md`.

</details>


## Using the API directly (curl)

### Simple PDF → Markdown

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@~/Downloads/document.pdf" \
  -F "to_format=md"
```

### With image descriptions (recommended)

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@~/Downloads/document.pdf" \
  -F "to_format=md" \
  -F "do_picture_description=true" \
  -F "include_images=true" \
  -F "picture_description_area_threshold=0.005"
```

### Scanned/image-based PDFs

```bash
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@~/Downloads/scan.pdf" \
  -F "to_format=md" \
  -F "force_ocr=true"
```

**Important:** Use `force_ocr=true` only for image-based PDFs without a text layer. On native PDFs with embedded text, `force_ocr=true` makes results worse (OCR reads pixels instead of the precise text layer).

## Usage: Convenience Wrappers

Instead of curl, you can use the included CLI wrappers:

```bash
# Basic conversion, output to stdout
./examples/convert-file.sh ~/Downloads/document.pdf

# Advanced wrapper with options
./docling_convert.sh ~/Downloads/document.pdf
./docling_convert.sh ~/Downloads/document.pdf --no-images  # skip picture description
./docling_convert.sh ~/Downloads/document.pdf --vlm        # use VLM-based layout (slower, better for complex documents)
./docling_convert.sh ~/Downloads/document.pdf --force-ocr  # force OCR on native PDFs (not recommended)
./docling_convert.sh ~/Downloads/document.pdf --async      # async mode for large documents
./docling_convert.sh ~/Downloads/document.pdf --out result.md  # save to file
./docling_convert.sh ~/Downloads/document.pdf --pages 1-5  # convert only pages 1-5
```

## Architecture: Native vs Docker

### Native (Recommended)

- **OCR:** ocrmac (Apple Vision Framework) — best-in-class for German
- **GPU:** Metal (MPS) for layout and table models
- **Language:** de-DE + en-US
- **Performance:** Bilder ~1–3 s each, pages ~3–8 s with VLM
- **How to start:** `./install-docling-agent.sh` once, then automatic at login
- **Logs:** `~/Library/Logs/docling-serve.log`
- **Pros:** Fastest OCR for German, GPU acceleration, local-only
- **Cons:** macOS only

### Docker Fallback (Not Recommended)

If you need to run on non-macOS or the native setup fails:

```bash
docker compose up -d
docker compose down
```

**Caveats:**
- Uses Tesseract OCR instead of ocrmac — noticeably worse German quality
- No GPU passthrough on macOS (Metal not available in container)
- Slower than native
- See `compose.yaml` for configuration

## Keyboard Shortcuts, Finder and Pseudonymization (doc2md)

`install.sh` sets these up. `doc2md` wraps the API with YAML frontmatter,
optional tags and optional local anonymization/pseudonymization:

- **Finder:** `Cmd+Shift+M` / `Cmd+Ctrl+M` / `Cmd+Ctrl+Opt+M` or right-click → Quick Actions (see [What you get](#what-you-get))
- **VSCode:** `Cmd+Shift+M` to convert the open file
- **Terminal:** `doc2md file.pdf`, `doc2md --tags --pii pseudo --pii-map-dir ~/keys file.pdf`

Details, all options and the honest limits of name detection:
[`doc2md/README.md`](doc2md/README.md).

## OpenWebUI Integration

To use this docling-serve instance with [OpenWebUI](https://openwebui.com/) for document extraction in RAG:

1. OpenWebUI Admin Settings → Documents
2. Content Extraction Engine → `docling`
3. Docling Server URL → `http://host.docker.internal:5001` (if OpenWebUI is in Docker) or `http://localhost:5001` (if OpenWebUI runs natively)
4. Standard extraction → leave parameters empty
5. Advanced (images + VLM) → copy the JSON from `openwebui-docling-params.json` into the `DOCLING_PARAMS` field

## Troubleshooting

### Port 5001 already in use

```bash
lsof -i :5001
# Kill the process, or check if Docker is still running:
docker ps | grep docling
docker compose down
```

Then restart: `./start_docling_native.sh`

### Server won't start / venv not found

```bash
# Verify venv exists and has docling-serve:
ls ~/.local/share/doc2md/docling-native/bin/docling-serve
~/.local/share/doc2md/docling-native/bin/docling-serve --version
```

If missing: run `./install.sh` again — it repairs the venv and the autostart.

### Shortcut does nothing

Check `~/Library/Logs/doc2md.log`. No new `argv=` line → the keystroke never
reached the Quick Action: run `./doc2md/install-quick-actions.sh` again (it
binds the key in both places macOS uses and restarts Finder) and restart the
app you pressed it in. A new line followed by a long wait → it is working;
large PDFs take minutes and notify you at the end.

### Conversion fails or poor OCR quality

Verify the native server is running (not Docker):

```bash
lsof -i :5001
# Process should be "Python" from ~/.local/share/doc2md/docling-native/, not Docker
```

Check the log:

```bash
tail -f ~/Library/Logs/docling-serve.log
```

### Ollama models won't pull (behind corporate proxy)

Ollama doesn't read proxy environment variables. Download the model GGUF manually and import it (see DOCLING_ERKENNTNISSE.md section 4 for details).

## Project Policy

OCR/conversion errors are fixed at the source (OCR engine, input resolution, model choice), **not** patched in Markdown output with regex corrections. No output post-processing.

## Files

| File | Purpose |
|---|---|
| `install.sh` | One-step installer: venv, autostart, doc2md, shortcuts, optional Ollama |
| `AGENTS.md` | Install and verification instructions for coding agents |
| `start_docling_native.sh` | Starts native docling-serve (ocrmac + MPS) |
| `install-docling-agent.sh` | Installs the LaunchAgent so the server starts at login |
| `docling_convert.sh` | CLI wrapper with options: `--vlm`, `--force-ocr`, `--async`, `--pages`, etc. |
| `examples/convert-file.sh` | Minimal conversion example |
| `DOCLING_API.md` | Full API reference: all endpoints, parameters, presets, custom configs |
| `DOCLING_QUICK_REF.md` | Quick commands for common scenarios; troubleshooting |
| `DOCLING_ERKENNTNISSE.md` | Test results, OCR quality analysis, hosting recommendations (German) |
| `compose.yaml` | Docker Compose configuration (Tesseract fallback, not recommended) |
| `openwebui-docling-params.json` | JSON config for OpenWebUI integration |
| `doc2md/` | Keyboard-shortcut / Finder / VSCode wrapper with frontmatter and anonymization |

## Further Reading

- **API Details:** see `DOCLING_API.md` — all parameters, OCR presets, VLM options, chunking, async
- **Quick Start:** see `DOCLING_QUICK_REF.md` — common curl commands and troubleshooting
- **Architecture & Hosting:** see `DOCLING_ERKENNTNISSE.md` — OCR quality analysis, hardware recommendations, known issues
- **Keyboard Shortcut Setup:** see `doc2md/README.md` — Finder, VSCode, terminal integration
