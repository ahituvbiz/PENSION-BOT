import streamlit as st
import google.generativeai as genai
import pypdf

# אבטחה: משיכת המפתח
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    # שינוי קריטי: הגדרת ה-API כך שיעבוד במסלול היציב ביותר
    genai.configure(api_key=API_KEY)
except Exception:
    st.error("שגיאה: מפתח ה-API לא נמצא בכספת (Secrets).")
    st.stop()

st.set_page_config(page_title="בודק הפנסיה - pensya.info", layout="centered")
st.title("🔍 בודק דמי ניהול אוטומטי")
st.write("העלה דוח פנסיוני בפורמט PDF")

file = st.file_uploader("בחר קובץ PDF", type=['pdf'])

if file:
    st.info("מנתח נתונים, אנא המתן...")
    try:
        # חילוץ טקסט
        reader = pypdf.PdfReader(file)
        full_text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t: full_text += t
        
        if len(full_text.strip()) < 50:
            st.error("לא הצלחתי לקרוא טקסט מהקובץ.")
        else:
            # שינוי קריטי 2: שימוש במודל ללא תוספות מיותרות
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            prompt = f"נתח את דמי הניהול מהפקדה וצבירה בטקסט הבא והחזר תשובה בעברית: האם הם גבוהים (מעל 1% הפקדה, מעל 0.145% צבירה)?\n\nטקסט:\n{full_text[:10000]}"
            
            # הכרחת המערכת להשתמש בשיטה הפשוטה ביותר
            response = model.generate_content(prompt)
            
            st.success("תוצאת הניתוח:")
            st.write(response.text)
            
    except Exception as e:
        # אם יש שגיאת 404, אנחנו נציג אותה וננסה להבין למה
        st.error(f"אירעה שגיאה: {e}")
