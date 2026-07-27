"""
Local Flask backend for the insurance-policy PDF extractor.

Reuses the offline extraction logic in `extract_policies.py`. Nothing leaves the
machine: PDFs are read locally, parsed with regex, and an Excel file is written
to a local path you choose. Serves the prebuilt React UI from ./frontend/dist.

Run:
    python app.py
Then open http://127.0.0.1:5001 in your browser.
"""

# Deferred annotation evaluation — required so this module still imports under
# Python 3.8 (the Windows build target for Windows 7 support). Without it,
# `X | None` and `list[...]`/`dict[...]`/`tuple[...]` type hints below raise
# TypeError at import time on 3.8 (PEP 604 unions and builtin generic
# subscripting are 3.10+/3.9+ features). Safe on any Python version since
# nothing in this module calls typing.get_type_hints() at runtime.
from __future__ import annotations

import os
import io
import sys
import glob
import json
import uuid
import queue
import atexit
import shutil
import logging
import tempfile
import threading
import time
import subprocess
import collections
from functools import lru_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── In-memory log buffer + SSE fan-out ──────────────────────────────────────
_log_buffer: collections.deque = collections.deque(maxlen=200)
_log_subscribers: list[queue.Queue] = []
_log_lock = threading.Lock()


class _UILogHandler(logging.Handler):
    def emit(self, record):
        line = self.format(record)
        with _log_lock:
            _log_buffer.append(line)
            for q in _log_subscribers:
                try:
                    q.put_nowait(line)
                except queue.Full:
                    pass


_ui_handler = _UILogHandler()
_ui_handler.setFormatter(
    logging.Formatter("%(name)s: %(message)s")
)
logging.getLogger().addHandler(_ui_handler)
logger = logging.getLogger(__name__)
# ────────────────────────────────────────────────────────────────────────────

from flask import Flask, request, jsonify, send_from_directory, send_file, Response, stream_with_context
from werkzeug.utils import safe_join
import pandas as pd

import pypdfium2 as pdfium
from PIL import Image, ImageDraw

from extract_policies import (
    read_document,
    extract_fields_gemini,
    extract_fields_gemini_vision,
    locate_fields,
    _is_text_poor,
    _LLM_FIELDS,
    gemini_status,
)

# When frozen by PyInstaller, bundled data lives under sys._MEIPASS. In a normal
# source checkout it lives next to this file.
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(BASE_DIR, "frontend", "dist")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# Column order shown in the UI / written to Excel.
COLUMNS = [
    "Party Name",
    "Insurance Company",
    "Policy No.",
    "Reg Number",
    "Type of Insurance",
    "Premium (Without GST)",
    "Premium",
    "Date Start",
    "End Date",
    "NCB (applied this yr)",
    "Source File",
]

# ── PDF preview cache ───────────────────────────────────────────────────────
# To render hover previews we must keep the source PDFs reachable for the life
# of the process. Uploaded files are copied into this temp dir; folder-scanned
# files are referenced in place. A doc_id keeps real paths out of the URL/API.
_DOC_DIR = tempfile.mkdtemp(prefix="pdfxl_docs_")
_DOC_REGISTRY: dict[str, str] = {}
_DOC_LOCK = threading.Lock()
# Cap the registry so a long-running session can't accumulate unbounded
# uploaded-PDF copies; evicting the oldest just disables its hover preview.
_MAX_DOCS = 500
# Don't leave copies of uploaded PDFs behind when the app closes.
atexit.register(lambda: shutil.rmtree(_DOC_DIR, ignore_errors=True))

# Preview render settings (PDF points → pixels).
_PREVIEW_SCALE = 3.0   # render resolution
_PREVIEW_PAD_X = 70    # context kept left/right of the value, in points
_PREVIEW_PAD_Y = 26    # context kept above/below the value, in points


def _register_doc(src_path: str, copy: bool) -> str:
    """Register a PDF for later preview and return its doc_id."""
    doc_id = uuid.uuid4().hex
    if copy:
        dst = os.path.join(_DOC_DIR, doc_id + ".pdf")
        shutil.copyfile(src_path, dst)
        path = dst
    else:
        path = os.path.abspath(src_path)
    with _DOC_LOCK:
        _DOC_REGISTRY[doc_id] = path
        while len(_DOC_REGISTRY) > _MAX_DOCS:
            old_id = next(iter(_DOC_REGISTRY))
            old_path = _DOC_REGISTRY.pop(old_id)
            if old_path.startswith(_DOC_DIR):
                try:
                    os.unlink(old_path)
                except OSError:
                    pass
    return doc_id


