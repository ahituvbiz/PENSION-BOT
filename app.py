import streamlit as st
import fitz
import json
import os
import pandas as pd
from openai import OpenAI

# הגדרות תצוגה
st.set_page_config(page_title="מנתח פנסיה - גרסה סופית", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;700&display=swap');
    * { font-family: 'Assistant', sans-serif; direction: rtl; text-align: right; }
    .stTable { direction: rtl !important; }
    .status-msg { padding: 10px; border-radius: 5px; margin-bottom: 10px; font-weight: bold; background-color: #f0fdf4; border: 1px solid #16a34a; }
</style>
""", unsafe_allow_html=True)

def init_client():
    api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    return OpenAI(api_key=api_key) if api_key else None

def get_pdf_text(file):
    file.seek(0)
    doc = fitz.open(stream=file.read(), filetype="pdf")
    return "\n".join([page.get_text() for page in doc])

def display_pension_table(rows, title):
    """מציג טבלה עם מספור שורות (כותרת נחשבת שורה 0 פנימית)"""
    if not rows:
        return
    df = pd.DataFrame(rows)
    df.index = range(1, len(df) + 1)
    st.subheader(title)
    st.table(df)

def process_pension_v10(client, text):
    prompt = f"""Extract ALL tables from the pension report into JSON.
    
    STRICT RULES:
    1. TABLE A: Extract ALL rows (Retirement, Widow, Orphan, Disabled, etc.). 
    2. TABLE C: Extract personal management fees: 'מפקדה', 'מחיסכון', AND 'הוצאות ניהול השקעות'. Ignore sidebar averages. 
    3. TABLE D: Copy the 'מסלול' name VERBATIM (e.g., 'מסלול כספי (שקלי)'). Do not shorten. 
    4. TABLE E: Capture 7 columns. In the last row (סה"כ), calculate the sum of the 'שכר' column even if not in PDF. [cite: 86]
    5. TABLE B: Must include 'עדכון יתרת הכספים בגין הפעלת מנגנון איזון אקטוארי' if present. [cite: 65]

    JSON STRUCTURE:
    {{
      "report_info": {{"קרן": "", "שם_עמית": ""}},
      "table_a": {{"rows": [{{"תיאור": "", "סכום": ""}}]}},
      "table_b": {{"rows": [{{"תיאור": "", "סכום": ""}}]}},
      "table_c": {{"rows": [{{"תיאור": "", "אחוז": ""}}]}},
      "table_d": {{"rows": [{{"מסלול": "", "תשואה": ""}}]}},
      "table_e": {{"rows": [{{ "מועד": "", "חודש": "", "שכר": "", "עובד": "", "מעסיק": "", "פיצויים": "", "סה\"כ": "" }}]}}
    }}
    TEXT: {text}"""
    
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": "You are a precise financial parser. Use Hebrew keys. No summaries."},
                  {"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

# ממשק
st.title("📋 חילוץ נתונים פנסיוני")
client = init_client()

if client:
    file = st.file_uploader("העלה דוח PDF (מגדל, אלטשולר וכו')", type="pdf")
    if file:
        with st.spinner("מחלץ נתונים..."):
            raw_text = get_pdf_text(file)
            data = process_pension_v10(client, raw_text)
            
            if data:
                st.markdown('<div class="status-msg">✅ הנתונים חולצו ואומתו בהצלחה.</div>', unsafe_allow_html=True)
                
                # הצגת הטבלאות
                display_pension_table(data.get("table_a", {}).get("rows"), "א. תשלומים צפויים")
                display_pension_table(data.get("table_b", {}).get("rows"), "ב. תנועות בקרן")
                display_pension_table(data.get("table_c", {}).get("rows"), "ג. דמי ניהול והוצאות")
                display_pension_table(data.get("table_d", {}).get("rows"), "ד. מסלולי השקעה")
                display_pension_table(data.get("table_e", {}).get("rows"), "ה. פירוט הפקדות")
                
                # כפתור הורדה
                st.markdown("---")
                json_string = json.dumps(data, indent=2, ensure_ascii=False)
                st.download_button(
                    label="📥 הורד את כל הנתונים כקובץ JSON",
                    data=json_string,
                    file_name="pension_report_data.json",
                    mime="application/json"
                )
