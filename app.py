import streamlit as st
import fitz
import json
import os
import pandas as pd
import re
from openai import OpenAI

# הגדרות RTL ועיצוב קשיח
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
    if val is None or val == "" or str(val).strip() in ["-", "nan", ".", "0"]:
        return 0.0
    try:
        cleaned = re.sub(r'[^\d\.\-]', '', str(val).replace(",", "").replace("−", "-"))
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0

def perform_cross_validation(data):
    dep_b = 0.0
    for r in data.get("table_b", {}).get("rows", []):
        row_str = " ".join(str(v) for v in r.values())
        if any(kw in row_str for kw in ["הופקדו", "כספים שהופקדו"]):
            nums = [clean_num(v) for v in r.values() if clean_num(v) > 10]
            if nums:
                dep_b = nums[0]
            break

    rows_e = data.get("table_e", {}).get("rows", [])
    dep_e = clean_num(rows_e[-1].get("סה\"כ", 0)) if rows_e else 0.0

    if abs(dep_b - dep_e) < 5 and dep_e > 0:
        st.markdown(f'<div class="val-success">✅ אימות הצלבה עבר: סכום ההפקדות ({dep_e:,.2f} ₪) תואם.</div>', unsafe_allow_html=True)
    elif dep_e > 0:
        st.markdown(f'<div class="val-error">⚠️ שגיאת אימות: טבלה ב\' ({dep_b:,.2f} ₪) לעומת טבלה ה\' ({dep_e:,.2f} ₪).</div>', unsafe_allow_html=True)

def display_pension_table(rows, title, col_order):
    if not rows:
        return
    df = pd.DataFrame(rows)
    existing = [c for c in col_order if c in df.columns]
    df = df[existing]
    df.index = range(1, len(df) + 1)
    st.subheader(title)
    st.table(df)

def process_audit_v29(client, text):
    prompt = f"""You are a RAW TEXT TRANSCRIBER. Your ONLY job is to copy characters from the text to JSON.

CRITICAL:
1. ZERO INTERPRETATION
2. ZERO ROUNDING
3. COPY NUMBERS EXACTLY AS THEY APPEAR
4. DO NOT FLIP DIGITS

JSON STRUCTURE:
{{
  "table_a": {{"rows": [{{"תיאור": "", "סכום בש\"ח": ""}}]}},
  "table_b": {{"rows": [{{"תיאור": "", "סכום בש\"ח": ""}}]}},
  "table_c": {{"rows": [{{"תיאור": "", "אחוז": ""}}]}},
  "table_d": {{"rows": [{{"מסלול": "", "תשואה": ""}}]}},
  "table_e": {{"rows": [{{ "שם המעסיק": "", "מועד": "", "חודש": "", "שכר": "", "עובד": "", "מעסיק": "", "פיצויים": "", "סה\"כ": "" }}]}}
}}

TEXT:
{text}
"""

    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You copy characters exactly. No logic."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        response_format={"type": "json_object"}
    )

    data = json.loads(res.choices[0].message.content)

    # =========================
    # FIX 1 — Merge multiline track names (Table D)
    # =========================
    rows_d = data.get("table_d", {}).get("rows", [])
    merged_rows = []
    i = 0

    while i < len(rows_d):
        row = rows_d[i]
        track = str(row.get("מסלול", "")).strip()
        ret = str(row.get("תשואה", "")).strip()

        if (ret == "" or ret == "-") and i > 0:
            merged_rows[-1]["מסלול"] = (
                merged_rows[-1]["מסלול"].rstrip() + " " + track
            ).strip()
            i += 1
            continue

        merged_rows.append({
            "מסלול": track,
            "תשואה": ret
        })
        i += 1

    data["table_d"]["rows"] = merged_rows

    # =========================
    # FIX 2 — Numeric direction alignment using Table C
    # =========================
    def reverse_decimal_str(num_str):
        if "." in num_str:
            p = num_str.split(".")
            if len(p) == 2:
                return p[0] + "." + p[1][::-1]
        return num_str[::-1]

    rows_c = data.get("table_c", {}).get("rows", [])
    flip_required = False

    if len(rows_c) >= 2:
        val_c = str(rows_c[1].get("אחוז", "")).strip()
        match_c = re.search(r'-?\d+\.\d+|-?\d+', val_c)
        if match_c:
            raw_c = match_c.group(0)
            try:
                if float(raw_c) > 0.5:
                    flip_required = True
            except:
                pass

    if flip_required:
        for row in rows_c:
            val = str(row.get("אחוז", "")).strip()
            match = re.search(r'-?\d+\.\d+|-?\d+', val)
            if match:
                row["אחוז"] = reverse_decimal_str(match.group(0))

        for row in data.get("table_d", {}).get("rows", []):
            val = str(row.get("תשואה", "")).strip()
            match = re.search(r'-?\d+\.\d+|-?\d+', val)
            if match:
                row["תשואה"] = reverse_decimal_str(match.group(0))

    return data


# =========================
# UI
# =========================

st.title("📋 חילוץ נתונים פנסיוני - גירסה 29.0")
client = init_client()

if client:
    file = st.file_uploader("העלה דוח PDF", type="pdf")

    if file:
        with st.spinner("חילוץ טקסט ללא פרשנות..."):
            raw_text = "\n".join([
                page.get_text("text", sort=True)
                for page in fitz.open(stream=file.read(), filetype="pdf")
            ])

            data = process_audit_v29(client, raw_text)

            if data:
                perform_cross_validation(data)

                display_pension_table(data.get("table_a", {}).get("rows"),
                                      "א. תשלומים צפויים",
                                      ["תיאור", "סכום בש\"ח"])

                display_pension_table(data.get("table_b", {}).get("rows"),
                                      "ב. תנועות בקרן",
                                      ["תיאור", "סכום בש\"ח"])

                display_pension_table(data.get("table_c", {}).get("rows"),
                                      "ג. דמי ניהול והוצאות",
                                      ["תיאור", "אחוז"])

                display_pension_table(data.get("table_d", {}).get("rows"),
                                      "ד. מסלולי השקעה",
                                      ["מסלול", "תשואה"])

                display_pension_table(data.get("table_e", {}).get("rows"),
                                      "ה. פירוט הפקדות",
                                      ["שם המעסיק", "מועד", "חודש", "שכר",
                                       "עובד", "מעסיק", "פיצויים", "סה\"כ"])
