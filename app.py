import streamlit as st
import fitz
import json
import os
import pandas as pd
import re
from openai import OpenAI

# הגדרות תצוגה RTL
st.set_page_config(page_title="מנתח פנסיה - גרסת האימות הסופי", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;700&display=swap');
    * { font-family: 'Assistant', sans-serif; direction: rtl; text-align: right; }
    .stTable { direction: rtl !important; }
    .val-success { padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold; background-color: #f0fdf4; border: 1px solid #16a34a; color: #16a34a; }
    .val-error { padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold; background-color: #fef2f2; border: 1px solid #dc2626; color: #dc2626; }
</style>
""", unsafe_allow_html=True)

def init_client():
    api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    return OpenAI(api_key=api_key) if api_key else None

def get_full_pdf_text(file):
    file.seek(0)
    doc = fitz.open(stream=file.read(), filetype="pdf")
    full_text = ""
    for i, page in enumerate(doc):
        full_text += f"--- PAGE {i+1} ---\n" + page.get_text() + "\n"
    return full_text

def clean_num(val):
    """ניקוי מספרים לחישובים מתמטיים"""
    if not val: return 0.0
    return float(re.sub(r'[^\d\.\-]', '', str(val).replace(",", "")))

def perform_cross_validation(data):
    """אימות הצלבה: סה\"כ הפקדות בטבלה ב' מול סה\"כ בטבלה ה'"""
    # 1. חילוץ סכום ההפקדות מטבלה ב'
    rows_b = data.get("table_b", {}).get("rows", [])
    deposit_in_b = 0.0
    for r in rows_b:
        if "הופקדו" in r.get("תיאור", ""):
            deposit_in_b = clean_num(r.get("סכום", 0))
            break
            
    # 2. חילוץ שורת הסה\"כ מטבלה ה'
    rows_e = data.get("table_e", {}).get("rows", [])
    deposit_in_e = 0.0
    if rows_e:
        last_row = rows_e[-1]
        deposit_in_e = clean_num(last_row.get("סה\"כ", 0))
    
    # הצגת התוצאה
    if abs(deposit_in_b - deposit_in_e) < 5:
        st.markdown(f'<div class="val-success">✅ אימות הצלבה עבר: סכום ההפקדות בטבלה ב\' ({deposit_in_b:,.0f} ₪) תואם לסיכום בטבלה ה\'.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="val-error">⚠️ שגיאת הצלבה: סכום ההפקדות בטבלה ב\' ({deposit_in_b:,.0f} ₪) אינו תואם לטבלה ה\' ({deposit_in_e:,.0f} ₪).</div>', unsafe_allow_html=True)

def display_pension_table(rows, title):
    if not rows: return
    df = pd.DataFrame(rows)
    df.index = range(1, len(df) + 1)
    st.subheader(title)
    st.table(df)

def process_with_cross_audit(client, text):
    prompt = f"""Extract ALL tables from the pension report into JSON.
    
    TERMINATION RULE FOR TABLE E:
    - Extract rows sequentially.
    - STOP extraction for Table E immediately after the row that starts with 'סה"כ' (Total).
    - Ignore all rows and sections appearing after the 'סה"כ' row.
    
    CORE REQUIREMENTS:
    - TABLE A: Extract ALL Estimates.
    - TABLE B: Extract ALL rows including Opening Balance, Deposits, and Closing Balance.
    - TABLE C: Include Management Fees and Investment Expenses (הוצאות ניהול השקעות).
    - TABLE D: VERBATIM track name (e.g., 'מסלול כספי שקלי').
    - TABLE E: 7 columns. Calculate 'שכר' total for the 'סה"כ' row.

    JSON STRUCTURE:
    {{
      "table_a": {{"rows": []}},
      "table_b": {{"rows": []}},
      "table_c": {{"rows": []}},
      "table_d": {{"rows": []}},
      "table_e": {{"rows": [{{ "מועד": "", "חודש": "", "שכר": "", "עובד": "", "מעסיק": "", "פיצויים": "", "סה\"כ": "" }}]}}
    }}
    
    TEXT:
    {text}"""
    
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": "You are a forensic financial auditor. Accuracy is 100% required."},
                  {"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

# ממשק
st.title("📋 מנתח פנסיה - גרסת האימות המצליב")
client = init_client()

if client:
    file = st.file_uploader("העלה דוח PDF", type="pdf")
    if file:
        with st.spinner("מחלץ ומאמת נתונים..."):
            raw_text = get_full_pdf_text(file)
            data = process_cross_audit(client, raw_text)
            
            if data:
                # הרצת אימות הצלבה
                perform_cross_validation(data)
                
                # הצגת הטבלאות
                display_pension_table(data.get("table_a", {}).get("rows"), "א. תשלומים צפויים")
                display_pension_table(data.get("table_b", {}).get("rows"), "ב. תנועות בקרן")
                display_pension_table(data.get("table_c", {}).get("rows"), "ג. דמי ניהול והוצאות")
                display_pension_table(data.get("table_d", {}).get("rows"), "ד. מסלולי השקעה")
                display_pension_table(data.get("table_e", {}).get("rows"), "ה. פירוט הפקדות")
                
                st.markdown("---")
                st.download_button("📥 הורד JSON", json.dumps(data, indent=2, ensure_ascii=False), "pension_audit.json")
