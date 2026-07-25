# Insurance Policy Extractor — UI

A desktop-style tool to extract structured data from insurance policy PDFs
into Excel. **React frontend, Python backend**, using Google's Gemini API to
read each PDF and pull out the fields.

## Architecture

```
React (Vite)  ──fetch──▶  Flask (app.py)  ──▶  extract_policies.py  ──▶  Excel
   frontend/                 local API          pdfplumber + Gemini API   openpyxl
```

The React app is built to static files and served by Flask. PDFs and the
generated Excel file stay on your machine, but the document contents are sent
to Google's Gemini API for field extraction — see the **Gemini** section below.

## Run it

**macOS / Linux — one command** (creates `.venv`, installs Python deps, builds
the React UI on first run, starts the server):

```bash
./run.sh
```

Or double-click **`Start Policy Extractor.command`** in Finder — it runs
`run.sh` in the background; open http://127.0.0.1:5001 once the server is up.

**Windows — one command** (PowerShell equivalent of `run.sh`):

```powershell
run.bat
```
(or right-click → Run with PowerShell on `run.ps1`)

**Manual / any OS:**

```bash
# 1. Python deps
python3 -m pip install -r requirements.txt

# 2. Build the React UI (first time only)
cd frontend && npm install && npm run build && cd ..

# 3. Start
python3 app.py
```

Then open **http://127.0.0.1:5001** in your browser.

See `PACKAGING.md` for building a standalone installer/binary (Windows/macOS/Linux).

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

## Gemini (cloud AI extraction)

The app uses Google's Gemini API to read each PDF and extract fields —
**document contents are sent to Google's servers**, so don't use this for PDFs
that must stay on the machine.

1. Get an API key from [Google AI Studio](https://aistudio.google.com/apikey)
   (there is a free tier).
2. Open **Settings** and paste the key when prompted — it is validated and
   saved to `~/.pdfxl_config.json` so you only do this once. Alternatively set
   the `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) environment variable before
   starting the app.
3. Pick a model from the dropdown (the *flash* models are fast, cheap and
   plenty for field extraction) and extract as usual.

PDFs with a good text layer are sent as text (first 30 000 characters,
`GEMINI_MAX_CHARS` to change). Scanned / image-only PDFs are uploaded whole so
Gemini can read the pages itself; files over 20 MB fall back to rendered page
images.

---

## Note on extraction accuracy

Extraction accuracy depends on how cleanly the PDF's text layer maps to the
fields Gemini is asked for. Some insurer layouts will leave a field blank or
misread it — that is expected. The editable results table is there precisely
so you can correct those fields by hand before exporting.

## Fields extracted

Party Name · Insurance Company · Policy No. · Reg Number · Type of Insurance ·
Premium · Start Date · End Date ·
NCB (applied this yr) · Source File
