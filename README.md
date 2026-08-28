# Everything2Markdown

PDF/DOCX-to-Markdown conversion stack built on [Docling](https://github.com/docling-project/docling-serve), tuned for knowledge-management/RAG pipelines. Runs natively on macOS for best OCR and GPU performance; Docker fallback available for other platforms.

## Prerequisites

- **macOS** (Intel or Apple Silicon)
- **Python 3** (version requirement: not explicitly documented in repo; see note below)
- **curl** (for API calls; included on macOS)
- **Ollama** (optional, for VLM-based image description and complex document layout)

**Installation note:** The exact pip install command for docling-serve is not documented in this repo. The server version is docling-serve 1.26. You'll need to install it into a Python venv (see Setup below).

## Installation

### 1. Clone and enter the repo

```bash
git clone <repo-url>
cd Everything2Markdown
```

### 2. Create and activate a Python venv

```bash
python3 -m venv docling-native
source docling-native/bin/activate
```

### 3. Install docling-serve

The exact pip command is not pinned in the repo. Install the package:

```bash
pip install docling-serve
```

(If you need a specific version, try `pip install docling-serve==1.26` based on the version documented in DOCLING_API.md, but this is not explicitly recommended in the codebase.)

### 4. Start the native server

```bash
./start_docling_native.sh
```

The script:
- Stops any running Docker `docling-serve` container (port 5001 conflict)
- Sets up ocrmac (Apple Vision) OCR with German+English language support
- Enables Metal GPU (MPS) for layout and table models
- Logs to `/tmp/docling-native.log`

**Behind a corporate proxy?** Set `HTTP_PROXY` and `HTTPS_PROXY` before running:

```bash
export HTTP_PROXY="http://proxy-host:port"
export HTTPS_PROXY="http://proxy-host:port"
./start_docling_native.sh
```

### 5. Verify the server is running

```bash
curl http://localhost:5001/health
# Expected: {"status": "ok"} or similar
```

Open the API docs in your browser:

```bash
open http://localhost:5001/docs
```

### 6. (Optional) Set up Ollama for VLM features

If you want advanced image descriptions or VLM-based document layout analysis:

```bash
# Install Ollama from https://ollama.com
# Then pull models used by this project:
ollama pull ibm/granite-docling:258m
ollama pull granite3.3-vision:2b
ollama pull gemma4
```

Ollama runs locally on port 11434. If you're behind a corporate proxy, `ollama pull` may fail. Workaround: download models manually and import them (see DOCLING_ERKENNTNISSE.md for details).

## First Conversion

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
- **How to start:** `./start_docling_native.sh`
- **Logs:** `/tmp/docling-native.log`
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

## Optional: Keyboard Shortcut / Finder Integration (doc2md)

A companion tool for macOS keyboard shortcuts, Finder Quick Actions, and VSCode integration that wraps this API with YAML frontmatter and optional local anonymization:

- **Finder Quick Action:** right-click → "Convert to Markdown"
- **VSCode:** Cmd+Shift+M to convert the open file
- **Terminal:** `doc2md file.pdf`

See [`doc2md/README.md`](doc2md/README.md) for setup.

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
ls docling-native/bin/docling-serve
docling-native/bin/docling-serve --version
```

If missing: re-run steps 2–3 in Installation.

### Conversion fails or poor OCR quality

Verify the native server is running (not Docker):

```bash
lsof -i :5001
# Process should be "Python" from ./docling-native/, not a Docker container
```

Check the log:

```bash
tail -f /tmp/docling-native.log
```

### Ollama models won't pull (behind corporate proxy)

Ollama doesn't read proxy environment variables. Download the model GGUF manually and import it (see DOCLING_ERKENNTNISSE.md section 4 for details).

## Project Policy

OCR/conversion errors are fixed at the source (OCR engine, input resolution, model choice), **not** patched in Markdown output with regex corrections. No output post-processing.

## Files

| File | Purpose |
|---|---|
| `start_docling_native.sh` | Starts native docling-serve (ocrmac + MPS) |
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
