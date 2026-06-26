"""
Offline insurance-policy PDF field extractor.

Drop your PDFs into a folder, run this script, and it writes one row per
policy to an Excel file. Everything runs locally — no internet, no upload.

Usage:
    python extract_policies.py /path/to/folder_of_pdfs   output.xlsx

This is the RULE-BASED version, tuned for the HDFC ERGO layout. See the notes
at the bottom for how to make it handle ANY insurer using a local LLM.
"""

import sys
import re
import os
import glob
import pdfplumber
import pandas as pd


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


def extract_fields(text: str) -> dict:
    """Pull the 9 fields out of the policy text."""

    # Party name: the insured's name sits just above "Communication Address"
    party = first(r"\n([A-Z][A-Z .]+?)\s*\n?Communication Address", text)
    if not party:  # fallback: a line that starts with a salutation
        party = first(r"\b(M(?:R|RS|S|/S)\.? [A-Z][A-Z .]+)", text)

    # Insurer: take the company name from the header
    insurer = first(r"([A-Z][A-Za-z& ]*?(?:Insurance|Assurance)[A-Za-z ]*?(?:Company )?(?:Limited|Ltd|Co\.?L?t?d?))", text)

    # Registration number, e.g. GJ-03-BZ-1330
    reg = first(r"Registration No\.?\s*([A-Z]{2}[- ]?\d{1,2}[- ]?[A-Z]{1,3}[- ]?\d{3,4})", text)

    # Type / product name
    ins_type = first(r"Motor Insurance\s*[-–]\s*([A-Za-z ]+?Policy)", text)
    if not ins_type:
        ins_type = first(r"(Motor Insurance[^\n]*Policy)", text)

    # Premium WITHOUT GST  = the package premium (a+b), before tax
    prem_no_gst = first(r"Total Package Premium\s*\(a\+b\)\s*([\d,]+)", text)

    # Premium WITH GST = the final total premium
    prem_gst = first(r"Total Premium\s*([\d,]+)", text)

    # Policy period
    date_start = first(r"From\s*(\d{2}/\d{2}/\d{4})", text)
    date_end = first(r"To\s*(\d{2}/\d{2}/\d{4})", text)
    if not date_start:  # the "21 Dec, 2025" style
        date_start = first(r"From\s*(\d{1,2} [A-Za-z]{3,9},? \d{4})", text)
        date_end = first(r"To\s*(\d{1,2} [A-Za-z]{3,9},? \d{4})", text)

    # NCB — note: two values exist on these policies.
    #   "No Claim Bonus 25 %" = discount applied THIS year
    #   "NCB 20%"             = NCB earned from the PREVIOUS policy
    ncb_applied = first(r"No Claim Bonus\s*(\d{1,2})\s*%", text)
    ncb_prev = first(r"\bNCB\s*(\d{1,2})\s*%", text)

    return {
        "Party Name": party,
        "Insurance Company": insurer,
        "Reg Number": reg,
        "Type of Insurance": ins_type,
        "Premium without GST": prem_no_gst,
        "Premium with GST": prem_gst,
        "Date Start": date_start,
        "End Date": date_end,
        "NCB (applied this yr)": ncb_applied + ("%" if ncb_applied else ""),
        "NCB (prev policy)": ncb_prev + ("%" if ncb_prev else ""),
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
