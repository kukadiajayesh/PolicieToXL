"""
Offline insurance-policy PDF field extractor.

Drop your PDFs into a folder, run this script, and it writes one row per
policy to an Excel file. Everything runs locally — no internet, no upload.

Usage:
    python extract_policies.py /path/to/folder_of_pdfs   output.xlsx
"""

# Deferred annotation evaluation — required so this module still imports under
# Python 3.8 (the Windows build target for Windows 7 support). Without it,
# `X | None` and `list[...]`/`dict[...]`/`tuple[...]` type hints below raise
# TypeError at import time on 3.8 (PEP 604 unions and builtin generic
# subscripting are 3.10+/3.9+ features). Safe on any Python version since
# nothing in this module calls typing.get_type_hints() at runtime.
from __future__ import annotations

import sys
import re
import os
import glob
import json
import base64
import logging
import pdfplumber
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

def _env_int(name: str, default: int) -> int:
    """Read an int from the environment, falling back to default on anything invalid."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Below this many characters we consider the text layer "poor" and try vision.
_MIN_TEXT_CHARS = 200

# ── Gemini (Google AI) ──────────────────────────────────────────────────────
# Needs an API key (GEMINI_API_KEY / GOOGLE_API_KEY env var, or one saved from
# the UI). Text sent here leaves the machine — the UI calls that out when the
# engine is selected.
GEMINI_API_URL = (
    os.environ.get("GEMINI_API_URL") or "https://generativelanguage.googleapis.com/v1beta"
).rstrip("/")
_GEMINI_TIMEOUT = _env_int("GEMINI_TIMEOUT", 120)
_GEMINI_STATUS_TIMEOUT = _env_int("GEMINI_STATUS_TIMEOUT", 10)
# Gemini's context is huge compared to local models, so allow far more text.
_GEMINI_MAX_CHARS = _env_int("GEMINI_MAX_CHARS", 30000)
# generateContent rejects inline payloads over ~20 MB; larger PDFs fall back
# to rendered page images.
_GEMINI_MAX_PDF_BYTES = 20 * 1024 * 1024
_GEMINI_VISION_MAX_PAGES = 2

_EXTRACT_PROMPT = """\
You are an insurance document parser. Extract the following fields from the \
policy document text below and return ONLY a valid JSON object — no markdown, \
no explanation, just the JSON.

Required keys (use "" if not found):
  "Party Name"          – full name of the insured person or entity
  "Insurance Company"   – full legal name of the insurer
  "Policy No."          – policy number / ID
  "Reg Number"          – vehicle registration number exactly as printed in the document
  "Type of Insurance"   – policy type (e.g. Comprehensive, Third Party, etc.)
  "Premium (Without GST)" – net/base premium before GST, digits only (no ₹ or commas)
  "Premium"             – total premium including GST, digits only (no ₹ or commas)
  "Date Start"          – policy start date in DD/MM/YYYY
  "End Date"            – policy end date in DD/MM/YYYY
  "NCB (applied this yr)" – no-claim bonus % applied this year (e.g. "25%")

Copy values exactly as they appear in the text. If a field is not present, use "" — \
never guess or invent a value.

Document text:
{text}
"""

_VISION_PROMPT = """\
You are an insurance document parser. Look at this insurance policy document \
image and extract the following fields. Return ONLY a valid JSON object — no \
markdown, no explanation, just the JSON.

Required keys (use "" if not found):
  "Party Name"          – full name of the insured person or entity
  "Insurance Company"   – full legal name of the insurer
  "Policy No."          – policy number / ID
  "Reg Number"          – vehicle registration number
  "Type of Insurance"   – policy type as printed on the document
  "Premium (Without GST)" – net/base premium before GST, digits only (no currency symbol or commas)
  "Premium"             – total premium including GST, digits only (no currency symbol or commas)
  "Date Start"          – policy start date in DD/MM/YYYY
  "End Date"            – policy end date in DD/MM/YYYY
  "NCB (applied this yr)" – no-claim bonus percentage applied this year

