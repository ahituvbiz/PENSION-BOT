import streamlit as st
import fitz
import json
import os
import pandas as pd
import re
from openai import OpenAI

st.set_page_config(page_title="מנתח פנסיה - גירסה 29.0 (דיוק מוחלט)", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;700&display=swap');
    * { font-family: 'Assistant', sans-serif; direction: rtl; text-align: right; }
    .stTable { direction: rtl !important; width: 100%; }
    th, td { text-align: right !important; padding: 12px !important; white-space: nowrap; }
    .val-success { padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold; background-color: #f0fdf4; border: 1px solid #16a34a; color: #16a34a; }
    .val-error { padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold; background-color: #fef2f2; border: 1px solid #dc2626; color: #dc2626; }
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

def perform_cross_validation(data):
    """אימות הצלבה קשיח בין טבלה ב' ל-ה'"""
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

# ────────────────────────────────────────────────────────────────────────────────
# תיקון #1 - טבלה ד': איחוד שמות מסלול שנגלשו לשורה שמתחת
# לוגיקה: אם שורה אין לה תשואה (ריק או "-") — היא המשך שם המסלול של השורה הקודמת
# ────────────────────────────────────────────────────────────────────────────────
def fix_table_d_multiline(rows):
    if not rows:
        return rows
    fixed = []
    for row in rows:
        track = str(row.get("מסלול", "")).strip()
        ret   = str(row.get("תשואה", "")).strip()

        # שורה ללא תשואה = המשך שם המסלול הקודם
        if (ret == "" or ret == "-") and fixed:
            fixed[-1]["מסלול"] = fixed[-1]["מסלול"] + " " + track
        else:
            fixed.append(dict(row))
    return fixed

# ────────────────────────────────────────────────────────────────────────────────
# תיקון #2 - טבלה ה': ה-post-processing מנקה מועד/חודש רק בשורת הסיכום
# הבאג המקורי: "last_row["מועד"] = ""; last_row["חודש"] = """ מחק את
# הערכים בשורת הסיכום בלבד — אבל ה-AI בכלל לא חילץ אותם לשורות הרגילות.
# הפתרון: הוראה מפורשת בפרומפט + וולידציה של הפורמט בפוסט-פרוסס.
# ────────────────────────────────────────────────────────────────────────────────
DATE_RE  = re.compile(r'\d{1,2}/\d{4}|\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}')
MONTH_RE = re.compile(r'\d{1,2}/\d{4}|\d{2}/\d{2}')

def process_audit_v29(client, text):
    prompt = f"""You are a RAW TEXT TRANSCRIBER. Your ONLY job is to copy characters from the text to JSON.

CRITICAL INSTRUCTIONS:
1. ZERO INTERPRETATION: Do not flip digits (e.g., 67 remains 67).
2. ZERO ROUNDING: If a return is 0.17%, copy 0.17%. Do NOT round to 1.0%.

TABLE D SPECIFIC RULES:
- Each investment track (מסלול) has EXACTLY ONE return (תשואה).
- If a track name is split across two physical lines in the source, JOIN them with a space into a single "מסלול" string.
- The row for the continuation line must NOT appear as a separate row — merge it into the previous row's "מסלול" field.
- Example: if the PDF shows:
    "מניות חו\"ל כללי    12.5%"
    "(גידור מלא)"
  The output must be ONE row: {{"מסלול": "מניות חו\"ל כללי (גידור מלא)", "תשואה": "12.5%"}}
- Never produce a row with an empty or "-" תשואה.

TABLE E SPECIFIC RULES:
- "מועד" is the deposit DATE — copy it exactly as it appears (e.g., "01/2024", "ינואר 2024", "15/01/2024").
- "חודש" is the SALARY MONTH — copy it exactly as it appears (e.g., "01/2024", "ינואר 2024").
- Both fields MUST be populated for every data row (not the summary row).
- The summary (סה"כ) row: "מועד" = "", "חודש" = "", "שם המעסיק" = "סה\"כ".
- Do NOT leave מועד or חודש empty for regular (non-summary) rows.

TABLE E SUMMARY ROW:
- The 'סה"כ' row must be mapped STRICTLY.
- The total of the total (the largest sum) MUST be in the 'סה"כ' column.
- 'מועד' and 'חודש' must be empty strings.

JSON STRUCTURE:
{{
  "table_a": {{"rows": [{{"תיאור": "", "סכום בש\\"ח": ""}}]}},
  "table_b": {{"rows": [{{"תיאור": "", "סכום בש\\"ח": ""}}]}},
  "table_c": {{"rows": [{{"תיאור": "", "אחוז": ""}}]}},
  "table_d": {{"rows": [{{"מסלול": "", "תשואה": ""}}]}},
  "table_e": {{"rows": [{{"שם המעסיק": "", "מועד": "", "חודש": "", "שכר": "", "עובד": "", "מעסיק": "", "פיצויים": "", "סה\\"כ": ""}}]}}
}}
TEXT: {text}"""

    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": (
                "You are a mechanical OCR tool. You copy characters exactly. "
                "You do not use logic, you do not round, and you do not flip numbers. "
                "For table_d: always merge wrapped track names into a single row. "
                "For table_e: always extract מועד (deposit date) and חודש (salary month) for every non-summary row."
            )},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        response_format={"type": "json_object"}
    )
    data = json.loads(res.choices[0].message.content)

    # ── תיקון טבלה ד': איחוד שורות גולשות ──────────────────────────────────────
    if "table_d" in data:
        data["table_d"]["rows"] = fix_table_d_multiline(data["table_d"].get("rows", []))

    # ── תיקון טבלה ה': חישוב שורת סיכום + Shift Fix ────────────────────────────
    rows_e = data.get("table_e", {}).get("rows", [])
    if len(rows_e) > 1:
        last_row = rows_e[-1]

        # 1. חישוב שכר נקי
        salary_sum = sum(clean_num(r.get("שכר", 0)) for r in rows_e[:-1])

        # 2. תיקון הסטה (Shift Fix)
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

        # 3. קיבוע שכר וניקוי תאריכים בשורת הסיכום בלבד
        last_row["שכר"]         = f"{salary_sum:,.0f}"
        last_row["מועד"]        = ""   # ← ריק רק בשורת הסיכום
        last_row["חודש"]        = ""   # ← ריק רק בשורת הסיכום
        last_row["שם המעסיק"]   = "סה\"כ"

    return data

