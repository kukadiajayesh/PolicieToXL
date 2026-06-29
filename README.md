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

Then open **http://127.0.0.1:5000**.

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
python3 app.py            # backend on :5000
cd frontend && npm run dev   # UI on :5173, proxies /api to :5000
```

## Note on extraction accuracy

The regex patterns in `extract_policies.py` are tuned for the **HDFC ERGO**
layout. Other insurers (ICICI Lombard, etc.) will leave some fields blank — that
is expected. The editable results table is there precisely so you can correct
those fields by hand, and you can extend the regexes per insurer over time.

## Fields extracted

Party Name · Insurance Company · Reg Number · Type of Insurance ·
Premium without GST · Premium with GST · Start Date · End Date ·
NCB (this year) · NCB (previous policy) · Source File