Copy values exactly as printed in the image. If you cannot clearly read a \
field, use "" — never guess or invent a value.
"""


def _is_text_poor(text: str) -> bool:
    """Return True when pdfplumber extracted too little text to be useful."""
    return len(text.strip()) < _MIN_TEXT_CHARS


# Canonical field order for an extracted policy row (excludes the Source File,
# which the caller fills in). Shared by the regex and LLM extraction paths.
_LLM_FIELDS = (
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
)


def _parse_llm_json(raw: str) -> dict:
    """Best-effort parse of an LLM response into a dict.

    Even with ``"format": "json"`` a model can wrap its answer in markdown fences
    or add stray prose, so we strip fences and fall back to the first ``{...}``
    block. Returns ``{}`` (never raises) when nothing parseable is found, and
    drops any non-object payload (lists, strings, numbers).
    """
    if not raw or not raw.strip():
        return {}
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            logger.warning("Could not locate JSON in LLM response")
            return {}
        try:
            data = json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            logger.warning("LLM response was not valid JSON")
            return {}
    return data if isinstance(data, dict) else {}


def _normalize_llm_fields(fields: dict) -> dict:
    """Coerce a raw LLM dict into the canonical row: every key present, clean strings."""
    row = {}
    for key in _LLM_FIELDS:
        val = fields.get(key, "")
        row[key] = "" if val is None else str(val).strip()
    row["Source File"] = ""  # filled in by caller
    return row


def pdf_pages_to_b64(pdf_path: str, max_pages: int | None = None) -> list[str]:
    """Render PDF pages to base64-encoded PNGs (requires pypdfium2).

    ``max_pages`` caps how many leading pages are rendered so a long document
    can't balloon the vision request payload or blow the timeout.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise RuntimeError(
            "pypdfium2 is required for vision extraction. Install it with: pip install pypdfium2"
        )
    import io

    try:
        doc = pdfium.PdfDocument(pdf_path)
    except Exception as exc:
        raise RuntimeError(
            f"Could not open {os.path.basename(pdf_path)} for rendering: {exc}"
        ) from exc
    try:
        n_pages = len(doc) if max_pages is None else min(len(doc), max_pages)
        images = []
        for i in range(n_pages):
            try:
                page = doc[i]
                if hasattr(page, "render_topil"):
                    pil = page.render_topil(scale=2.0)
                else:
                    pil = page.render(scale=2.0).to_pil()  # 2× zoom ≈ 144 dpi
            except Exception as exc:
                # One corrupt page shouldn't sink the whole vision request.
                logger.warning(
                    "Skipping unrenderable page %d of %s: %s",
                    i + 1, os.path.basename(pdf_path), exc,
                )
                continue
            buf = io.BytesIO()
            # JPEG encodes several times faster than PNG and keeps the base64
            # payload (and the model's image-ingest time) much smaller; quality
            # 90 keeps document text crisp.
            pil.convert("RGB").save(buf, format="JPEG", quality=90)
            images.append(base64.b64encode(buf.getvalue()).decode())
    finally:
        doc.close()
    return images


def read_document(pdf_path: str, want_words: bool = True) -> tuple[str, list[list[dict]]]:
    """Parse a PDF once, returning (full_text, per-page word lists).

    The expensive step in pdfplumber is the per-page pdfminer layout parse.
    Extracting the text and the word boxes from the same open document does
    that parse once, where separate read_text() + locate_fields() calls used
    to do it twice — roughly halving the time to process each PDF.
    """
    chunks: list[str] = []
    pages_words: list[list[dict]] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                chunks.append(page.extract_text() or "")
                if want_words:
                    pages_words.append(page.extract_words())
                # Parsed page objects are large; drop each page's cache as we
                # go so a long PDF doesn't hold every page in memory at once.
                page.flush_cache()
    except Exception as exc:
        hint = ""
        if "password" in str(exc).lower() or "decrypt" in str(exc).lower():
            hint = " — the PDF appears to be password-protected"
        raise RuntimeError(
            f"Could not read {os.path.basename(pdf_path)}: {exc}{hint}"
        ) from exc
    # collapse whitespace so regexes are easier to write
    return re.sub(r"[ \t]+", " ", "\n".join(chunks)), pages_words


