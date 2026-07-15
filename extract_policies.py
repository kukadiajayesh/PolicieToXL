"""
Offline insurance-policy PDF field extractor.

Drop your PDFs into a folder, run this script, and it writes one row per
policy to an Excel file. Everything runs locally — no internet, no upload.

Usage:
    python extract_policies.py /path/to/folder_of_pdfs   output.xlsx
"""

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


def _normalize_ollama_url(raw: str) -> str:
    """Normalise an Ollama endpoint.

    Ollama's own OLLAMA_HOST convention allows a bare ``host:port`` (no scheme)
    and we want to tolerate a trailing slash, so coerce both into a clean base URL.
    """
    url = (raw or "").strip().rstrip("/")
    if not url:
        url = "http://localhost:11434"
    if not re.match(r"^https?://", url):
        url = "http://" + url
    return url


# Ollama base URL — honours the standard OLLAMA_HOST / OLLAMA_URL env vars so the
# server can live on another host or port.
OLLAMA_URL = _normalize_ollama_url(os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_URL"))
# Max characters of PDF text sent to the LLM (keeps prompts fast).
_OLLAMA_MAX_CHARS = 8000
# Below this many characters we consider the text layer "poor" and try vision.
_MIN_TEXT_CHARS = 200
# Network timeouts (seconds) and the vision page cap — all overridable via env.
_OLLAMA_TIMEOUT = _env_int("OLLAMA_TIMEOUT", 180)
_OLLAMA_VISION_TIMEOUT = _env_int("OLLAMA_VISION_TIMEOUT", 300)
_OLLAMA_STATUS_TIMEOUT = _env_int("OLLAMA_STATUS_TIMEOUT", 5)
# Each rendered page image costs ~700-800 tokens. Small vision models (moondream
# is 2048) reject requests that overflow their context, so cap pages low — the
# key policy fields sit on the first page(s) anyway. Bump via env for roomier
# models (llava, minicpm-v).
_OLLAMA_VISION_MAX_PAGES = _env_int("OLLAMA_VISION_MAX_PAGES", 2)

# ── Gemini (Google AI) ──────────────────────────────────────────────────────
# Cloud alternative to Ollama. Needs an API key (GEMINI_API_KEY / GOOGLE_API_KEY
# env var, or one saved from the UI). Unlike the local path, text sent here
# leaves the machine — the UI calls that out when the engine is selected.
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
            logger.warning("Could not locate JSON in Ollama response")
            return {}
        try:
            data = json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            logger.warning("Ollama response was not valid JSON")
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
                pil = doc[i].render(scale=2.0).to_pil()  # 2× zoom ≈ 144 dpi
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


def _ollama_generate(payload: dict, url: str, timeout: int) -> dict:
    """POST to Ollama's /api/generate and return a normalized field dict.

    Translates the noisy failure modes (server down, slow model, bad model name,
    HTML error page, malformed JSON) into clear ``RuntimeError`` messages so the
    UI can show something actionable instead of a raw stack trace.
    """
    if not _REQUESTS_OK:
        raise RuntimeError("requests library is required for Ollama extraction")
    try:
        r = _requests.post(f"{url}/api/generate", json=payload, timeout=timeout)
        r.raise_for_status()
    except _requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot reach Ollama at {url}. Is it running? Start it with `ollama serve`."
        )
    except _requests.exceptions.Timeout:
        raise RuntimeError(
            f"Ollama did not respond within {timeout}s. Try a smaller/faster model."
        )
    except _requests.exceptions.HTTPError as exc:
        detail = ""
        try:
            detail = r.json().get("error", "")
        except ValueError:
            detail = (r.text or "").strip()[:200]
        raise RuntimeError(f"Ollama request failed: {detail or exc}")
    except _requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Ollama request failed: {exc}")

    try:
        body = r.json()
    except ValueError:
        raise RuntimeError("Ollama returned a non-JSON response.")
    if isinstance(body, dict) and body.get("error"):
        raise RuntimeError(f"Ollama error: {body['error']}")

    raw = body.get("response", "") if isinstance(body, dict) else ""
    logger.info("=== Ollama response ===\n%s", raw)
    return _normalize_llm_fields(_parse_llm_json(raw))


def extract_fields_ollama_vision(pdf_path: str, model: str, url: str = OLLAMA_URL) -> dict:
    """Use a vision-capable Ollama model to extract fields directly from PDF images."""
    if not _REQUESTS_OK:
        raise RuntimeError("requests library is required for Ollama extraction")
    if not model:
        raise ValueError("No Ollama model specified")
    max_pages = _OLLAMA_VISION_MAX_PAGES
    if "moondream" in model.lower():
        # moondream was trained on a single image; a second one just crowds its
        # 2048-token context (each page ≈ 729 tokens) and degrades the answer.
        max_pages = 1
    images = pdf_pages_to_b64(pdf_path, max_pages=max_pages)
    if not images:
        raise RuntimeError("No pages could be rendered from the PDF for vision extraction")
    payload = {
        "model": model,
        "prompt": _VISION_PROMPT,
        "images": images,
        "stream": False,
        "format": "json",
    }
    logger.info("=== Ollama vision: %d page(s) -> %s ===", len(images), model)
    return _ollama_generate(payload, url, _OLLAMA_VISION_TIMEOUT)


