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

OLLAMA_URL = "http://localhost:11434"
# Max characters of PDF text sent to the LLM (keeps prompts fast).
_OLLAMA_MAX_CHARS = 8000
# Below this many characters we consider the text layer "poor" and try vision.
_MIN_TEXT_CHARS = 200

_EXTRACT_PROMPT = """\
You are an insurance document parser. Extract the following fields from the \
policy document text below and return ONLY a valid JSON object — no markdown, \
no explanation, just the JSON.

Required keys (use "" if not found):
  "Party Name"          – full name of the insured person or entity
  "Insurance Company"   – full legal name of the insurer
  "Policy No."          – policy number / ID
  "Reg Number"          – vehicle registration number (e.g. MH01AB1234)
  "Type of Insurance"   – policy type (e.g. Comprehensive, Third Party, etc.)
  "Premium"             – total premium including GST, digits only (no ₹ or commas)
  "Date Start"          – policy start date in DD/MM/YYYY
  "End Date"            – policy end date in DD/MM/YYYY
  "NCB (applied this yr)" – no-claim bonus % applied this year (e.g. "25%")

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
  "Reg Number"          – vehicle registration number (e.g. MH01AB1234)
  "Type of Insurance"   – policy type (e.g. Comprehensive, Third Party, etc.)
  "Premium"             – total premium including GST, digits only (no ₹ or commas)
  "Date Start"          – policy start date in DD/MM/YYYY
  "End Date"            – policy end date in DD/MM/YYYY
  "NCB (applied this yr)" – no-claim bonus % applied this year (e.g. "25%")
"""


def _is_text_poor(text: str) -> bool:
    """Return True when pdfplumber extracted too little text to be useful."""
    return len(text.strip()) < _MIN_TEXT_CHARS