def read_text(pdf_path: str) -> str:
    """Extract the full text layer from a PDF."""
    return read_document(pdf_path, want_words=False)[0]


def _gemini_generate(parts: list[dict], model: str, api_key: str, timeout: int = _GEMINI_TIMEOUT) -> dict:
    """POST to Gemini's generateContent and return a normalized field dict.

    Every failure mode (bad key, unknown model, rate limit, network trouble,
    malformed body) becomes a RuntimeError with a message the UI can show as-is.
    """
    if not _REQUESTS_OK:
        raise RuntimeError("requests library is required for Gemini extraction")
    if not api_key:
        raise RuntimeError(
            "No Gemini API key configured. Set GEMINI_API_KEY or save a key from the UI."
        )
    if not model:
        raise ValueError("No Gemini model specified")
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    url = f"{GEMINI_API_URL}/models/{model}:generateContent"
    try:
        r = _requests.post(
            url, json=payload, headers={"x-goog-api-key": api_key}, timeout=timeout
        )
        r.raise_for_status()
    except _requests.exceptions.ConnectionError:
        raise RuntimeError("Cannot reach the Gemini API. Check your internet connection.")
    except _requests.exceptions.Timeout:
        raise RuntimeError(f"Gemini did not respond within {timeout}s.")
    except _requests.exceptions.HTTPError as exc:
        detail = ""
        try:
            detail = r.json().get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            detail = (r.text or "").strip()[:200]
        if r.status_code in (401, 403):
            raise RuntimeError(f"Gemini rejected the API key: {detail or exc}")
        if r.status_code == 404:
            raise RuntimeError(f"Unknown Gemini model '{model}': {detail or exc}")
        if r.status_code == 429:
            raise RuntimeError(f"Gemini rate limit hit — wait a moment and retry: {detail or exc}")
        raise RuntimeError(f"Gemini request failed: {detail or exc}")
    except _requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Gemini request failed: {exc}")

    try:
        body = r.json()
    except ValueError:
        raise RuntimeError("Gemini returned a non-JSON response.")

    try:
        resp_parts = body["candidates"][0]["content"]["parts"]
        raw = "".join(p.get("text", "") for p in resp_parts)
    except (KeyError, IndexError, TypeError):
        # A blocked prompt has promptFeedback instead of candidates.
        reason = (body.get("promptFeedback") or {}).get("blockReason", "")
        raise RuntimeError(
            f"Gemini returned no answer{f' (blocked: {reason})' if reason else ''}."
        )
    logger.info("=== Gemini response ===\n%s", raw)
    return _normalize_llm_fields(_parse_llm_json(raw))


def extract_fields_gemini(text: str, model: str, api_key: str) -> dict:
    """Ask a Gemini model to extract policy fields from the PDF's text layer."""
    prompt = _EXTRACT_PROMPT.format(text=(text or "")[:_GEMINI_MAX_CHARS])
    logger.info("=== Gemini text extraction -> %s ===", model)
    return _gemini_generate([{"text": prompt}], model, api_key)


