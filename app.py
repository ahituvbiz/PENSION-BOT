import streamlit as st
import fitz
import json
import os
import pandas as pd
import re
import io
from openai import OpenAI

# הגדרות RTL ועיצוב קשיח
st.set_page_config(page_title="מנתח פנסיה - גרסה 43.0", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;700&display=swap');
    * { font-family: 'Assistant', sans-serif; direction: rtl; text-align: right; }
    .stTable { direction: rtl !important; width: 100%; }
    th, td { text-align: right !important; padding: 10px !important; }
</style>
""", unsafe_allow_html=True)

def init_client():
    api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    return OpenAI(api_key=api_key) if api_key else None

def clean_num(val):
    if val is None or val == "" or str(val).strip() in ["-", "nan", ".", "0"]: return 0.0
    try:
        # ניקוי פסיקים ותווים שאינם ספרות למעט נקודה עשרונית ומינוס
        cleaned = re.sub(r'[^\d\.\-]', '', str(val).replace(",", "").replace("−", "-"))
        return float(cleaned) if cleaned else 0.0
    except: return 0.0

def process_audit_v43(client, text):
    prompt = f"""You are a MECHANICAL SCRIBE. Your ONLY job is to transcribe rows exactly.
    
    STRICT RULES:
    1. DIGIT INTEGRITY: If the text says '50', do NOT write '05'. If it says '11.25', do NOT write '5.21'.
    2. TABLE E EXTRACTION:
       - Extract ONLY individual contribution rows.
       - DO NOT extract the summary (סה"כ) row from the PDF.
       - Map columns: שם המעסיק, מועד הפקדה, עבור חודש, משכורת, עובד, מעסיק, פיצויים, סה"כ.
       - Copy values exactly as they appear in the text.
    3. TABLE D: Copy the track name and return percentage digit-by-digit.
    
    JSON STRUCTURE:
    {{
      "table_a": {{"rows": [{{"תיאור": "", "סכום": ""}}]}},
      "table_b": {{"rows": [{{"תיאור": "", "סכום": ""}}]}},
      "table_c": {{"rows": [{{"תיאור": "", "אחוז": ""}}]}},
      "table_d": {{"rows": [{{"מסלול": "", "תשואה": ""}}]}},
      "table_e": {{"rows": [{{ "שם המעסיק": "", "מועד": "", "חודש": "", "שכר": "", "עובד": "", "מעסיק": "", "פיצויים": "", "סה\"כ": "" }}]}}
    }}
    TEXT: {text}"""
    
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": "Mechanical OCR tool. No digit flipping. Focus on individual rows only. No summary extraction."},
                  {"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"}
    )
    data = json.loads(res.choices[0].message.content)
    
    # חישוב שורת סיכום מתמטית ב-Python
    rows_e = data.get("table_e", {}).get("rows", [])
    if rows_e:
        sum_row = {
            "שם המעסיק": "סה\"כ (מחושב)",
            "מועד": "", "חודש": "",
            "שכר": sum(clean_num(r.get("שכר")) for r in rows_e),
            "עובד": sum(clean_num(r.get("עובד")) for r in rows_e),
            "מעסיק": sum(clean_num(r.get("מעסיק")) for r in rows_e),
            "פיצויים": sum(clean_num(r.get("פיצויים")) for r in rows_e),
            "סה\"כ": sum(clean_num(r.get("סה\"כ")) for r in rows_e)
        }
        rows_e.append(sum_row)
    
    return data

# ממשק משתמש
st.title("📋 חילוץ נתונים פנסיוני - גרסה 43.0 (דיוק מתמטי)")
client = init_client()

if client and (file := st.file_uploader("העלה דוח PDF", type="pdf")):
    with st.spinner("מבצע חילוץ וחישוב מחדש..."):
        raw_text = "\n".join([page.get_text() for page in fitz.open(stream=file.read(), filetype="pdf")])
        data = process_audit_v43(client, raw_text)
        
        if data:
            dfs_for_excel = {}
            # מיפוי עמודות שצריכות להישמר כמספרים באקסל
            config = [
                ("A", ["תיאור", "סכום"], ["סכום"]),
                ("B", ["תיאור", "סכום"], ["סכום"]),
                ("C", ["תיאור", "אחוז"], []),
                ("D", ["מסלול", "תשואה"], []),
                ("E", ["שם המעסיק", "מועד", "חודש", "שכר", "עובד", "מעסיק", "פיצויים", "סה\"כ"], ["שכר", "עובד", "מעסיק", "פיצויים", "סה\"כ"])
            ]
            
            for k, cols, num_cols in config:
                rows = data.get(f"table_{k.lower()}", {}).get("rows", [])
                if rows:
                    df = pd.DataFrame(rows)[cols]
                    st.subheader(f"טבלה {k}")
                    st.table(df) # תצוגה
                    
                    # המרה למספרים לקובץ האקסל
                    excel_df = df.copy()
                    for c in num_cols:
                        excel_df[c] = excel_df[c].apply(clean_num)
                    dfs_for_excel[k] = excel_df

            # יצירת אקסל
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                sn = 'דוח ריכוז'
                col_map = {"A": 1, "B": 4, "C": 7, "D": 10, "E": 13}
                for k, start_col in col_map.items():
                    if k in dfs_for_excel:
                        dfs_for_excel[k].to_excel(writer, sheet_name=sn, startcol=start_col, startrow=1, index=False)
                
                workbook, worksheet = writer.book, writer.sheets[sn]
                header_fmt = workbook.add_format({'bold': True, 'align': 'right'})
                for (k, start_col), title in zip(col_map.items(), ["תשלומים", "תנועות", "דמי ניהול", "מסלולים", "הפקדות"]):
                    worksheet.write(0, start_col, title, header_fmt)
                worksheet.right_to_left()

            st.download_button("📥 הורד Excel (מספרים וחישובים)", output.getvalue(), "pension_v43.xlsx")
