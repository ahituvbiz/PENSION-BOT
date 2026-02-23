import streamlit as st
import fitz
import json
import os
import base64
import pandas as pd
import re
from openai import OpenAI

st.set_page_config(page_title="מנתח פנסיה - גירסה 30.0 (Vision)", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;700&display=swap');
    * { font-family: 'Assistant', sans-serif; direction: rtl; text-align: right; }
    .stTable { direction: rtl !important; width: 100%; }
    th, td { text-align: right !important; padding: 12px !important; white-space: nowrap; }
    .val-success { padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold;
        background-color: #f0fdf4; border: 1px solid #16a34a; color: #16a34a; }
    .val-error { padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold;
        background-color: #fef2f2; border: 1px solid #dc2626; color: #dc2626; }
</style>
""", unsafe_allow_html=True)

def init_client():
    api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    return OpenAI(api_key=api_key) if api_key else None

def clean_num(val):
    if val is None or val == "" or str(val).strip() in ["-", "nan", ".", "0"]: return 0.0
    try:
        cleaned = re.sub(r'[^\d\.\-]', '', str(val).replace(",", "").replace("−", "-"))
        return float(cleaned) if cleaned else 0.0
    except: return 0.0

# ── המרת עמודי PDF לתמונות base64 ─────────────────────────────────────────────
def pdf_to_images_b64(file_bytes, dpi=200):
    """ממיר כל עמוד ב-PDF לתמונת PNG מקודדת base64."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    images = []
    for page in doc:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        images.append(base64.b64encode(pix.tobytes("png")).decode("utf-8"))
    return images

# ── תיקון טבלה ד': איחוד שורות גולשות ────────────────────────────────────────
def fix_table_d_multiline(rows):
    if not rows: return rows
    fixed = []
    for row in rows:
        track = str(row.get("מסלול", "")).strip()
        ret   = str(row.get("תשואה", "")).strip()
        if (ret == "" or ret == "-") and fixed:
            fixed[-1]["מסלול"] = fixed[-1]["מסלול"] + " " + track
        else:
            fixed.append(dict(row))
    return fixed

def perform_cross_validation(data):
    dep_b = 0.0
    for r in data.get("table_b", {}).get("rows", []):
        row_str = " ".join(str(v) for v in r.values())
        if any(kw in row_str for kw in ["הופקדו", "כספים שהופקדו"]):
            nums = [clean_num(v) for v in r.values() if clean_num(v) > 10]
            if nums: dep_b = nums[0]
            break
    rows_e = data.get("table_e", {}).get("rows", [])
    dep_e = clean_num(rows_e[-1].get("סה\"כ", 0)) if rows_e else 0.0
    if abs(dep_b - dep_e) < 5 and dep_e > 0:
        st.markdown(f'<div class="val-success">✅ אימות הצלבה עבר: סכום ההפקדות ({dep_e:,.2f} ₪) תואם במדויק.</div>', unsafe_allow_html=True)
    elif dep_e > 0:
        st.markdown(f'<div class="val-error">⚠️ שגיאת אימות: טבלה ב\' ({dep_b:,.2f} ₪) לעומת טבלה ה\' ({dep_e:,.2f} ₪).</div>', unsafe_allow_html=True)

def display_pension_table(rows, title, col_order):
    if not rows: return
    df = pd.DataFrame(rows)
    existing = [c for c in col_order if c in df.columns]
    df = df[existing]
    df.index = range(1, len(df) + 1)
    st.subheader(title)
    st.table(df)

# ── קריאה ל-GPT-4o Vision ─────────────────────────────────────────────────────
def process_audit_v30(client, images_b64):
    """
    שולח את כל עמודי הדוח כתמונות ל-GPT-4o Vision.
    היתרון: ה-AI רואה את הפריסה הויזואלית המלאה במקום טקסט כאוטי.
    """
    system_msg = (
        "You are a mechanical OCR tool for Israeli pension reports (דוחות פנסיה). "
        "You see the document visually and extract tables exactly as they appear. "
        "You do not round numbers, do not flip digits, and do not interpret. "
        "For table_d: if a track name wraps to a second line, merge both lines into one מסלול string. "
        "For table_e: extract מועד (deposit date) and חודש (salary month) for every non-summary row."
    )

    user_content = [
        {
            "type": "text",
            "text": """Extract ALL FIVE tables from this Israeli pension report into JSON.

TABLES:
- table_a: תשלומים צפויים → columns: תיאור, סכום בש"ח
- table_b: תנועות בקרן → columns: תיאור, סכום בש"ח  
- table_c: דמי ניהול → columns: תיאור, אחוז
- table_d: מסלולי השקעה → columns: מסלול, תשואה
- table_e: פירוט הפקדות → columns: שם המעסיק, מועד, חודש, שכר, עובד, מעסיק, פיצויים, סה"כ

CRITICAL RULES:
1. Copy numbers EXACTLY — do not round, do not flip digits.
2. table_e: מועד = deposit date (e.g. 06/01/2025), חודש = salary month (e.g. 12/2024). Fill both for every data row.
3. table_e summary row (סה"כ): מועד="", חודש="", שם המעסיק="סה\\"כ"
4. table_d: merge wrapped track names into one row.
5. Negative values in table_b must stay negative (e.g. -442).

Return ONLY valid JSON, no markdown fences:
{"table_a":{"rows":[{"תיאור":"","סכום בש\\"ח":""}]},
 "table_b":{"rows":[{"תיאור":"","סכום בש\\"ח":""}]},
 "table_c":{"rows":[{"תיאור":"","אחוז":""}]},
 "table_d":{"rows":[{"מסלול":"","תשואה":""}]},
 "table_e":{"rows":[{"שם המעסיק":"","מועד":"","חודש":"","שכר":"","עובד":"","מעסיק":"","פיצויים":"","סה\\"כ":""}]}}"""
        }
    ]

    # הוספת כל עמודי הדוח כתמונות
    for img_b64 in images_b64:
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}",
                "detail": "high"  # רזולוציה גבוהה לקריאת מספרים מדויקת
            }
        })

    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_content}
        ],
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=4096
    )

    raw = res.choices[0].message.content
    data = json.loads(raw)

    # ── Post-processing (Python בלבד, ללא AI) ──────────────────────────────────

    # תיקון טבלה ד'
    if "table_d" in data:
        data["table_d"]["rows"] = fix_table_d_multiline(data["table_d"].get("rows", []))

    # תיקון טבלה ה' — שורת סיכום
    rows_e = data.get("table_e", {}).get("rows", [])
    if len(rows_e) > 1:
        last_row = rows_e[-1]

        # חישוב שכר
        salary_sum = sum(clean_num(r.get("שכר", 0)) for r in rows_e[:-1])

        # Shift Fix
        vals = [last_row.get("עובד"), last_row.get("מעסיק"), last_row.get("פיצויים"), last_row.get("סה\"כ")]
        cleaned_vals = [clean_num(v) for v in vals]
        max_val = max(cleaned_vals)
        if max_val > 0 and clean_num(last_row.get("סה\"כ")) != max_val:
            non_zero_vals = [v for v in vals if clean_num(v) > 0]
            if len(non_zero_vals) == 4:
                last_row["סה\"כ"]    = non_zero_vals[3]
                last_row["פיצויים"] = non_zero_vals[2]
                last_row["מעסיק"]   = non_zero_vals[1]
                last_row["עובד"]    = non_zero_vals[0]
            elif len(non_zero_vals) == 3:
                last_row["סה\"כ"]    = non_zero_vals[2]
                last_row["מעסיק"]   = non_zero_vals[1]
                last_row["עובד"]    = non_zero_vals[0]
                last_row["פיצויים"] = "0"

        last_row["שכר"]       = f"{salary_sum:,.0f}"
        last_row["מועד"]      = ""
        last_row["חודש"]      = ""
        last_row["שם המעסיק"] = "סה\"כ"

    return data

