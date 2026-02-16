import streamlit as st
import google.generativeai as genai

# --- הגדרת המפתח שלך ---
# וודא שהמפתח שלך נשאר בתוך המרכאות
API_KEY = "AIzaSyBrvKibfRFWjnmSm4LTFHtaqLEoZZVcrgU"

genai.configure(api_key=API_KEY)

st.set_page_config(page_title="בודק הפנסיה - pensya.info", layout="centered")
st.title("🔍 בודק דמי ניהול אוטומטי")
st.write("העלה צילום מסך או קובץ PDF של טבלת דמי הניהול מהדוח")

file = st.file_uploader("בחר קובץ (PDF או תמונה)", type=['png', 'jpg', 'jpeg', 'pdf'])

if file:
    st.info("מנתח נתונים, אנא המתן...")
    try:
        # תיקון השגיאה: שימוש בשם המודל המדויק ללא גרסאות בטא
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        doc_data = file.read()
        
        prompt = """
        Analyze the management fees (דמי ניהול) in the attached document:
        1. From deposit (הפקדה) - threshold is 1%.
        2. From accumulation (צבירה) - threshold is 0.145%.
        
        Return the answer in Hebrew:
        - If both are above threshold: 'דמי הניהול גבוהים'
        - If only one is above: 'דמי הניהול סבירים'
        - If both are below/equal: 'דמי הניהול מעולים'
        Include the exact percentages you found.
        """
        
        # שליחה ל-Gemini
        response = model.generate_content([
            prompt,
            {"mime_type": file.type, "data": doc_data}
        ])
        
        st.success("הנה הניתוח המהיר:")
        st.write(response.text)
        
    except Exception as e:
        st.error(f"אירעה שגיאה בניתוח הקובץ: {e}")