def _augment_row(row: dict, pdf_path: str, copy: bool, pages_words=None, locations=None) -> dict:
    """Attach a doc_id and per-field source locations for the hover preview."""
    doc_id = _register_doc(pdf_path, copy=copy)
    if locations is None:
        try:
            locations = locate_fields(pdf_path, row, pages_words=pages_words)
        except Exception as exc:  # noqa: BLE001 — preview is best-effort
            logger.warning("Field location failed for %s: %s", row.get("Source File"), exc)
            locations = {}
    row["_doc_id"] = doc_id
    row["_locations"] = locations
    return row


# ── API-key storage ──────────────────────────────────────────────────────────
# The env var wins; otherwise a key saved from the UI lives in a plain JSON
# config file in the user's home directory.
_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".pdfxl_config.json")
_CONFIG_LOCK = threading.Lock()


def _config_read() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def _config_write_key(config_key: str, key: str | None) -> None:
    """Set (or drop, when None/empty) one entry in the config file."""
    with _CONFIG_LOCK:
        cfg = _config_read()
        if key:
            cfg[config_key] = key
        else:
            cfg.pop(config_key, None)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)


# ── Gemini API key ──────────────────────────────────────────────────────────
def _load_saved_gemini_key() -> str:
    return str(_config_read().get("gemini_api_key") or "")


def _save_gemini_key(key: str) -> None:
    _config_write_key("gemini_api_key", key)


def _gemini_key() -> str:
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or _load_saved_gemini_key()
    )


def _gemini_key_info() -> dict:
    """Describe the configured key for the settings UI (never the key itself)."""
    env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    key = env_key or _load_saved_gemini_key()
    if not key:
        return {"key_set": False, "masked": "", "source": ""}
    masked = key[:4] + "…" + key[-4:] if len(key) > 12 else "•••"
    return {"key_set": True, "masked": masked, "source": "env" if env_key else "saved"}


@lru_cache(maxsize=8)
def _render_page(doc_id: str, page_no: int) -> Image.Image:
    """Render a full PDF page to a PIL image (cached; treat result as read-only)."""
    with _DOC_LOCK:
        path = _DOC_REGISTRY.get(doc_id)
    if not path:
        raise KeyError(doc_id)
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[page_no]
        if hasattr(page, "render_topil"):
            return page.render_topil(scale=_PREVIEW_SCALE).convert("RGB")
        else:
            return page.render(scale=_PREVIEW_SCALE).to_pil().convert("RGB")
    finally:
        pdf.close()


def _render_crop(doc_id: str, page_no: int, bbox) -> bytes:
    """Return PNG bytes of a zoomed, highlighted crop around bbox (PDF points)."""
    x0, top, x1, bottom = bbox
    page = _render_page(doc_id, page_no)
    s = _PREVIEW_SCALE
    cx0 = max(0, int((x0 - _PREVIEW_PAD_X) * s))
    cy0 = max(0, int((top - _PREVIEW_PAD_Y) * s))
    cx1 = min(page.width, int((x1 + _PREVIEW_PAD_X) * s))
    cy1 = min(page.height, int((bottom + _PREVIEW_PAD_Y) * s))
    crop = page.crop((cx0, cy0, cx1, cy1)).convert("RGBA")

    overlay = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle(
        [x0 * s - cx0 - 2, top * s - cy0 - 2, x1 * s - cx0 + 2, bottom * s - cy0 + 2],
        fill=(255, 214, 0, 70),
        outline=(240, 150, 0, 255),
        width=2,
    )
    out = Image.alpha_composite(crop, overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "PNG")
    buf.seek(0)
    return buf.getvalue()
# ────────────────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=None)
# Reject pathological uploads before they hit the disk; policy PDFs are small.
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB


@app.errorhandler(413)
def _too_large(e):
    return jsonify({"error": "File too large (limit is 100 MB)."}), 413


# ----------------------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------------------
@app.route("/app-icon.png")
def serve_icon():
    return send_from_directory(ASSETS_DIR, "icon.png")


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
    # safe_join refuses traversal outside DIST_DIR (returns None).
    full = safe_join(DIST_DIR, path)
    if full and os.path.isfile(full):
        return send_from_directory(DIST_DIR, path)
    # SPA fallback
    return send_from_directory(DIST_DIR, "index.html")