# Fields whose values appear verbatim in the document. Dates, premium and NCB
# may be legitimately reformatted by the model (DD/MM/YYYY, digits only), so
# they can't be checked by substring match.
_ANCHOR_FIELDS = ("Party Name", "Insurance Company", "Policy No.", "Reg Number")


def vision_row_is_credible(row: dict, text: str) -> bool:
    """Cross-check a vision-extracted row against the PDF's text layer.

    Small vision models often can't actually read a dense policy page and then
    invent plausible-looking values (typically echoing the prompt's field
    descriptions). When the PDF has a usable text layer we can catch that:
    a credible row must have at least one verbatim anchor field that really
    occurs in the document text (compared with spacing/punctuation/case
    stripped, so line wraps and OCR-style spacing don't cause false negatives).
    """
    norm_text = _norm_token(text)
    anchors = [_norm_token(row.get(k, "")) for k in _ANCHOR_FIELDS]
    return any(a and a in norm_text for a in anchors)


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


def first(pattern, text, group=1, flags=re.IGNORECASE):
    """Return the first regex match (a stripped string) or '' if none.

    Defensive on purpose: a malformed pattern or a missing capture group returns
    '' (with a warning) rather than aborting extraction of every other field.
    """
    try:
        m = re.search(pattern, text, flags)
    except re.error:
        logger.warning("Skipping invalid regex pattern: %r", pattern)
        return ""
    if not m:
        return ""
    try:
        val = m.group(group)
    except (IndexError, re.error):
        return ""
    return val.strip() if val else ""


_VISION_KEYWORDS = ("llava", "bakllava", "moondream", "minicpm-v", "vision", "-vl")


def _is_vision_model(name: str) -> bool:
    lower = name.lower()
    return any(k in lower for k in _VISION_KEYWORDS)


# Installed-model preference for the "Recommended" tag, best first. The top
# entries read both the page image and plain text well; moondream is deliberately
# absent (too weak for dense policy pages). If no vision model is installed the
# strong text models follow, since regex/vision fallbacks cover scanned PDFs.
_OLLAMA_PREFERRED = ("minicpm-v", "llava", "bakllava", "qwen2.5", "llama3", "gemma", "mistral")


def _recommended_ollama(names: list[str]) -> str:
    for pref in _OLLAMA_PREFERRED:
        for n in names:
            if pref in n.lower():
                return n
    return names[0] if names else ""


def ollama_status(url: str = OLLAMA_URL) -> dict:
    """Return {"ok": True, "models": [...]} or {"ok": False, "error": "..."}."""
    if not _REQUESTS_OK:
        return {"ok": False, "error": "requests library not installed"}
    try:
        r = _requests.get(f"{url}/api/tags", timeout=_OLLAMA_STATUS_TIMEOUT)
        r.raise_for_status()
        all_models = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
        rec = _recommended_ollama(all_models)
        # Text models first so the UI default lands on a text model.
        models = sorted(
            [
                {"name": n, "vision": _is_vision_model(n), "recommended": n == rec}
                for n in all_models
            ],
            key=lambda m: m["vision"],
        )
        return {"ok": True, "models": models}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def extract_fields_ollama(text: str, model: str, url: str = OLLAMA_URL) -> dict:
    """Ask a local Ollama model to extract policy fields and return a dict."""
    if not _REQUESTS_OK:
        raise RuntimeError("requests library is required for Ollama extraction")
    if not model:
        raise ValueError("No Ollama model specified")
    prompt = _EXTRACT_PROMPT.format(text=(text or "")[:_OLLAMA_MAX_CHARS])
    logger.info("=== Ollama prompt ===\n%s", prompt)
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json"}
    return _ollama_generate(payload, url, _OLLAMA_TIMEOUT)


def _gemini_generate(parts: list[dict], model: str, api_key: str, timeout: int = _GEMINI_TIMEOUT) -> dict:
    """POST to Gemini's generateContent and return a normalized field dict.

    Same contract as _ollama_generate: every failure mode (bad key, unknown
    model, rate limit, network trouble, malformed body) becomes a RuntimeError
    with a message the UI can show as-is.
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
    rendered screenshots). Oversized files fall back to rendered page images,
    reusing the same cap as the Ollama vision path.
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
        images = pdf_pages_to_b64(pdf_path, max_pages=_OLLAMA_VISION_MAX_PAGES)
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
    """Pick the model to tag as "Recommended": the newest stable flash.

    Every Gemini model is multimodal, so flash is the sweet spot for field
    extraction — it reads both text and page images accurately at a fraction
    of pro's cost/latency. Prefer an exact stable "gemini-<ver>-flash" (newest
    version); otherwise any flash that isn't a lite/preview/experimental spin.
    """
    best, best_ver = "", -1.0
    for n in names:
        m = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", n)
        if m and float(m.group(1)) > best_ver:
            best, best_ver = n, float(m.group(1))
    if best:
        return best
    for n in names:
        ln = n.lower()
        if "flash" in ln and not any(
            x in ln for x in ("lite", "preview", "exp", "8b", "thinking")
        ):
            return n
    return names[0] if names else ""


def gemini_status(api_key: str) -> dict:
    """Return {"ok": True, "models": [...]} or {"ok": False, "error": "..."}.

    Mirrors ollama_status so the UI can treat both engines the same. Also
    validates the key: a bad key fails the models list with a clear error.
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
            name = (m.get("name") or "").removeprefix("models/")
            if "gemini" not in name.lower():
                continue
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            if not _gemini_usable(name):
                continue
            names.append(name)
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
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


