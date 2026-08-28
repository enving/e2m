# Docling: Erkenntnisse aus den Tests (Juli 2026)

Gesammelte Ergebnisse aus den Qualitäts- und Setup-Tests auf dem MacBook —
als Entscheidungsgrundlage für ein späteres **zentrales Hosting im Unternehmen**.

**Testbasis:** hauptsächlich ein bildbasiertes deutsches Zertifikats-PDF (300-DPI-Scan,
fast kein Text-Layer, Umlaute, Logos, Unterschrift). Einzeldokument — die Werte sind
**relative Orientierung, keine Benchmarks**.

---

## 1. OCR-Qualität für Deutsch (wichtigste Erkenntnis)

Getestet am selben Dokument, gleiche Pipeline, nur Engine getauscht:

| Engine | Plattform | Qualität Deutsch | Typische Fehler |
|---|---|---|---|
| **ocrmac** (Apple Vision) | nur macOS, nur nativ | ★★★★★ nahezu fehlerfrei | keine; liest sogar Text in Logos |
| **tesserocr 5.5 + tessdata_best** | überall (Linux ok) | ★★★☆☆ brauchbar | `nat den`→hat den, `erTolgreich`, `I11-Sicherheit`, `Geschäftstuhrung` |
| **Tesseract CLI 4.1** (alte Distro-Version) | Linux-Container | ★★☆☆☆ | wie oben, plus Abstürze bei fehlenden tessdata |
| **RapidOCR** (Docling-Default bei `auto`!) | überall | ★☆☆☆☆ unbrauchbar für Deutsch | `MaBnahmen`, `KaistraBe4.4O221Dusseldorf`, Spacing zerstört |

**Konsequenzen fürs zentrale Hosting (Ubuntu):**
- ⚠️ **ocrmac gibt es auf Linux nicht.** Die beste gefundene Engine ist nicht portierbar.
- Auf Ubuntu ist **tesserocr ≥5.5 mit tessdata_best (deu+eng)** die Baseline — Qualität
  „brauchbar, aber nicht fehlerfrei" bei schwierigen Scans. Bei sauberen Scans deutlich besser.
- `auto` niemals unkonfiguriert lassen: Docling wählt sonst RapidOCR (chinesisch-fokussiert).
  Immer Server-seitig überschreiben: `DOCLING_SERVE_CUSTOM_OCR_PRESETS='{"auto":{...}}'`.
- Für höhere Qualität auf Linux: **OCR-fokussierte VLMs auf GPU** evaluieren
  (Docling unterstützt Presets: `deepseek_ocr`, `nanonets_ocr2`, `glm_ocr`, `lightonocr` —
  von uns **nicht getestet**, aber der naheliegendste Weg, ocrmac-Niveau auf Linux zu erreichen).
- EasyOCR mit Deutsch: von uns nicht getestet, laut Recherche keine belastbaren Belege für
  Überlegenheit gegenüber Tesseract.

## 2. VLM-Pipeline (Seite als Bild → Modell)