def pdf_pages_to_b64(pdf_path: str) -> list[str]:
    """Render each PDF page to a base64-encoded PNG (requires pymupdf)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError(
            "pymupdf is required for vision extraction. Install it with: pip install pymupdf"
        )
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2× zoom ≈ 144 dpi
        images.append(base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return images


def extract_fields_ollama_vision(pdf_path: str, model: str, url: str = OLLAMA_URL) -> dict:
    """Use a vision-capable Ollama model to extract fields directly from PDF images."""
    if not _REQUESTS_OK:
        raise RuntimeError("requests library is required for Ollama extraction")
    images = pdf_pages_to_b64(pdf_path)
    payload = {
        "model": model,
        "prompt": _VISION_PROMPT,
        "images": images,
        "stream": False,
        "format": "json",
    }
    logger.info("=== Ollama vision: %d page(s) -> %s ===", len(images), model)
    r = _requests.post(f"{url}/api/generate", json=payload, timeout=300)
    r.raise_for_status()
    raw = r.json().get("response", "{}")
    logger.info("=== Ollama vision response ===\n%s", raw)
    fields = json.loads(raw)
    return {
        "Party Name": fields.get("Party Name", ""),
        "Insurance Company": fields.get("Insurance Company", ""),
        "Policy No.": fields.get("Policy No.", ""),
        "Reg Number": fields.get("Reg Number", ""),
        "Type of Insurance": fields.get("Type of Insurance", ""),
        "Premium": str(fields.get("Premium", "")),
        "Date Start": fields.get("Date Start", ""),
        "End Date": fields.get("End Date", ""),
        "NCB (applied this yr)": fields.get("NCB (applied this yr)", ""),
        "Source File": "",
    }


def read_text(pdf_path: str) -> str:
    """Extract the full text layer from a PDF."""
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    # collapse whitespace so regexes are easier to write
    return re.sub(r"[ \t]+", " ", "\n".join(chunks))


def first(pattern, text, group=1, flags=re.IGNORECASE):
    """Return the first regex match (a stripped string) or '' if none."""
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else ""


def ollama_status(url: str = OLLAMA_URL) -> dict:
    """Return {"ok": True, "models": [...]} or {"ok": False, "error": "..."}."""
    if not _REQUESTS_OK:
        return {"ok": False, "error": "requests library not installed"}
    try:
        r = _requests.get(f"{url}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        return {"ok": True, "models": models}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def extract_fields_ollama(text: str, model: str, url: str = OLLAMA_URL) -> dict:
    """Ask a local Ollama model to extract policy fields and return a dict."""
    if not _REQUESTS_OK:
        raise RuntimeError("requests library is required for Ollama extraction")
    prompt = _EXTRACT_PROMPT.format(text=text[:_OLLAMA_MAX_CHARS])
    logger.info("=== Ollama prompt ===\n%s", prompt)
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json"}
    r = _requests.post(f"{url}/api/generate", json=payload, timeout=180)
    r.raise_for_status()
    raw = r.json().get("response", "{}")
    logger.info("=== Ollama response ===\n%s", raw)
    fields = json.loads(raw)
    return {
        "Party Name": fields.get("Party Name", ""),
        "Insurance Company": fields.get("Insurance Company", ""),
        "Policy No.": fields.get("Policy No.", ""),
        "Reg Number": fields.get("Reg Number", ""),
        "Type of Insurance": fields.get("Type of Insurance", ""),
        "Premium": str(fields.get("Premium", "")),
        "Date Start": fields.get("Date Start", ""),
        "End Date": fields.get("End Date", ""),
        "NCB (applied this yr)": fields.get("NCB (applied this yr)", ""),
        "Source File": "",
    }


def extract_fields(text: str) -> dict:
    """Pull the 9 fields out of the policy text."""

    # ── PARTY NAME ──────────────────────────────────────────────────────
    # ICICI Lombard motor: "Name of the Insured [: ] NAME  Policy No."
    party = first(r"Name of the Insured\s*:?\s*([A-Za-z][A-Za-z ]+?)(?:\s+Policy No\.|\s*\n)", text)
    # ICICI commercial schedule: "NAMED INSURED   NAME"
    if not party:
        party = first(r"NAMED INSURED\s+([A-Z][A-Z& ]+?)\s*\n", text)
    # Tata AIG new summary header: "Name [Mr.] FULL NAME Unlock ..." (full name on one line)
    # This is tried BEFORE "Insured Name" because the certificate table wraps the name across lines.
    if not party:
        party = first(
            r"\bName\s+((?:(?:Mr\.|Mrs\.|Ms\.)\s*)?[A-Z][A-Za-z]+(?:\s+[A-Za-z]+){1,5}?)(?:\s+Unlock|\s*\n)",
            text,
        )
    # Bajaj / Tata AIG old (certificate section): "Insured Name [: ] NAME  [Registration|...]"
    if not party:
        party = first(
            r"Insured Name\s*:?\s*((?:Mr\.|Mrs\.|Ms\.)?\s*[A-Za-z][A-Za-z ]+?)"
            r"(?=\s+(?:Registration|Policy|CC|Fuel|Mfg|Body|Zone)|\s*\n)",
            text,
        )
    # HDFC ERGO: name line ends just before "Registration No."
    if not party:
        party = first(r"\n([A-Z][A-Z .]+?)\s+Registration No\.", text)
    # HDFC ERGO fallback: line before "Communication Address"
    if not party:
        party = first(r"\n([A-Z][A-Z .]+?)\s*\n?Communication Address", text)
    # General salutation fallback
    if not party:
        party = first(r"\b(M(?:R|RS|S|/S)\.? [A-Z][A-Z .]+)", text)

    # ── INSURANCE COMPANY ────────────────────────────────────────────────
    # Case-sensitive [A-Z] start avoids broker names (e.g. "probus insurance…")
    # Handles both Title Case and ALL CAPS variants of Insurance/Limited
    insurer = first(
        r"([A-Z][A-Za-z& ]+ (?:[Ii]nsurance|INSURANCE|[Aa]ssurance|ASSURANCE)"
        r"(?:[A-Za-z ]+?)?(?:[Cc]ompany |COMPANY )?(?:[Ll]imited|LIMITED|[Ll]td|LTD))",
        text,
        flags=0,
    )
    if insurer:
        insurer = re.sub(r"^(?:Welcome to |For )", "", insurer).strip()

    # ── REGISTRATION NUMBER ──────────────────────────────────────────────
    # Accepts "Registration No.", "Registration no :", "Vehicle Registration No." etc.
    reg = first(r"Registration [Nn]o\.?\s*:?\s*([A-Z]{2}[- ]?\d{1,2}[- ]?[A-Z]{1,3}[- ]?\d{3,4})", text)

    # ── TYPE OF INSURANCE ────────────────────────────────────────────────
    ins_type = first(r"Motor Insurance\s*[-–]\s*([A-Za-z ]+?Policy)", text)
    if not ins_type:
        ins_type = first(r"(Motor Insurance[^\n]*Policy)", text)
    if not ins_type:
        ins_type = first(r"^(Auto Secure\s*[-–]\s*[^\n]+?Policy)", text, flags=re.MULTILINE)
    if not ins_type:
        ins_type = first(r"((?:Two Wheeler|Private Car|Commercial Vehicle)[^\n]+?Policy)", text)
    if not ins_type:
        ins_type = first(r"(Comprehensive General Liability Insurance)", text)

    # ── PREMIUMS ─────────────────────────────────────────────────────────
    # HDFC ERGO (package premium breakdown)
    prem_no_gst = first(r"Total Package Premium\s*\(a\+b\)\s*([\d,]+)", text)
    prem_gst = first(r"Total Premium\s*([\d,]+)", text)
    # Tata AIG / Probus: "Net Premium (A+B+C+D) ₹ NNNN"
    if not prem_no_gst:
        prem_no_gst = first(r"Net Premium\s*\([^)]+\)\s*[^\d]*([\d,]+)", text)
    if not prem_gst:
        prem_gst = first(r"Total Policy Premium\s*[^\d]*([\d,.]+)", text)
    # ICICI Motor (liability-only layout)
    if not prem_no_gst:
        prem_no_gst = first(r"Total Liability Premium\s*([\d,.]+)", text)
    if not prem_gst:
        prem_gst = first(r"Total Premium Payable In\s*[`₹]?\s*([\d,.]+)", text)
    # ICICI Commercial: "PREMIUM (INCLUSIVE OF ALL\nX NNN\nAPPLICABLE TAXES) INR"
    if not prem_gst:
        prem_gst = first(r"PREMIUM\s*\(INCLUSIVE OF ALL\s*\n[^\d\n]*([\d,]+)", text)
    # Tata AIG summary: "Premium Amount (Including GST) ₹ NNN"
    if not prem_gst:
        prem_gst = first(r"Premium [Aa]mount\s*\(Including GST\)\s*[₹]?\s*([\d,]+)", text)
    # Bajaj Home: "Total Amount NNNN" (the settled payable amount)
    if not prem_gst:
        prem_gst = first(r"Total Amount\s*([\d,]+)", text)
    # Bajaj Home: "Total Premium (Before GST) N,NNN"
    if not prem_no_gst:
        prem_no_gst = first(r"Total Premium\s*\(Before GST\)\s*([\d,]+)", text)

    # ── POLICY PERIOD ────────────────────────────────────────────────────
    # HDFC ERGO: "From DD/MM/YYYY"
    date_start = first(r"From\s+(\d{2}/\d{2}/\d{4})", text)
    date_end = first(r"To\s+(\d{2}/\d{2}/\d{4})", text)
    # Tata AIG (Jasani/liability): "From DD/MM/YYYY … To DD/MM/YYYY" in certificate
    if not date_start:
        date_start = first(r"From\s*:?\s*(\d{2}/\d{2}/\d{4})", text)
        date_end = first(r"To\s*:?\s*(\d{2}/\d{2}/\d{4})", text)
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
    # Bajaj-style: "FromDD-MON-YYYY To DD-MON-YYYY"
    if not date_start:
        date_start = first(r"[Ff]rom\s*(\d{2}-[A-Z]{3}-\d{4})", text)
        date_end = first(r"[Tt]o\s+(\d{2}-[A-Z]{3}-\d{4})", text)

    # ── NCB ──────────────────────────────────────────────────────────────
    # HDFC ERGO: "No Claim Bonus 25 %" / Tata AIG: "No claim bonus (45%)"
    ncb_applied = first(r"No Claim Bonus\s*\(?\s*(\d{1,2})\s*%", text)
    # Tata AIG: "NCB Claimed: 45 %" (fallback)
    if not ncb_applied:
        ncb_applied = first(r"NCB Claimed\s*:\s*(\d{1,2})\s*%", text)
    # HDFC ERGO: "NCB 20%" = previous policy NCB
    ncb_prev = first(r"\bNCB\s*(\d{1,2})\s*%", text)
    # Tata AIG: "NCB in Previous Policy: 35 %"
    if not ncb_prev:
        ncb_prev = first(r"NCB in Previous Policy\s*:\s*(\d{1,2})\s*%", text)

    # ── POLICY NUMBER ────────────────────────────────────────────────────
    policy_no = first(r"Policy\s*(?:No\.?|Number)\s*:?\s*([A-Za-z0-9/.-]+(?:(?:\s+|/)[0-9]+){0,4})", text)

    return {
        "Party Name": party,
        "Insurance Company": insurer,
        "Policy No.": policy_no,
        "Reg Number": reg,
        "Type of Insurance": ins_type,
        "Premium": prem_gst,
        "Date Start": date_start,
        "End Date": date_end,
        "NCB (applied this yr)": ncb_applied + ("%" if ncb_applied else ""),
        "Source File": "",  # filled in by caller
    }


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    out = sys.argv[2] if len(sys.argv) > 2 else "policies.xlsx"

    pdfs = sorted(glob.glob(os.path.join(folder, "*.pdf")))
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

    df = pd.DataFrame(rows)
    df.to_excel(out, index=False)
    print(f"\nWrote {len(rows)} rows -> {out}")
    # also print to screen so you can eyeball it
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