try:
    import anthropic as _anthropic
    _ANTHROPIC_OK = True
except ImportError:
    _ANTHROPIC_OK = False

_ANTHROPIC_TIMEOUT = _env_int("ANTHROPIC_TIMEOUT", 120)
# Claude's context is huge compared to local models, so allow far more text.
_ANTHROPIC_MAX_CHARS = _env_int("ANTHROPIC_MAX_CHARS", 30000)
# The Messages API rejects inline PDF payloads over ~32MB; larger PDFs fall
# back to rendered page images, reusing the same cap as the other vision paths.
_ANTHROPIC_MAX_PDF_BYTES = 20 * 1024 * 1024

# Structured-outputs schema for the 9 policy fields — guarantees a valid JSON
# object back from Claude with no markdown fences or stray prose to strip.
_ANTHROPIC_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in _LLM_FIELDS},
    "required": list(_LLM_FIELDS),
    "additionalProperties": False,
}


def _anthropic_client(api_key: str):
    if not _ANTHROPIC_OK:
        raise RuntimeError(
            "anthropic package is required for Claude extraction. Install it with: pip install anthropic"
        )
    if not api_key:
        raise RuntimeError(
            "No Claude API key configured. Set ANTHROPIC_API_KEY or save a key from the UI."
        )
    return _anthropic.Anthropic(api_key=api_key, timeout=_ANTHROPIC_TIMEOUT)