| Modell | Größe | Ergebnis bei unserem Scan | Anmerkung |
|---|---|---|---|
| granite-docling (Ollama) | 258M | Fehler auf tesserocr-Niveau | interne Encoder-Auflösung fix → `scale` > 2.0 **bringt nichts** |
| SmolVLM (Bildbeschreibung) | 256M | generisch („a logo") auf CPU; detaillierter/schneller auf GPU | beschreibt Bilder, macht kein Seiten-OCR |
| granite3.3-vision | 2B | in Ollama importiert, in Docling-Serve **nicht** server-seitig einbindbar (jobkit-Bug) | nur per Request-Custom-Config nutzbar |

**Merksatz:** Kleine Dokument-VLMs (≤258M) lösen schwierige deutsche Scans **nicht** besser
als klassisches Tesseract. Der Qualitätssprung kam von der besseren OCR-Engine, nicht vom VLM.

## 3. CPU vs. GPU — gemessene Anhaltspunkte

| Workload | CPU (Container, M-Series via Rosetta-Emulation der AVX-Pfade) | GPU |
|---|---|---|
| SmolVLM Bildbeschreibung | **~33 s pro Bild** | einstellige Sekunden (MPS nativ) |
| granite-docling ganze Seite | — | **3–8 s/Seite** (Ollama, Metal) |
| Layout-/Tabellen-Modelle | funktioniert, spürbar träge | flüssig (MPS) |
| Klassisches OCR (tesserocr/ocrmac) | CPU-bound, ok | profitiert kaum von GPU |
| Modell-Load beim Boot | ~2 min | ~2 min (einmalig) |

**Faustregel:** Reines OCR+Layout geht auf CPU. Sobald **Bildbeschreibung oder
VLM-Pipeline** gewünscht ist (und das war bei uns der Qualitätshebel für Bilder/Logos),
ist eine **GPU praktisch Pflicht** — Faktor grob 5–10× bei kleinen VLMs, bei größeren
Modellen (2B+) ist CPU unbrauchbar.

## 4. Empfehlung zentrales Hosting (grob)

**Basis-Setup (OCR + Layout, ohne Vision):**
- Ubuntu 22.04/24.04, docling-serve Container (CUDA-Image existiert, CPU-Image reicht hier)
- 8+ Cores, 16–32 GB RAM (~2–4 GB RAM pro parallelem Dokument + Modelle)
- tesserocr ≥5.5 + tessdata_best, `auto`-Preset überschreiben
- Skalierung: docling-serve unterstützt drei Engines — `local` (1 Node),
  `RQ` (Redis-Queue, mehrere Worker), `Ray` (Cluster, Autoscaling). Für zentrales
  Hosting mit mehreren Nutzern: **RQ mit 2–4 Workern als Startpunkt**.

**Qualitäts-Setup (mit Bildbeschreibung/VLM — empfohlen wenn Budget da):**
- + NVIDIA-GPU: für 2B-Modelle reichen **8–12 GB VRAM** (granite3.3-vision Q4 ≈ 2.4 GB,
  granite-docling 258M winzig); für OCR-VLMs der 7B-Klasse eher **24 GB** (z. B. L4, A10, RTX 4090)
- VLM-Serving getrennt von docling-serve: **vLLM oder Ollama als eigener Dienst**,
  docling-serve spricht es per `engine_type: api` an (genau wie unser Ollama-Setup) —
  dann können mehrere docling-Worker sich eine GPU teilen
- Erwartung: 3–8 s/Seite VLM, <1 s/Bild Beschreibung

**Was NICHT geht / Fallstricke fürs Hosting:**
- ocrmac (beste deutsche OCR) existiert nur auf macOS — auf Linux OCR-VLMs evaluieren
- Docker auf macOS hat kein GPU-Passthrough — Macs taugen nicht als Container-Host für dieses Workload
- Ollama hinter Firmenproxy: `ollama pull` scheitert; Modelle als GGUF per `curl -x <proxy>`
  von HuggingFace laden und mit `ollama create` importieren
- HuggingFace-Zugang für Modell-Downloads nötig (docling lädt Layout-/Tabellen-Modelle beim Boot);
  hinter Proxy: `HTTPS_PROXY` setzen, funktioniert
- `force_ocr=true` zerstört korrekte Text-Layer (aus „08.07.2026" wird „D8.07.2026") —
  niemals global aktivieren; Docling hat **keine** Auto-Erkennung für kaputte Text-Layer
- docling rendert für Tesseract hartkodiert mit 216 DPI — `images_scale` ändert daran nichts

## 5. Docling-Serve Konfigurations-Fallstricke (API/Server)

- Clients senden default `ocr_preset="auto"` → Server-Override via Custom-Preset `"auto"` greift transparent
- Server-seitige `CUSTOM_PICTURE_DESCRIPTION_PRESETS` mit `api_ollama`: **Deserialisierungs-Bug**
  in docling-jobkit (dict statt Options-Objekt) — Ollama-VLMs nur per Request-Config
- Verschachtelte JSON-Optionen nie als Form-Feld, immer `-F "options=@file.json;type=application/json"`
- `vlm_pipeline_preset`: erlaubte Namen sind `default`, `smoldocling`, `granite_vision`, … —
  der Server-Default heißt im Request immer `default`
- `picture_description_preset` allein aktiviert nichts — `do_picture_description=true` muss mit
- `picture_description_area_threshold` default 5 % ist für Logos zu hoch → 0.005 (0,5 %)

## 6. Offene Punkte für die Hosting-Entscheidung

- [ ] OCR-VLMs (deepseek_ocr, nanonets_ocr2) auf GPU gegen tesserocr benchmarken —
      entscheidet, ob Linux ocrmac-Qualität erreichen kann
- [ ] Durchsatz-Test mit realistischem Dokumentenmix (nicht nur 1 Zertifikat)
- [ ] RQ-Setup mit Redis testen (Multi-Worker)
- [ ] Klären: welche Dokumenttypen/Volumen kommen im Unternehmen wirklich an
      (bestimmt CPU/GPU-Dimensionierung mehr als alles andere)