# ── ממשק משתמש ────────────────────────────────────────────────────────────────
st.title("📋 חילוץ נתונים פנסיוני - גירסה 30.0 (Vision)")
st.caption("משתמש ב-GPT-4o Vision — קורא את הדוח ויזואלית כמו בן אדם, ולא כטקסט כאוטי")

client = init_client()

if client:
    file = st.file_uploader("העלה דוח PDF", type="pdf")
    if file:
        file_bytes = file.read()
        with st.spinner("ממיר עמודים לתמונות ושולח ל-GPT-4o Vision..."):
            images_b64 = pdf_to_images_b64(file_bytes, dpi=200)
            st.info(f"📄 {len(images_b64)} עמודים זוהו ונשלחים לניתוח")
            data = process_audit_v30(client, images_b64)

        if data:
            perform_cross_validation(data)
            display_pension_table(data.get("table_a", {}).get("rows"), "א. תשלומים צפויים",   ["תיאור", "סכום בש\"ח"])
            display_pension_table(data.get("table_b", {}).get("rows"), "ב. תנועות בקרן",       ["תיאור", "סכום בש\"ח"])
            display_pension_table(data.get("table_c", {}).get("rows"), "ג. דמי ניהול והוצאות", ["תיאור", "אחוז"])
            display_pension_table(data.get("table_d", {}).get("rows"), "ד. מסלולי השקעה",       ["מסלול", "תשואה"])
            display_pension_table(data.get("table_e", {}).get("rows"), "ה. פירוט הפקדות",
                                  ["שם המעסיק", "מועד", "חודש", "שכר", "עובד", "מעסיק", "פיצויים", "סה\"כ"])
else:
    st.error("לא נמצא OPENAI_API_KEY — הגדר אותו ב-secrets או כמשתנה סביבה.")
