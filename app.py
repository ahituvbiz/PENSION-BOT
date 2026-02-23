import streamlit as st
import fitz
import json
import os
import pandas as pd
from openai import OpenAI

# הגדרות עמוד
st.set_page_config(page_title="חילוץ נתוני פנסיה", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;700&display=swap');
    * { font-family: 'Assistant', sans-serif; direction: rtl; text-align: right; }
    .stTable { direction: rtl !important; }
    .status-box { padding: 10px; border-radius: 5px; margin-bottom: 10px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

def init_openai():
    api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        st.error("❌ מפתח API חסר.")
        return None
    return OpenAI(api_key=api_key)

def extract_text(file):
    file.seek(0)
    doc = fitz.open(stream=file.read(), filetype="pdf")
    return "\n".join([page.get_text() for page in doc])

def display_custom_table(data_list, title):
    """מציג טבלה עם אינדקס מותאם: כותרת=0, שורה ראשונה=1"""
    if not data_list:
        st.info(f"לא נמצאו נתונים עבור {title}")
        return
    
    df = pd.DataFrame(data_list)
    # יצירת אינדקס שמתחיל ב-1 (הכותרת נחשבת כ-0 בעיני המשתמש)
    df.index = range(1, len(df) + 1)
    st.subheader(f"{title} (שורה 0 = כותרת)")
    st.table(df)

def validate_data(data):
    """ביצוע חישובי אימות לטבלאות ב' וה'"""
    report = []
    
    # אימות טבלה ב'
    rows_b = data.get("table_b", {}).get("rows", [])
    if len(rows_b) > 1:
        # סכימת כל השורות פרט לאחרונה (יתרת סיום)
        vals = [float(str(r.get("value", 0)).replace(",", "").replace("−", "-")) for r in rows_b[:-1]]
        total_calc = sum(vals)
        total_rep = float(str(rows_b[-1].get("value", 0)).replace(",", "").replace("−", "-"))
        if abs(total_calc - total_rep) < 2:
            report.append("✅ טבלה ב': האימות המתמטי עבר בהצלחה.")
        else:
            report.append(f"⚠️ טבלה ב': סטייה בחישוב (צפוי: {total_rep}, חושב: {total_calc:.0f})")

    # אימות טבלה ה'
    rows_e = data.get("table_e", {}).get("rows", [])
    totals_e = data.get("table_e", {}).get("totals", {})
    if rows_e:
        sum_e = sum(float(str(r.get("total", 0)).replace(",", "")) for r in rows_e)
        rep_e = float(str(totals_e.get("total", 0)).replace(",", ""))
        if abs(sum_e - rep_e) < 2:
            report.append("✅ טבלה ה': סך ההפקדות תואם לסיכום השורות.")
        else:
            report.append(f"⚠️ טבלה ה': סטייה בסיכום (צפוי: {rep_e}, חושב: {sum_e:.0f})")
            
    return report

def process_ai(client, text):
    prompt = f"""Extract ALL pension tables into JSON. 
    IMPORTANT:
    1. Table C: Ignore the sidebar with averages (1.26%, 0.13%). Extract ONLY the personal rates (1.49%, 0.10%).
    2. Table D: Must include investment tracks and returns.
    3. Table E: Must include all 7 columns: deposit_date, salary_month, salary, employee, employer, severance, total.
    4. Table E Totals: Extract the summary row separately as "totals".

    JSON STRUCTURE:
    {{
      "report_info": {{"fund": "", "period": ""}},
      "table_a": {{"rows": [{{"תיאור": "", "סכום": ""}}]}},
      "table_b": {{"rows": [{{"תיאור": "", "value": ""}}]}},
      "table_c": {{"rows": [{{"תיאור": "", "אחוז": ""}}]}},
      "table_d": {{"rows": [{{"מסלול": "", "תשואה": ""}}]}},
      "table_e": {{
          "rows": [{{ "מועד": "", "חודש": "", "שכר": "", "עובד": "", "מעסיק": "", "פיצויים": "", "total": "" }}],
          "totals": {{ "employee": "", "employer": "", "severance": "", "total": "" }}
      }}
    }}
    TEXT: {text}"""
    
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": "You are a precise financial parser. Return JSON only."},
                  {"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

# ממשק משתמש
st.title("📋 חילוץ נתונים פנסיוני - גרסה מתוקנת")
client = init_openai()

if client:
    file = st.file_uploader("העלה דוח PDF", type="pdf")
    if file:
        with st.spinner("מנתח נתונים ומבצע אימותים..."):
            raw_text = extract_text(file)
            data = process_ai(client, raw_text)
            
            # הצגת דוחות אימות
            validation_notes = validate_data(data)
            for note in validation_notes:
                color = "#dcfce7" if "✅" in note else "#fee2e2"
                st.markdown(f'<div class="status-box" style="background:{color}">{note}</div>', unsafe_allow_html=True)
            
            # הצגת הטבלאות עם המספור המבוקש
            display_custom_table(data.get("table_a", {}).get("rows"), "א. תשלומים צפויים")
            display_custom_table(data.get("table_b", {}).get("rows"), "ב. תנועות בקרן")
            display_custom_table(data.get("table_c", {}).get("rows"), "ג. דמי ניהול (אישי בלבד)")
            display_custom_table(data.get("table_d", {}).get("rows"), "ד. מסלולי השקעה")
            display_custom_table(data.get("table_e", {}).get("rows"), "ה. פירוט הפקדות (7 עמודות)")
            
            # הצגת שורת הסיכום של טבלה ה' שביקשת
            st.subheader("סיכום טבלה ה' (מתוך הקובץ)")
            st.json(data.get("table_e", {}).get("totals", {}))
            
            st.download_button("הורד JSON מלא", json.dumps(data, indent=2, ensure_ascii=False), "pension_data.json")
