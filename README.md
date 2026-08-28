# Everything2Markdown

Local document-conversion stack (PDF/DOCX → Markdown) built on
[Docling](https://github.com/docling-project/docling-serve), tuned for
knowledge-management/RAG pipelines.

## Architecture

- `docling-serve` runs **natively on macOS** (not in Docker) so it can use
  Apple's Vision framework for OCR and the Metal GPU (MPS) for the layout and
  table models. Docker on macOS has no GPU passthrough, and Apple's OCR engine
  only works natively.
- OCR: **ocrmac** (Apple Vision Framework) — best-in-class for languages like
  German, configured via `de-DE`+`en-US`.
- GPU: **MPS (Metal)** for layout/table models.
- Optional VLM picture-description/page pipeline via a local
  [Ollama](https://ollama.com) instance (e.g. `ibm/granite-docling:258m`,
  `granite3.3-vision:2b`).
- A Docker Compose stack (`compose.yaml`, Tesseract-based) is kept as a
  fallback for non-macOS hosts — OCR quality is noticeably worse than ocrmac,
  especially for German.

## Start (native)

```bash
./start_docling_native.sh
# stops a running Docker container automatically (port conflict)
# log: /tmp/docling-native.log
```

Stop:

```bash
pkill -f docling-serve
```

Useful URLs:

- API: http://localhost:5001
- Docs/Swagger: http://localhost:5001/docs

If you're behind a corporate proxy (needed for the initial HuggingFace model
downloads), export `HTTP_PROXY`/`HTTPS_PROXY` before running the script — see
`start_docling_native.sh`.

## Standard API call

```bash
# Native PDFs with an embedded text layer — do NOT set force_ocr
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@document.pdf" \
  -F "to_format=md" \
  -F "do_picture_description=true" \
  -F "include_images=true" \
  -F "picture_description_area_threshold=0.005"

# Image-based / scanned PDFs (no text layer)
curl -X POST http://localhost:5001/v1/convert/file \
  -F "files=@scan.pdf" \
  -F "to_format=md" \
  -F "force_ocr=true"
```

> `force_ocr=true` is only for image-based PDFs. On native text PDFs it makes
> results worse (OCR reads pixels instead of the text layer).

Or use the convenience wrapper:

```bash
./docling_convert.sh path/to/file.pdf
./examples/convert-file.sh path/to/file.pdf
```

For a macOS keyboard-shortcut / Finder Quick Action / VSCode task that calls
this API and adds OKF-compatible frontmatter (with optional local
anonymization + tagging), see [`doc2md/`](doc2md/README.md).

## OpenWebUI integration

1. Admin Settings → Documents
2. Content Extraction Engine: `docling`
3. Docling Server URL: `http://host.docker.internal:5001` (or
   `http://localhost:5001` if OpenWebUI also runs natively)
4. Standard extraction: leave parameters empty.
5. Advanced (images, VLM): use the JSON in `openwebui-docling-params.json` as
   `DOCLING_PARAMS`.

## Docker fallback (not recommended)

```bash
docker compose up -d   # emergency use only
docker compose down
```

Uses Tesseract OCR (`./tessdata/`) instead of ocrmac — noticeably worse
German OCR quality, no GPU acceleration.

## Project policy: no output post-processing

OCR/conversion errors are fixed at the source (engine, resolution, model
choice), not patched afterwards with regex corrections on the Markdown
output.

## Files

| File | Purpose |
|---|---|
| `start_docling_native.sh` | Starts native docling-serve (ocrmac + MPS) |
| `docling_convert.sh` | CLI wrapper for conversions (`--vlm`, `--force-ocr`, `--async`, `--pages`) |
| `DOCLING_API.md` | Full API reference, including non-obvious parameters |
| `DOCLING_QUICK_REF.md` | Quick reference for common commands |
| `DOCLING_ERKENNTNISSE.md` | Test findings and hosting recommendations (German) |
| `compose.yaml` | Docker fallback (Tesseract-based) |
| `openwebui-docling-params.json` | Docling options for the OpenWebUI integration |
