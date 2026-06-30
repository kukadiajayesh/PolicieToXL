# Insurance Policy Extractor — UI

A fully offline desktop-style tool to extract structured data from insurance
policy PDFs into Excel. **React frontend, Python backend, nothing leaves your
machine.**

## Architecture

```
React (Vite)  ──fetch──▶  Flask (app.py)  ──▶  extract_policies.py  ──▶  Excel
   frontend/                 local API           pdfplumber + regex       openpyxl
```

The React app is built to static files and served by Flask, so at runtime there
is **no internet dependency** — PDFs are read locally and the Excel file is
written to a local path you choose.

## Run it

The easy way:

```bash
./run.sh
```

Or manually:

```bash
# 1. Python deps
python3 -m pip install -r requirements.txt

# 2. Build the React UI (first time only)
cd frontend && npm install && npm run build && cd ..

# 3. Start
python3 app.py
```

Then open **http://127.0.0.1:5001**.

## Using the UI

1. **Add PDFs** — either paste a folder path and click *Scan*, or drag & drop
   PDF files onto the dropzone.
2. **Extract all** — each file shows a live status badge (Pending → Reading →
   Done / Error).
3. **Edit the results** — every cell in the table is editable, so you can fix
   any field the parser missed before exporting.
4. **Export** — *Save to disk* (type an output path like
   `~/Desktop/policies.xlsx`) or *Download .xlsx* through the browser.

## Develop the UI with hot reload

```bash
python3 app.py            # backend on :5001
cd frontend && npm run dev   # UI on :5173, proxies /api to :5001
```

## Ollama (AI extraction)

The app supports a local LLM via [Ollama](https://ollama.com) as an alternative
to the regex engine. Useful for PDFs from insurers not yet covered by the regex
patterns.

### 1. Install Ollama

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# macOS (Homebrew)
brew install ollama
```

### 2. Pull a model

Text extraction (fast, low memory):

```bash
ollama pull llama3.2        # ~2 GB, good all-rounder
ollama pull qwen2.5:7b      # slightly more accurate on structured data
```

Vision extraction (for scanned / image-only PDFs):

```bash
ollama pull llava:7b        # ~4 GB, multimodal
ollama pull minicpm-v       # lighter alternative
```

### 3. Start Ollama

```bash
ollama serve
```

Ollama listens on `http://localhost:11434` by default. The app checks this
endpoint automatically and shows a status indicator in the UI.

### 4. Select Ollama in the UI

In the extraction panel, switch the **Engine** toggle from *Regex* to *Ollama*
and pick your model from the dropdown. Then extract as usual.

**Vision fallback** — if a PDF has fewer than 200 characters of extractable
text (scanned / image PDF), the app automatically retries using the vision API
instead of the text API. A vision-capable model (`llava`, `minicpm-v`, etc.)
must be installed for this to work; otherwise it falls back to the text prompt.

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Ollama not running" badge | `ollama serve` is not running — start it |
| Empty model list | Pull at least one model: `ollama pull llama3.2` |
| Timeout on large PDFs | Only the first 8 000 chars are sent; try a faster model |
| Vision fails | Install `pymupdf`: `pip install pymupdf` |

---

## Note on extraction accuracy

The regex patterns in `extract_policies.py` are tuned for the **HDFC ERGO**
layout. Other insurers (ICICI Lombard, etc.) will leave some fields blank — that
is expected. The editable results table is there precisely so you can correct
those fields by hand, and you can extend the regexes per insurer over time.

## Fields extracted

Party Name · Insurance Company · Policy No. · Reg Number · Type of Insurance ·
Premium · Start Date · End Date ·
NCB (applied this yr) · Source File