# ----------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------
@app.route("/api/scan", methods=["POST"])
def scan():
    """List the PDFs found in a local folder path."""
    data = request.get_json(silent=True) or {}
    folder = (data.get("folder") or "").strip()
    folder = os.path.expanduser(folder)
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": f"Not a folder: {folder}"}), 400
    # Case-insensitive: schedules arrive as both "x.pdf" and "x.PDF".
    pdfs = sorted(
        p for p in glob.glob(os.path.join(folder, "*")) if p.lower().endswith(".pdf")
    )
    files = [{"name": os.path.basename(p), "path": p} for p in pdfs]
    return jsonify({"files": files})


def _do_extract(path: str, text: str, model: str) -> dict:
    if not model:
        model = "gemini-2.5-flash"
    key = _gemini_key()
    name = os.path.basename(path)
    # Gemini models are all multimodal, so route on the text layer alone:
    # good text goes as a (cheap, fast) text prompt, a poor/scanned layer
    # sends the PDF itself.
    if not _is_text_poor(text):
        row = extract_fields_gemini(text, model, key)
        if any(row.get(k) for k in _LLM_FIELDS):
            return row
        logger.warning(
            "Gemini text extraction found no fields for %s; retrying with "
            "the PDF itself", name,
        )
    return extract_fields_gemini_vision(path, model, key)


def _extract_one(path, model=""):
    text, pages_words = read_document(path)
    row = _do_extract(path, text, model)
    row["Source File"] = os.path.basename(path)
    return _augment_row(row, path, copy=False, pages_words=pages_words)


@app.route("/api/gemini/status", methods=["GET"])
def api_gemini_status():
    """Return Gemini availability (key configured + valid) and usable models."""
    key = _gemini_key()
    status = gemini_status(key)
    status["key_set"] = bool(key)
    return jsonify(status)


@app.route("/api/gemini/key", methods=["GET", "POST", "DELETE"])
def api_gemini_key():
    """Manage the locally stored Gemini API key (settings UI).

    GET    → masked description of the configured key (never the key itself).
    POST   → validate {"api_key": ...} against Google and save it.
    DELETE → forget the saved key (an env-var key cannot be removed from here).
    """
    if request.method == "GET":
        return jsonify(_gemini_key_info())

    if request.method == "DELETE":
        try:
            _save_gemini_key("")
        except OSError as e:
            return jsonify({"ok": False, "error": f"Could not update config: {e}"}), 500
        return jsonify({"ok": True, **_gemini_key_info()})

    data = request.get_json(silent=True) or {}
    key = (data.get("api_key") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "Empty API key"}), 400
    status = gemini_status(key)  # listing models doubles as key validation
    if not status.get("ok"):
        status.update(_gemini_key_info())
        return jsonify(status), 400
    try:
        _save_gemini_key(key)
    except OSError as e:
        return jsonify({"ok": False, "error": f"Could not save key: {e}"}), 500
    status.update(_gemini_key_info())
    return jsonify(status)


@app.route("/api/extract", methods=["POST"])
def extract():
    """
    Extract fields from one PDF.

    Accepts either a multipart upload (field name "file") for drag-and-dropped
    files, or JSON {"path": "/abs/path.pdf"} for files already on disk.
    Optional fields: "model" (model name).
    """
    # multipart upload (drag & drop)
    if "file" in request.files:
        f = request.files["file"]
        name = f.filename or "uploaded.pdf"
        model = request.form.get("model", "")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            # Save through the open handle (re-opening by name breaks on Windows).
            f.save(tmp)
            tmp_path = tmp.name
        try:
            text, pages_words = read_document(tmp_path)
            row = _do_extract(tmp_path, text, model)
            row["Source File"] = name
            # copy=True keeps a copy alive for previews after the temp is removed
            return jsonify({"row": _augment_row(row, tmp_path, copy=True, pages_words=pages_words)})
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": str(e), "source": name}), 500
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # path on disk (folder scan)
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    model = data.get("model", "")
    if not path or not os.path.isfile(path):
        return jsonify({"error": f"Not a file: {path}"}), 400
    try:
        return jsonify({"row": _extract_one(path, model)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e), "source": os.path.basename(path)}), 500


