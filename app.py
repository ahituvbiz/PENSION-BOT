import streamlit as st
import google.generativeai as genai
import pypdf

# --- הגדרת המפתח שלך ---
API_KEY = "AIzaSyBrvKibfRFWjnmSm4LTFHtaqLEoZZVcrgU"
genai.configure(api_key=API_KEY)

st.set_page_config(page_title="בודק הפנסיה - pensya.info", layout="centered")
st.title("🔍 בודק דמי ניהול אוטומטי")
st.write("העלה דוח שנתי או רבעוני (PDF)")

file = st.file_uploader("בחר קובץ PDF", type=['pdf'])

if file:
    st.info("מנתח נתונים, אנא המתן...")
    try:
        # 1. חילוץ טקסט עצמאי מה-PDF
        reader = pypdf.PdfReader(file)
        full_text = ""
        for page in reader.pages:
            content = page.extract_text()
            if content:
                full_text += content
        
        if not full_text.strip():
            st.error("לא הצלחתי לקרוא טקסט מהקובץ. נסה להעלות צילום מסך במקום.")
        else:
            # 2. שליחת הטקסט כהודעה פשוטה (String) למודל
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            prompt = f"""
            משימה: מצא את דמי הניהול בטקסט המצורף מהדוח הפנסיוני.
            
            תנאי סף לבדיקה:
            - דמי ניהול מהפקדה: מעל 1% זה גבוה.
            - דמי ניהול מצבירה: מעל 0.145% זה גבוה.
            
            החזר תשובה בעברית הכוללת:
            1. האם דמי הניהול 'גבוהים', 'סבירים' או 'מעולים'.
            2. האחוזים המדויקים שמצאת בדו"ח.
            
            הטקסט לניתוח:
            {full_text}
            """
            
            # פקודה זו שולחת טקסט בלבד, ולכן לא תייצר שגיאת 404 של קבצים
            response = model.generate_content(prompt)
            
            st.success("תוצאת הבדיקה:")
            st.write(response.text)
            
    except Exception as e:
        st.error(f"אירעה שגיאה: {e}")
