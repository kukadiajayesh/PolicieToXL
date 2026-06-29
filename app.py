"""
Local Flask backend for the insurance-policy PDF extractor.

Reuses the offline extraction logic in `extract_policies.py`. Nothing leaves the
machine: PDFs are read locally, parsed with regex, and an Excel file is written
to a local path you choose. Serves the prebuilt React UI from ./frontend/dist.

Run:
    python app.py
Then open http://127.0.0.1:5000 in your browser.
"""

import os
import io
import glob
import tempfile

from flask import Flask, request, jsonify, send_from_directory, send_file
import pandas as pd

from extract_policies import read_text, extract_fields

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "frontend", "dist")

# Column order shown in the UI / written to Excel.
COLUMNS = [
    "Party Name",
    "Insurance Company",
    "Reg Number",
    "Type of Insurance",
    "Premium without GST",
    "Premium with GST",
    "Date Start",
    "End Date",
    "NCB (applied this yr)",
    "NCB (prev policy)",
    "Source File",
]

app = Flask(__name__, static_folder=None)


# ----------------------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    if os.path.exists(os.path.join(DIST_DIR, "index.html")):
        return send_from_directory(DIST_DIR, "index.html")
    return (
        "<h2>Frontend not built yet.</h2>"
        "<p>Run <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code> "
        "then restart this server.</p>",
        200,
    )


@app.route("/<path:path>")
def static_proxy(path):
    full = os.path.join(DIST_DIR, path)
    if os.path.exists(full):
        return send_from_directory(DIST_DIR, path)
    # SPA fallback
    return send_from_directory(DIST_DIR, "index.html")


# ----------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------
@app.route("/api/scan", methods=["POST"])
def scan():
    """List the PDFs found in a local folder path."""
    data = request.get_json(force=True) or {}
    folder = (data.get("folder") or "").strip()
    folder = os.path.expanduser(folder)
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": f"Not a folder: {folder}"}), 400
    pdfs = sorted(glob.glob(os.path.join(folder, "*.pdf")))
    files = [{"name": os.path.basename(p), "path": p} for p in pdfs]
    return jsonify({"files": files})


def _extract_one(path):
    row = extract_fields(read_text(path))
    row["Source File"] = os.path.basename(path)
    return row


@app.route("/api/extract", methods=["POST"])
def extract():
    """
    Extract fields from one PDF.

    Accepts either JSON {"path": "/abs/path.pdf"} for files already on disk,
    or a multipart upload (field name "file") for drag-and-dropped files.
    Processing one file per request lets the UI show live per-file progress.
    """
    # multipart upload (drag & drop)
    if "file" in request.files:
        f = request.files["file"]
        name = f.filename or "uploaded.pdf"
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            f.save(tmp.name)
            tmp_path = tmp.name
        try:
            row = extract_fields(read_text(tmp_path))
            row["Source File"] = name
            return jsonify({"row": row})
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": str(e), "source": name}), 500
        finally:
            os.unlink(tmp_path)

    # path on disk (folder scan)
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path or not os.path.isfile(path):
        return jsonify({"error": f"Not a file: {path}"}), 400
    try:
        return jsonify({"row": _extract_one(path)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e), "source": os.path.basename(path)}), 500


@app.route("/api/export", methods=["POST"])
def export():
    """
    Write the (possibly edited) rows to an Excel file.

    If `output_path` is given, save there and return the path. Otherwise stream
    the .xlsx back to the browser as a download.
    """
    data = request.get_json(force=True) or {}
    rows = data.get("rows") or []
    output_path = (data.get("output_path") or "").strip()
    if not rows:
        return jsonify({"error": "No rows to export."}), 400

    cols = [c for c in COLUMNS if any(c in r for r in rows)] or COLUMNS
    df = pd.DataFrame(rows)
    df = df.reindex(columns=cols)

    if output_path:
        output_path = os.path.expanduser(output_path)
        if not output_path.lower().endswith(".xlsx"):
            output_path += ".xlsx"
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        df.to_excel(output_path, index=False)
        return jsonify({"saved": output_path, "rows": len(df)})

    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="policies.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    print("Insurance PDF extractor running at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