@app.route("/api/preview", methods=["GET"])
def preview():
    """Render a zoomed, highlighted crop of the source PDF for one field.

    Query params: doc_id, page, x0, top, x1, bottom (the located bounding box).
    Returns a PNG so the UI can show it in a hover popover for verification.
    """
    doc_id = request.args.get("doc_id", "")
    with _DOC_LOCK:
        path = _DOC_REGISTRY.get(doc_id)
    if not path or not os.path.isfile(path):
        return jsonify({"error": "Unknown document."}), 404
    try:
        page_no = int(request.args.get("page", "0"))
        bbox = (
            float(request.args["x0"]),
            float(request.args["top"]),
            float(request.args["x1"]),
            float(request.args["bottom"]),
        )
    except (KeyError, ValueError):
        return jsonify({"error": "Bad preview parameters."}), 400
    if page_no < 0 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return jsonify({"error": "Bad preview parameters."}), 400
    try:
        png = _render_crop(doc_id, page_no, bbox)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500
    return send_file(io.BytesIO(png), mimetype="image/png")


@app.route("/api/open-pdf", methods=["GET"])
def open_pdf():
    """Serve the full PDF file for viewing/downloading.

    Query param: doc_id
    Returns the PDF file so the browser can display or download it.
    """
    doc_id = request.args.get("doc_id", "")
    with _DOC_LOCK:
        path = _DOC_REGISTRY.get(doc_id)
    if not path or not os.path.isfile(path):
        return jsonify({"error": "Unknown document."}), 404
    try:
        # Get the filename for the download/save-as suggestion
        filename = os.path.basename(path)
        return send_file(
            path,
            mimetype="application/pdf",
            as_attachment=False,  # Display inline in browser if possible
            download_name=filename
        )
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@app.route("/api/export", methods=["POST"])
def export():
    """
    Write the (possibly edited) rows to an Excel file.

    If `output_path` is given, save there and return the path. Otherwise stream
    the .xlsx back to the browser as a download.
    """
    data = request.get_json(silent=True) or {}
    rows = data.get("rows") or []
    output_path = (data.get("output_path") or "").strip()
    if not rows or not all(isinstance(r, dict) for r in rows):
        return jsonify({"error": "No rows to export."}), 400

    cols = [c for c in COLUMNS if any(c in r for r in rows)] or COLUMNS
    df = pd.DataFrame(rows)
    df = df.reindex(columns=cols)

    if output_path:
        output_path = os.path.expanduser(output_path)
        if not output_path.lower().endswith(".xlsx"):
            output_path += ".xlsx"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            df.to_excel(output_path, index=False)
        except Exception as e:  # noqa: BLE001 — surface disk/permission errors as JSON
            return jsonify({"error": f"Could not save {output_path}: {e}"}), 500
        return jsonify({"saved": output_path, "rows": len(df)})

    buf = io.BytesIO()
    try:
        df.to_excel(buf, index=False)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Could not build Excel file: {e}"}), 500
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="policies.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/logs")
def stream_logs():
    """SSE endpoint — streams log lines to the UI."""
    def generate():
        with _log_lock:
            buffered = list(_log_buffer)
            q: queue.Queue = queue.Queue(maxsize=200)
            _log_subscribers.append(q)
        def _sse(line: str) -> str:
            # Multi-line messages must use repeated "data:" prefixes per SSE spec.
            return "data: " + line.replace("\n", "\ndata: ") + "\n\n"

        try:
            for line in buffered:
                yield _sse(line)
            while True:
                try:
                    line = q.get(timeout=30)
                    yield _sse(line)
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _log_lock:
                try:
                    _log_subscribers.remove(q)
                except ValueError:
                    pass

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/pick_output", methods=["POST"])
def pick_output():
    """Open a native save-file dialog and return the chosen path."""
    script = (
        'tell application "Finder"\n'
        '  set f to choose file name with prompt "Save Excel file as:" '
        'default name "policies.xlsx"\n'
        '  return POSIX path of f\n'
        'end tell'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            return jsonify({"path": result.stdout.strip()})
        return jsonify({"cancelled": True})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    url = "http://127.0.0.1:5001"
    print(f"Insurance PDF extractor running at {url}")
    print("Open that URL in your browser. (Ctrl+C here to stop the server)")
    try:
        app.run(host="127.0.0.1", port=5001, threaded=True, debug=False, use_reloader=False)
    except OSError as e:
        print(f"Could not start on 127.0.0.1:5001 ({e}). Is the app already running?")
        sys.exit(1)