def _anthropic_generate(content, model: str, api_key: str) -> dict:
    """Send one Messages API request and return a normalized field dict.

    Translates the noisy failure modes (bad key, unknown model, rate limit,
    network trouble, refusal) into clear RuntimeError messages, mirroring
    _ollama_generate/_gemini_generate so the UI can show them as-is.
    """
    if not model:
        raise ValueError("No Claude model specified")
    client = _anthropic_client(api_key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            output_config={"format": {"type": "json_schema", "schema": _ANTHROPIC_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
    except _anthropic.AuthenticationError:
        raise RuntimeError("Claude rejected the API key.")
    except _anthropic.NotFoundError as exc:
        raise RuntimeError(f"Unknown Claude model '{model}': {exc.message}")
    except _anthropic.RateLimitError as exc:
        raise RuntimeError(f"Claude rate limit hit — wait a moment and retry: {exc.message}")
    except _anthropic.APIConnectionError:
        raise RuntimeError("Cannot reach the Claude API. Check your internet connection.")
    except _anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude request failed: {exc.message}")

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to process this document.")
    raw = next((b.text for b in response.content if b.type == "text"), "")
    logger.info("=== Claude response ===\n%s", raw)
    return _normalize_llm_fields(_parse_llm_json(raw))


def extract_fields_claude(text: str, model: str, api_key: str) -> dict:
    """Ask a Claude model to extract policy fields from the PDF's text layer."""
    prompt = _EXTRACT_PROMPT.format(text=(text or "")[:_ANTHROPIC_MAX_CHARS])
    logger.info("=== Claude text extraction -> %s ===", model)
    return _anthropic_generate(prompt, model, api_key)


def extract_fields_claude_vision(pdf_path: str, model: str, api_key: str) -> dict:
    """Use Claude's native PDF input to extract fields from the document itself.

    Claude reads PDFs natively, so we send the raw file (better fidelity than
    rendered screenshots). Oversized files fall back to rendered page images,
    reusing the same cap as the Ollama/Gemini vision paths.
    """
    try:
        size = os.path.getsize(pdf_path)
    except OSError as exc:
        raise RuntimeError(f"Could not read {os.path.basename(pdf_path)}: {exc}") from exc

    content: list[dict] = []
    if size <= _ANTHROPIC_MAX_PDF_BYTES:
        with open(pdf_path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        content.append(
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
        )
        logger.info("=== Claude vision: whole PDF (%.1f KB) -> %s ===", size / 1024, model)
    else:
        images = pdf_pages_to_b64(pdf_path, max_pages=_OLLAMA_VISION_MAX_PAGES)
        if not images:
            raise RuntimeError("No pages could be rendered from the PDF for vision extraction")
        content.extend(
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img}}
            for img in images
        )
        logger.info("=== Claude vision: %d page image(s) -> %s ===", len(images), model)
    content.append({"type": "text", "text": _VISION_PROMPT})
    return _anthropic_generate(content, model, api_key)


def _recommended_claude(names: list[str]) -> str:
    """Pick the model to tag as "Recommended": the flagship Opus model.

    Every current Claude model is multimodal, so this is really about picking
    the strongest general-purpose model for dense policy documents.
    """
    if "claude-opus-4-8" in names:
        return "claude-opus-4-8"
    for n in names:
        if "opus" in n.lower():
            return n
    for n in names:
        if "sonnet" in n.lower():
            return n
    return names[0] if names else ""


def claude_status(api_key: str) -> dict:
    """Return {"ok": True, "models": [...]} or {"ok": False, "error": "..."}.

    Mirrors ollama_status/gemini_status so the UI can treat every engine the
    same. Also validates the key: a bad key fails the models list.
    """
    if not _ANTHROPIC_OK:
        return {"ok": False, "error": "anthropic package not installed"}
    if not api_key:
        return {"ok": False, "error": "No API key configured"}
    try:
        client = _anthropic.Anthropic(api_key=api_key, timeout=_ANTHROPIC_TIMEOUT)
        names = [m.id for m in client.models.list()]
    except Exception as exc:  # noqa: BLE001 — surface any auth/network failure to the UI
        return {"ok": False, "error": str(exc)}
    rec = _recommended_claude(names)
    # Every current Claude model is multimodal, hence vision: True.
    return {
        "ok": True,
        "models": [{"name": n, "vision": True, "recommended": n == rec} for n in names],
    }


# Indian vehicle-registration state/UT codes (anchors the plate regex so the
# label-less fallback can't latch onto chassis numbers, CINs or UINs).
_REG_STATE_CODES = (
    "AN|AP|AR|AS|BR|CG|CH|DD|DL|DN|GA|GJ|HP|HR|JH|JK|KA|KL|LA|LD|MH|ML|MN|MP|"
    "MZ|NL|OD|OR|PB|PY|RJ|SK|TN|TR|TS|UK|UP|WB"
)


def _first_amount(patterns, text: str) -> str:
    """Return the first non-zero money match across an ordered pattern list.

    Premium tables list several look-alike totals; trying patterns from most
    to least specific and skipping zero rows (e.g. "Total Liability Premium
    (B) 0.00" on an own-damage-only policy) keeps the wrong total from
    shadowing the right one.
    """
    for pat in patterns:
        val = first(pat, text)
        if not val:
            continue
        try:
            if float(val.replace(",", "")) > 0:
                return val
        except ValueError:
            continue
    return ""


def extract_fields(text: str) -> dict:
    """Pull the policy fields out of the policy text."""

    # ── PARTY NAME ──────────────────────────────────────────────────────
    # Ordered from most-specific label to loosest fallback; each pattern is
    # anchored on a label unique to one insurer family so a miss simply falls
    # through to the next shape instead of grabbing a wrong line.
    # ICICI Lombard motor / Magma: "Name of [the] Insured [: ] MR. NAME  [Policy No.]"
    party = first(
        r"Name of (?:the )?Insured\s*:?\s*([A-Za-z][A-Za-z. ]+?)(?=\s+Policy No|\s*\n)", text
    )
    # ICICI commercial schedule: "NAMED INSURED   NAME"
    if not party:
        party = first(r"NAMED INSURED\s+([A-Z][A-Z& ]+?)\s*\n", text)
    # Shriram: "Insured's Code/ Name IN-12345 / M/S. NAME  GSTIN ..."
    if not party:
        party = first(
            r"Insured'?s Code\s*/\s*Name\s+\S+\s*/\s*([A-Za-z][A-Za-z./&' ]+?)(?=\s+GSTIN|\s*\n)",
            text,
        )
    # Zuno: "Insured's Name: Mr. NAME Insured's GST No.: ..."
    if not party:
        party = first(
            r"Insured'?s Name\s*:?\s*((?:M(?:r|rs|s)\.?\s*)?[A-Za-z][A-Za-z. ]+?)"
            r"(?=\s+Insured'?s|\s*\n)",
            text,
        )
    # Liberty: "Insured NAME Policy Issued on DD/MM/YYYY" — all on one line
    # ([ \t]), so section headers like "INSURED DETAILS\nPolicy Issued" don't match.
    if not party:
        party = first(r"\bInsured[ \t]+([A-Z][A-Za-z. ]+?)[ \t]+Policy Issued", text)
    # Go Digit: "Name NAME Vehicle Registration No. XX00XX0000"
    if not party:
        party = first(r"\bName[ \t]+([A-Z][A-Za-z. ]+?)[ \t]+Vehicle Registration", text)
    # Tata AIG new summary header: "Name [Mr.] FULL NAME Unlock ..." (name stays
    # on one line, hence [ \t]). This is tried BEFORE "Insured Name" because the
    # certificate table wraps the name across lines. The lookbehinds keep
    # agent/broker rows ("POSP Name ...", "Partner Name ...") out.
    if not party:
        party = first(
            r"(?<!Intermediary )(?<!Insurer )(?<!Nominee )(?<!Agent )(?<!Partner )"
            r"(?<!POSP )(?<!Holder )(?<!Bank )(?<!Proposer )"
            r"\bName[ \t]+((?:(?:Mr\.|Mrs\.|Ms\.)\s*)?[A-Z][A-Za-z]+(?:[ \t]+[A-Za-z]+){1,5}?)(?:\s+Unlock|\s*\n)",
            text,
        )
    # Bajaj / Tata AIG old (certificate section): "Insured Name [: ] NAME  [Registration|...]"
    if not party:
        party = first(
            r"Insured Name\s*:?\s*((?:Mr\.|Mrs\.|Ms\.)?\s*[A-Za-z][A-Za-z ]+?)"
            r"(?=\s+(?:Registration|Policy|CC|Fuel|Mfg|Body|Zone)|\s*\n)",
            text,
        )
    # SBI: "Name : [Mr.]NAME  Policy Servicing|Customer ID ..." — the lookbehinds
    # keep broker/agent name rows ("Intermediary Name :", "Bank Name:...") out.
    if not party:
        party = first(
            r"(?<!Intermediary )(?<!Nominee )(?<!Agent )(?<!Partner )(?<!POSP )"
            r"(?<!Holder )(?<!Bank )(?<!Broker )"
            r"\bName\s*:\s*((?:M(?:r|rs|s)\.?\s*)?[A-Za-z][A-Za-z.&/ ]+?)"
            r"(?=\s+(?:Policy Servicing|Customer ID|Intermediary|Address|Contact|Email)|\s*\n)",
            text,
        )
    # Chola: name sits on the line right below "Name&Communication Address:"
    if not party:
        party = first(r"Name\s*&\s*Communication Address:[^\n]*\n\s*([A-Z][A-Za-z. ]+?)\s*\n", text)
    # HDFC ERGO: name line ends just before "Registration No."
    if not party:
        party = first(r"\n([A-Z][A-Z .]+?)\s+Registration No\.", text)
    # HDFC ERGO fallback: line before "Communication Address"
    if not party:
        party = first(r"\n([A-Z][A-Z .]+?)\s*\n?Communication Address", text)
    # General salutation fallback
    if not party:
        party = first(r"\b(M(?:R|RS|S|/S)\.? [A-Z][A-Z .]+)", text)
    # Some schedules print the salutation twice ("MRS MRS YUSRA ..."); collapse it.
    party = re.sub(r"^((?:M/?S|MR|MRS)\.?\s+)\1+", r"\1", party, flags=re.IGNORECASE)

    # ── INSURANCE COMPANY ────────────────────────────────────────────────
    # Handles both Title Case and ALL CAPS variants of Insurance/Limited.
    # The {1,80} / {1,40} bounds are deliberate: these two overlapping char-class
    # runs straddle the required "insurance"/"assurance" literal and are the only
    # spot here where unbounded quantifiers could backtrack badly on a long line.
    # The caps are generous (insurer names are short) so real matches are intact.
    # Brokers/intermediaries ("PROBUS INSURANCE BROKER LTD") match the same shape
    # and can appear before the insurer, so scan all matches and skip them.
    insurer = ""
    for m in re.finditer(
        r"([A-Z][A-Za-z& ]{1,80} (?:[Ii]nsurance|INSURANCE|[Aa]ssurance|ASSURANCE)"
        r"(?:[A-Za-z ]{1,40}?)?(?:[Cc]ompany |COMPANY )?(?:[Ll]imited|LIMITED|[Ll]td|LTD))",
        text,
    ):
        cand = m.group(1)
        if re.search(r"\bbrok(?:er|ers|ing)\b", cand, re.IGNORECASE):
            continue
        # Drop boilerplate the match can start on: "Welcome to X", "Thank you for
        # choosing X", "For X" (signature line), incl. a stray table token before it.
        insurer = re.sub(
            r"^(?:[A-Z]{1,3} )?(?:Welcome to |Thank you for choosing |For )", "", cand
        ).strip()
        # Some PDFs drop the spaces between words ("ICICI LombardGeneral
        # InsuranceCompanyLimited"); re-insert them at case boundaries.
        insurer = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", insurer)
        break

    # ── REGISTRATION NUMBER ──────────────────────────────────────────────
    # Indian plate: <state code> <2-digit RTO> <1-3 letter series> <3-4 digits>.
    # Restricting the leading pair to real state codes keeps the label-less
    # fallback from matching chassis/CIN/UIN fragments.
    reg_value = (
        r"((?:" + _REG_STATE_CODES + r")[- ]?\d{1,2}[- ]?[A-Z]{1,3}[- ]?\d{3,4})"
    )
    # Labelled: "Registration No.", "Vehicle Registration No.", "Registration Mark:" etc.
    reg = first(
        r"Registration\s*(?:Mark|Number|No\.?)?\s*(?:&\s*No\.?)?\s*:?\s*" + reg_value, text
    )
    # Fallback: a bare plate anywhere (vehicle-details tables print it without an
    # adjacent label). Case-sensitive so lowercase prose can't fake a plate.
    if not reg:
        reg = first(r"\b" + reg_value + r"\b", text, flags=0)

    # ── TYPE OF INSURANCE ────────────────────────────────────────────────
    # Generali welcome letter: "We thank you for choosing Motor Secure insurance policy"
    ins_type = first(r"for choosing ([A-Z][A-Za-z ]{2,40}?) insurance policy", text, flags=0)
    if not ins_type:
        ins_type = first(r"Motor Insurance\s*[-–]\s*([A-Za-z ]+?Policy)", text)
    if not ins_type:
        ins_type = first(r"(Motor Insurance[^\n]*Policy)", text)
    if not ins_type:
        ins_type = first(r"^(Auto Secure\s*[-–]\s*[^\n]+?Policy)", text, flags=re.MULTILINE)
    # Product headline naming the vehicle class. The class may wrap across a
    # line break ("COMMERCIAL VEHICLE\nINSURANCE POLICY-PACKAGE"), hence \n in
    # the bounded filler. "Insurance(?!\s+Policy)" keeps expanding through
    # "... Insurance Policy" instead of stopping at the bare "Insurance".
    # Candidates that grab half a parenthesis ("GOODS CARRYING) Policy") or a
    # QR caption ("policy details") are layout noise — skip to the next hit.
    if not ins_type:
        for m in re.finditer(
            r"((?:Two[- ]?Wheeler|Private Car|Commercial Vehicle|Goods Carrying|"
            r"Passenger Carrying)[A-Za-z ()&\n-]{0,60}?(?:Insurance(?!\s+Policy)|Policy(?!\s+details))\)?)",
            text,
            re.IGNORECASE,
        ):
            cand = re.sub(r"\s+", " ", m.group(1)).strip()
            if cand.count("(") != cand.count(")") or re.search(r"\bdetails?\b", cand, re.IGNORECASE):
                continue
            ins_type = cand
            break
    # Bajaj non-motor: "Transcript of Proposal for FLEXI HOME SHIELD (UIN) ..."
    if not ins_type:
        ins_type = first(r"Transcript of Proposal for ([A-Z][A-Za-z /&-]+?)\s*\(\s*UIN", text)
    if not ins_type:
        ins_type = first(r"(Comprehensive General Liability Insurance)", text)

    # ── PREMIUMS ─────────────────────────────────────────────────────────
    # Ordered most-specific → generic; _first_amount skips zero-valued rows.
    _AMT = r"([\d,]+(?:\.\d{1,2})?)"
    # Premium before tax.
    prem_no_gst = _first_amount(
        (
            # HDFC ERGO: "Total Package Premium (a+b) 19182"
            r"Total Package Premium\s*\(a\+b\)\s*" + _AMT,
            # Tata AIG "Net Premium (A+B+C+D) ₹", SBI "NET PREMIUM (A+B)",
            # Digit "Net Premium (`) 714.00"
            r"Net Premium\s*\([^)\n]{0,12}\)\s*[^\dA-Za-z\n]{0,8}" + _AMT,
            # SBI package: "TOTAL PREMIUM (A+B) 46361.36"
            r"TOTAL PREMIUM\s*\(A\+B\)\s*[^\d\n]{0,8}" + _AMT,
            # Bajaj Home: "Total Premium (Before GST) 7,547/-"
            r"Total Premium\s*\(Before GST\)\s*[^\d\n]{0,8}" + _AMT,
            # Generali: "Total Premium for the Policy Period 23,490.60"
            r"Total Premium for the Policy Period\s*[^\d\n]{0,8}" + _AMT,
            # Shriram: "Gross Premium 91475 IGST 0" (pre-tax when a tax row follows)
            r"Gross Premium\s+" + _AMT + r"\s*(?:Add\s*:?\s*)?(?:IGST|CGST|SGST)",
            # ICICI / Magma / Zuno / Liberty: "Total Liability Premium ₹ 714.00"
            r"Total Liability Premium\s*[^\dA-Za-z\n]{0,8}" + _AMT,
            # Liberty / Bajaj motor: bare "Net Premium ` 714.00"
            r"Net Premium\s*[^\dA-Za-z\n]{0,8}" + _AMT,
            # Chola: "TOTAL CONSIDERATION 21,663.00"
            r"TOTAL CONSIDERATION\s*[^\d\n]{0,8}" + _AMT,
        ),
        text,
    )
    # Premium including tax.
    prem_gst = _first_amount(
        (
            # SBI: "Total Premium Collected 48992.90" / "Policy premium including Tax Rs. N"
            r"Total Premium Collected\s*[^\d\n]{0,8}" + _AMT,
            r"Policy premium including Tax\s*(?:Rs\.?)?\s*[^\d\n]{0,5}" + _AMT,
            # Tata AIG summary: "Premium Amount (Including GST) ₹ NNN"
            r"Premium Amount\s*\(Including GST\)\s*[₹`]?\s*" + _AMT,
            # ICICI Motor: "Total Premium Payable In ` 843.00"
            r"Total Premium Payable In\s*[`₹]?\s*" + _AMT,
            # Digit / Zuno / Bajaj motor / SBI: "Final Premium 842.52"
            r"Final Premium\s*[^\dA-Za-z\n]{0,8}" + _AMT,
            # Shriram: "PREMIUM AMOUNT 102189.00"
            r"PREMIUM AMOUNT\s*[^\dA-Za-z\n]{0,8}" + _AMT,
            # Chola: "AMOUNT COLLECTED 23,465.00"
            r"AMOUNT COLLECTED\s*[^\d\n]{0,8}" + _AMT,
            # Tata AIG / Liberty: "TOTAL POLICY PREMIUM ` 843.00"
            r"Total Policy Premium\s*[^\d\n]{0,8}" + _AMT,
            # ICICI Commercial: "PREMIUM (INCLUSIVE OF ALL\nX NNN\nAPPLICABLE TAXES) INR"
            r"PREMIUM\s*\(INCLUSIVE OF ALL\s*\n[^\d\n]*([\d,]+)",
            # Generali tax invoice: "a sum of Rs. 27,719.00 towards Premium"
            r"sum of Rs\.?\s*([\d,]+)(?:\.\d+)?\s*towards Premium",
            # Generali "Total Premium (rounded off) 27,719.00"; HDFC "Total Premium NNNN".
            # Digits must follow immediately — a looser filler would grab Generali's
            # pre-tax "Total Premium for the Policy Period" line instead.
            r"Total Premium\s*(?:\(rounded off\)\s*)?[`₹]?\s*" + _AMT,
            # Magma: the grand-total row "TOTAL 4,787.00" under the GST lines
            r"(?m)^TOTAL\s+([\d,]+\.\d{2})\s*$",
            # Bajaj Home: "Gross Premium 8,905/-" (post-tax when nothing follows)
            r"Gross Premium\s*[^\dA-Za-z\n]{0,8}" + _AMT,
        ),
        text,
    )

    # ── POLICY PERIOD ────────────────────────────────────────────────────
    # Generali / Magma / Shriram / Liberty / Zuno: a time-of-day precedes the
    # date — "From 00:00 Hrs of DD/MM/YYYY", "From 12:01:00 of DD/MM/YYYY"
    date_start = first(
        r"\d{1,2}:\d{2}(?::\d{2})?\s*(?:[Hh](?:ou)?rs\.?)?\s+(?:of|on)\s+(\d{2}/\d{2}/\d{4})",
        text,
    )
    date_end = ""
    # HDFC ERGO / SBI: "From DD/MM/YYYY" ... "To DD/MM/YYYY"
    if not date_start:
        date_start = first(r"From\s*:?\s*(\d{2}/\d{2}/\d{4})", text)
        date_end = first(r"To\s*:?\s*(\d{2}/\d{2}/\d{4})", text)
    # Magma letter: "Period of Insurance DD/MM/YYYY TO DD/MM/YYYY"
    if not date_start:
        date_start = first(r"Period [Oo]f Insurance\s*:?\s*(\d{2}/\d{2}/\d{4})\s*TO", text)
    # HDFC ERGO: "From D Mon, YYYY" style
    if not date_start:
        date_start = first(r"From\s+(\d{1,2} [A-Za-z]{3,9},? \d{4})", text)
        date_end = first(r"To\s+(\d{1,2} [A-Za-z]{3,9},? \d{4})", text)
    # Tata AIG new layout: dates carry "(HH:MM Hrs)" / "(Midnight)" markers
    if not date_start:
        date_start = first(r"(\d{2}/\d{2}/\d{4})\s*\(\d{2}:\d{2} Hrs\)", text)
        date_end = first(r"(\d{2}/\d{2}/\d{4})\s*\(Midnight\)", text)
    # Tata AIG old layout: "TP cover period : D Mon 'YY(HH:MMHrs) to D Mon 'YY (Midnight)"
    if not date_start:
        date_start = first(r"[Cc]over [Pp]eriod\s*:?\s*(\d{1,2} [A-Za-z]{3} '\d{2})", text)
        date_end = first(r"(\d{1,2} [A-Za-z]{3} '\d{2})\s*\(Midnight\)", text)
    # ICICI Motor: "Period of Insurance [: ] Mon D, YYYY ... to ... Mon D, YYYY"
    if not date_start:
        date_start = first(r"Period of Insurance\s*:?\s*([A-Za-z]{3} \d{1,2}, \d{4})", text)
        date_end = first(r"Midnight of ([A-Za-z]{3} \d{1,2}, \d{4})", text)
        if not date_end:
            date_end = first(r"\bto ([A-Za-z]{3} \d{1,2}, \d{4})", text)
    # Bajaj Home / Digit: "From DD-MON-YYYY To DD-MON-YYYY" (or DD-Mon-YYYY)
    if not date_start:
        date_start = first(r"[Ff]rom\s*(\d{1,2}-[A-Za-z]{3}-\d{4})", text)
        date_end = first(r"[Tt]o\s+(\d{1,2}-[A-Za-z]{3}-\d{4})", text)
    # Bajaj motor: "From 26-06-2026 00:00:00 to 25-06-2027 Midnight"
    if not date_start:
        date_start = first(r"From:?\s*(\d{2}-\d{2}-\d{4})", text)
        date_end = first(r"[Tt]o:?\s*(\d{2}-\d{2}-\d{4})", text)
    # A start without an end usually means the end date uses a different shape
    # (e.g. Chola "from DD/MM/YYYY 00:00 hours to midnight on DD/MM/YYYY").
    if date_start and not date_end:
        for pat in (
            # "To Midnight of DD/MM/YYYY" / "midnight on DD/MM/YYYY" / "Midnight Of ..."
            r"Midnight\s*(?:of|on)?\s*:?\s*(\d{2}/\d{2}/\d{4})",
            # Zuno: "to 23:59:59 of DD/MM/YYYY"
            r"[Tt]o\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:of|on)\s*(\d{2}/\d{2}/\d{4})",
            r"To\s*:?\s*(\d{2}/\d{2}/\d{4})",
            # Watermark-garbled Digit PDFs: allow a little noise after "To"
            r"To[^\n]{0,20}?(\d{1,2}-[A-Za-z]{3}-\d{4})",
        ):
            date_end = first(pat, text)
            if date_end:
                break

    # ── NCB ──────────────────────────────────────────────────────────────
    # HDFC ERGO: "No Claim Bonus 25 %" / Tata AIG: "No claim bonus (45%)"
    ncb_applied = first(r"No Claim Bonus\s*\(?\s*(\d{1,2})\s*%", text)
    # Tata AIG: "NCB Claimed: 45 %" (fallback)
    if not ncb_applied:
        ncb_applied = first(r"NCB Claimed\s*:\s*(\d{1,2})\s*%", text)
    # Generali schedule: "Renewal NCB % 0%"
    if not ncb_applied:
        ncb_applied = first(r"Renewal NCB\s*%?\s*(\d{1,2})\s*%", text)
    # Shriram: "NCB Discount (%) 50"
    if not ncb_applied:
        ncb_applied = first(r"NCB Discount\s*\(%\)\s*(\d{1,2})", text)
    # Chola: "Bonus Discount (25%)"
    if not ncb_applied:
        ncb_applied = first(r"Bonus Discount\s*\(\s*(\d{1,2})\s*%\s*\)", text)
    # HDFC ERGO: "NCB 20%" = previous policy NCB
    ncb_prev = first(r"\bNCB\s*(\d{1,2})\s*%", text)
    # Tata AIG: "NCB in Previous Policy: 35 %"
    if not ncb_prev:
        ncb_prev = first(r"NCB in Previous Policy\s*:\s*(\d{1,2})\s*%", text)

    # ── POLICY NUMBER ────────────────────────────────────────────────────
    # The first token after the label must itself contain a digit, so filler
    # words ("Policy No. is ...") and headings ("Renew Policy No") fall through
    # to the next occurrence instead of being captured. "(?<!Previous )" keeps
    # a renewal's old policy number from shadowing the current one.
    _POLICY_VALUE = r"([A-Za-z0-9/.-]*\d[A-Za-z0-9/.-]*(?:(?:\s+|/)[0-9]+){0,4})"
    policy_no = first(r"Policy\s*/\s*Certificate\s*No\.?\s*:?\s*" + _POLICY_VALUE, text)
    if not policy_no:
        policy_no = first(
            r"(?<!Previous )Policy\s*(?:No\.?|Number)\s*:?\s*" + _POLICY_VALUE, text
        )
    if not policy_no:
        policy_no = first(
            r"(?<!Previous )Certificate\s*(?:No\.?|Number)\s*:?\s*" + _POLICY_VALUE, text
        )

    return {
        "Party Name": party,
        "Insurance Company": insurer,
        "Policy No.": policy_no,
        "Reg Number": reg,
        "Type of Insurance": ins_type,
        "Premium (Without GST)": prem_no_gst,
        "Premium": prem_gst,
        "Date Start": date_start,
        "End Date": date_end,
        "NCB (applied this yr)": ncb_applied + ("%" if ncb_applied else ""),
        "Source File": "",  # filled in by caller
    }


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


def process_pdf(pdf_path: str) -> tuple[dict, dict]:
    """Full regex pipeline for one PDF: returns (fields row, preview locations).

    Top-level and returning only plain picklable data so app.py can run it in a
    worker process — pdfminer parsing is pure Python, so real parallelism for
    batch extraction needs processes, not threads.
    """
    text, pages_words = read_document(pdf_path)
    row = extract_fields(text)
    locations = locate_fields(pdf_path, row, pages_words=pages_words)
    return row, locations


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

    rows = []
    for path in pdfs:
        try:
            data = extract_fields(read_text(path))
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
