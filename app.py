import streamlit as st
import fitz  # PyMuPDF
import json
import os
from openai import OpenAI

# הגדרות תצוגה בסיסיות
st.set_page_config(page_title="חילוץ דוח פנסיה", layout="wide")

# הזרקת CSS לתיקון כיווניות (RTL) ומניעת קריסת ממשק
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;700&display=swap');
    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Assistant', sans-serif;
        direction: rtl;
        text-align: right;
    }
    .stTable { direction: rtl !important; }
    .report-card { 
        background-color: #f8fafc; 
        border-right: 5px solid #1e40af; 
        padding: 20px; 
        border-radius: 8px; 
        margin-bottom: 20px;
    }
    div[data-testid="stExpander"] { direction: rtl; }
</style>
""", unsafe_allow_html=True)

def init_openai():
    """אתחול בטוח של ה-Client"""
    api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        st.error("❌ מפתח OPENAI_API_KEY חסר בהגדרות (Secrets).")
        return None
    return OpenAI(api_key=api_key)

def get_pdf_text(uploaded_file):
    """חילוץ טקסט וקטורי - מבטיח דיוק של 100% במספרים לעומת תמונה"""
    text = ""
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        for page in doc:
            # חילוץ לפי בלוקים שומר על הקשר בין כותרות לנתונים
            blocks = page.get_text("blocks")
            for b in blocks:
                text += f"{b[4]}\n"
        doc.close()
        return text
    except Exception as e:
        st.error(f"שגיאה בקריאת ה-PDF: {e}")
        return None

def process_data_with_ai(client, raw_text):
    """שליחת הטקסט ל-AI לעיבוד מבני"""
    prompt = f"""You are a precise Israeli pension data extractor. 
    Analyze the following raw text from a pension report and return ONLY a JSON object.
    
    RULES:
    1. Table B: Include "יתרת פתיחה", "הפקדות", "הפסדים/רווחים" (with - sign if loss), "דמי ניהול", "ביטוח", and "יתרת סיום".
    2. Table E: Extract all deposit rows with exact dates, salary, and components.
    3. Ensure all numbers are strings in the JSON but reflect the exact report values.
    
    REPORT TEXT:
    {raw_text}
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a financial data parser. Return valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        st.error(f"שגיאה בעיבוד הנתונים: {e}")
        return None

# --- גוף האפליקציה ---
st.title("📋 חילוץ נתונים מדוח פנסיה")
st.write("העלה דוח PDF דיגיטלי לקבלת טבלאות נתונים מדויקות.")

client = init_openai()

if client:
    uploaded_file = st.file_uploader("בחר קובץ PDF", type=["pdf"])
    
    if uploaded_file:
        with st.spinner("מחלץ נתונים..."):
            # שלב 1: חילוץ טקסט ישיר מהקובץ
            raw_text = get_pdf_text(uploaded_file)
            
            if raw_text:
                # שלב 2: עיבוד הטקסט ל-JSON
                data = process_data_with_ai(client, raw_text)
                
                if data:
                    st.success("הנתונים חולצו בהצלחה!")
                    
                    # הצגת פרטי הדוח
                    info = data.get("report_info", {})
                    st.markdown(f"""
                    <div class="report-card">
                        <h3>{info.get('fund_name', 'דוח פנסיה')}</h3>
                        <p><b>תקופה:</b> {info.get('report_period', '—')} | <b>תאריך הפקה:</b> {info.get('report_date', '—')}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # טבלאות
                    col1, col2 = st.columns(2)
                    with col1:
                        st.subheader("תשלומים צפויים (טבלה א')")
                        st.table(data.get("table_a", {}).get("rows", []))
                    
                    with col2:
                        st.subheader("תנועות בקרן (טבלה ב')")
                        st.table(data.get("table_b", {}).get("rows", []))
                    
                    st.subheader("פירוט הפקדות (טבלה ה')")
                    st.table(data.get("table_e", {}).get("rows", []))
                    
                    # הורדת JSON
                    st.download_button(
                        "הורד נתונים (JSON)",
                        data=json.dumps(data, indent=2, ensure_ascii=False),
                        file_name="pension_data.json",
                        mime="application/json"
                    )