def extract_fields_gemini_vision(pdf_path: str, model: str, api_key: str) -> dict:
    """Use Gemini's multimodal input to extract fields from the PDF itself.

    Gemini reads PDFs natively, so we send the raw file (better fidelity than
    rendered screenshots). Oversized files fall back to rendered page images
    (capped at _GEMINI_VISION_MAX_PAGES pages).
    """
    try:
        size = os.path.getsize(pdf_path)
    except OSError as exc:
        raise RuntimeError(f"Could not read {os.path.basename(pdf_path)}: {exc}") from exc

    parts: list[dict] = [{"text": _VISION_PROMPT}]
    if size <= _GEMINI_MAX_PDF_BYTES:
        with open(pdf_path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        parts.append({"inline_data": {"mime_type": "application/pdf", "data": data}})
        logger.info("=== Gemini vision: whole PDF (%.1f KB) -> %s ===", size / 1024, model)
    else:
        images = pdf_pages_to_b64(pdf_path, max_pages=_GEMINI_VISION_MAX_PAGES)
        if not images:
            raise RuntimeError("No pages could be rendered from the PDF for vision extraction")
        parts.extend(
            {"inline_data": {"mime_type": "image/jpeg", "data": img}} for img in images
        )
        logger.info("=== Gemini vision: %d page image(s) -> %s ===", len(images), model)
    return _gemini_generate(parts, model, api_key)


# Google's models endpoint still lists retired generations (e.g. gemini-2.0-*
# now hard-404s with "no longer available") and specialty models that can't do
# JSON field extraction. Keep the UI list to models that actually work.
_GEMINI_MIN_VERSION = 2.5  # everything older is retired as of mid-2026
_GEMINI_NON_TEXT = ("tts", "image", "robotics", "computer-use", "lyria", "omni")


def _gemini_usable(name: str) -> bool:
    """True when a listed Gemini model can serve text→JSON extraction."""
    ln = name.lower()
    if any(x in ln for x in _GEMINI_NON_TEXT):
        return False
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", ln)
    # Versionless aliases (gemini-flash-latest, gemini-pro-latest) are always
    # current, so keep them.
    return m is None or float(m.group(1)) >= _GEMINI_MIN_VERSION


def _recommended_gemini(names: list[str]) -> str:
    """Pick the model to tag as "Recommended": gemini-flash-latest or the highest versioned flash.

    Every Gemini model is multimodal, so flash is the sweet spot for field
    extraction — it reads both text and page images accurately at a fraction
    of pro's cost/latency.
    """
    if "gemini-flash-latest" in names:
        return "gemini-flash-latest"
    best, best_ver = "", -1.0
    for n in names:
        m = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", n)
        if m and float(m.group(1)) > best_ver:
            best, best_ver = n, float(m.group(1))
    if best:
        return best
    if "gemini-2.5-flash" in names:
        return "gemini-2.5-flash"
    for n in names:
        ln = n.lower()
        if "flash" in ln and not any(
            x in ln for x in ("lite", "preview", "exp", "8b", "thinking")
        ):
            return n
    return names[0] if names else ""


def gemini_status(api_key: str) -> dict:
    """Return {"ok": True, "models": [...]} or {"ok": False, "error": "..."}.

    Also validates the key: a bad key fails the models list with a clear error.
    """
    if not _REQUESTS_OK:
        return {"ok": False, "error": "requests library not installed"}
    if not api_key:
        return {"ok": False, "error": "No API key configured"}
    try:
        r = _requests.get(
            f"{GEMINI_API_URL}/models",
            params={"pageSize": 100},
            headers={"x-goog-api-key": api_key},
            timeout=_GEMINI_STATUS_TIMEOUT,
        )
        if not r.ok:
            try:
                detail = r.json().get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                detail = ""
            return {"ok": False, "error": detail or f"HTTP {r.status_code}"}
        names = []
        for m in r.json().get("models", []):
            name = m.get("name") or ""
            if name.startswith("models/"):
                name = name[len("models/"):]
            if "gemini" not in name.lower():
                continue
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            if not _gemini_usable(name):
                continue
            names.append(name)

        import concurrent.futures
        def _works(n):
            try:
                res = _requests.post(
                    f"{GEMINI_API_URL}/models/{n}:generateContent",
                    json={"contents": [{"parts": [{"text": "1"}]}], "generationConfig": {"maxOutputTokens": 1}},
                    headers={"x-goog-api-key": api_key},
                    timeout=3.5,
                )
                return res.status_code not in (404, 503)
            except _requests.exceptions.RequestException:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            valid = list(ex.map(_works, names))

        names = [n for n, ok in zip(names, valid) if ok]

        # Flash models first — cheap and plenty for field extraction.
        names.sort(key=lambda n: ("flash" not in n, n))

        rec = _recommended_gemini(names)
        # Every current Gemini model is multimodal, hence vision: True.
        return {
            "ok": True,
            "models": [
                {"name": n, "vision": True, "recommended": n == rec} for n in names
            ],
        }
    except UnicodeEncodeError:
        return {"ok": False, "error": "API key contains invalid characters"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}





def _norm_token(s: str) -> str:
    """Lowercase and strip everything but alphanumerics (for fuzzy matching)."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def locate_fields(
    pdf_path: str, fields: dict, min_len: int = 3, pages_words: list[list[dict]] | None = None
) -> dict:
    """Find where each extracted field value sits on the page.

    For every non-empty value we normalise it (drop spaces/punctuation/case) and
    search the normalised stream of words on each page. The bounding box of the
    matching words is returned so the UI can render a zoomed, highlighted crop of
    the source PDF for verification.

    ``pages_words`` lets a caller that already parsed the document (see
    read_document) skip a second full parse of the PDF.

    Returns {field_name: {"page": int, "bbox": [x0, top, x1, bottom]}}; fields
    that can't be located (or are too short to match unambiguously) are omitted.
    Coordinates are in PDF points with a top-left origin (pdfplumber convention).
    """
    targets = {}
    for key, val in fields.items():
        if key == "Source File" or not val:
            continue
        norm = _norm_token(val)
        if len(norm) >= min_len:
            targets[key] = norm
    if not targets:
        return {}

    if pages_words is not None:
        return _locate_in_pages(pages_words, targets)
    with pdfplumber.open(pdf_path) as pdf:
        return _locate_in_pages((page.extract_words() for page in pdf.pages), targets)


def _locate_in_pages(pages_words, targets: dict) -> dict:
    """Match normalised target strings against per-page word lists."""
    found: dict = {}
    for page_no, words in enumerate(pages_words):
        if not words:
            continue
        # Concatenate all normalised words on the page, remembering which
        # character range each word occupies so we can map a match back to
        # the words (and therefore the bounding boxes) that produced it.
        concat = ""
        spans = []  # (start, end, word_index)
        for wi, w in enumerate(words):
            nw = _norm_token(w["text"])
            if not nw:
                continue
            start = len(concat)
            concat += nw
            spans.append((start, len(concat), wi))

        for key, norm in targets.items():
            if key in found:
                continue
            pos = concat.find(norm)
            if pos < 0:
                continue
            end = pos + len(norm)
            hits = [wi for (s, e, wi) in spans if s < end and e > pos]
            if not hits:
                continue
            found[key] = {
                "page": page_no,
                "bbox": [
                    min(words[i]["x0"] for i in hits),
                    min(words[i]["top"] for i in hits),
                    max(words[i]["x1"] for i in hits),
                    max(words[i]["bottom"] for i in hits),
                ],
            }
        if len(found) == len(targets):
            break
    return found


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    out = sys.argv[2] if len(sys.argv) > 2 else "policies.xlsx"

    # Case-insensitive: schedules arrive as both "x.pdf" and "x.PDF".
    pdfs = sorted(
        p for p in glob.glob(os.path.join(folder, "*")) if p.lower().endswith(".pdf")
    )
    if not pdfs:
        print(f"No PDFs found in {folder}")
        return

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        print("ERR: GEMINI_API_KEY or GOOGLE_API_KEY environment variable is required.")
        sys.exit(1)

    rows = []
    for path in pdfs:
        try:
            text, _ = read_document(path)
            if not _is_text_poor(text):
                data = extract_fields_gemini(text, "gemini-2.5-flash", key)
            else:
                data = extract_fields_gemini_vision(path, "gemini-2.5-flash", key)
            data["Source File"] = os.path.basename(path)
            rows.append(data)
            print(f"OK  {os.path.basename(path)}")
        except Exception as e:
            print(f"ERR {os.path.basename(path)}: {e}")

    if not rows:
        print("No rows extracted; nothing to write.")
        sys.exit(1)

    df = pd.DataFrame(rows)
    try:
        df.to_excel(out, index=False)
    except Exception as e:
        print(f"ERR could not write {out}: {e}")
        sys.exit(1)
    print(f"\nWrote {len(rows)} rows -> {out}")
    # also print to screen so you can eyeball it
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