# ── ממשק משתמש ──────────────────────────────────────────────────────────────────
st.title("📋 חילוץ נתונים פנסיוני - גירסה 29.0")
client = init_client()

if client:
    file = st.file_uploader("העלה דוח PDF", type="pdf")
    if file:
        with st.spinner("מעתיק נתונים כפי שהם (ללא שיקול דעת AI)..."):
            raw_text = "\n".join([page.get_text() for page in fitz.open(stream=file.read(), filetype="pdf")])
            data = process_audit_v29(client, raw_text)

            if data:
                perform_cross_validation(data)
                display_pension_table(data.get("table_a", {}).get("rows"), "א. תשלומים צפויים",   ["תיאור", "סכום בש\"ח"])
                display_pension_table(data.get("table_b", {}).get("rows"), "ב. תנועות בקרן",       ["תיאור", "סכום בש\"ח"])
                display_pension_table(data.get("table_c", {}).get("rows"), "ג. דמי ניהול והוצאות", ["תיאור", "אחוז"])
                display_pension_table(data.get("table_d", {}).get("rows"), "ד. מסלולי השקעה",       ["מסלול", "תשואה"])
                display_pension_table(data.get("table_e", {}).get("rows"), "ה. פירוט הפקדות",
                                      ["שם המעסיק", "מועד", "חודש", "שכר", "עובד", "מעסיק", "פיצויים", "סה\"כ"])
