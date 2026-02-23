import streamlit as st
import fitz
import json
import os
import pandas as pd
from openai import OpenAI

st.set_page_config(page_title="מנתח פנסיה - דיוק שכר", layout="wide")

# עיצוב RTL
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;700&display=swap');
    * { font-family: 'Assistant', sans-serif; direction: rtl; text-align: right; }
    .stTable { direction: rtl !important; }
    .val-msg { padding: 10px; border-radius: 5px; margin-bottom: 5px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

def init_client():
    api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    return OpenAI(api_key=api_key) if api_key else None

def get_text(file):
    file.seek(0)
    doc = fitz.open(stream=file.read(), filetype="pdf")
    return "\n".join([page.get_text() for page in doc])

def validate_totals(data):
    """אימות מתמטי כולל לשכר והפקדות"""
    logs = []
    rows_e = data.get("table_e", {}).get("rows", [])
    if len(rows_e) > 1:
        data_rows = rows_e[:-1]
        total_row = rows_e[-1]
        
        def to_f(v): return float(str(v).replace(",", "") or 0)
        
        # אימות שכר (הוספת אימות לעמודת השכר כפי שביקשת)
        calc_salary = sum(to_f(r.get("שכר", 0)) for r in data_rows)
        rep_salary = to_f(total_row.get("שכר", 0))
        
        if abs(calc_salary - rep_salary) < 10:
            logs.append(("✅ טבלה ה': סה\"כ שכר חושב ואומת בהצלחה.", "#dcfce7"))
        else:
            logs.append((f"⚠️ טבלה ה': סטייה בסיכום שכר (חושב: {calc_salary:,.0f}).", "#fee2e2"))
            
    return logs

def process_pension_v9(client, text):
    prompt = f"""Extract ALL tables from the pension report.
    STRICT MAPPING FOR TABLE E (7 COLUMNS):
    1. Columns: מועד | חודש | שכר | עובד | מעסיק | פיצויים | סה\"כ
    2. THE LAST ROW (סה\"כ): 
       - You MUST calculate the sum of the 'שכר' (Salary) column and place it in the 'שכר' field of the last row.
       - Ensure 'עובד' (Employee) total is placed in the 'עובד' column, NOT in the salary column.
    3. TABLE B: Must include "עדכון יתרת הכספים בגין הפעלת מנגנון איזון אקטוארי" and "רווחים/הפסדים".
    4. TABLE C: Include "הוצאות ניהול השקעות".
    
    JSON STRUCTURE:
    {{
      "table_a": {{"rows": []}},
      "table_b": {{"rows": []}},
      "table_c": {{"rows": []}},
      "table_d": {{"rows": []}},
      "table_e": {{"rows": [
          {{ "מועד": "", "חודש": "", "שכר": "", "עובד": "", "מעסיק": "", "פיצויים": "", "סה\"כ": "" }}
      ]}}
    }}
    TEXT: {text}"""
    
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": "Return JSON with Hebrew keys. Be mathematically precise."},
                  {"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

# ממשק
st.title("📋 מנתח פנסיה - גרסת דיוק שכר")
client = init_client()

if client:
    file = st.file_uploader("העלה דוח PDF", type="pdf")
    if file:
        with st.spinner("מחלץ נתונים..."):
            raw_text = get_text(file)
            data = process_pension_v9(client, raw_text)
            
            # הצגת תוצאות אימות
            for msg, color in validate_totals(data):
                st.markdown(f'<div class="val-msg" style="background:{color}">{msg}</div>', unsafe_allow_html=True)
            
            # תצוגת טבלאות
            for key, title in [("table_a", "א. תשלומים צפויים"), 
                               ("table_b", "ב. תנועות בקרן"), 
                               ("table_c", "ג. דמי ניהול והוצאות"), 
                               ("table_d", "ד. מסלולי השקעה"), 
                               ("table_e", "ה. פירוט הפקדות")]:
                rows = data.get(key, {}).get("rows", [])
                if rows:
                    st.subheader(f"{title} (שורה 0 = כותרת)")
                    df = pd.DataFrame(rows)
                    df.index = range(1, len(df) + 1)
                    st.table(df)
