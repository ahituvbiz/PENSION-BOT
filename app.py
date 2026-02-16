import streamlit as st
import google.generativeai as genai
import pypdf

# הגדרת המפתח
API_KEY = "AIzaSyBrvKibfRFWjnmSm4LTFHtaqLEoZZVcrgU"
genai.configure(api_key=API_KEY)

st.set_page_config(page_title="בודק הפנסיה - pensya.info", layout="centered")
st.title("🔍 בודק דמי ניהול אוטומטי")
st.write("העלה דוח פנסיוני בפורמט PDF")

file = st.file_uploader("בחר קובץ PDF", type=['pdf'])

if file:
    st.info("מנתח נתונים, אנא המתן...")
    try:
        # 1. חילוץ טקסט מה-PDF אצלנו (כדי למנוע שגיאות API)
        reader = pypdf.PdfReader(file)
        full_text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t: full_text += t
        
        if len(full_text) < 50:
            st.error("לא הצלחתי לקרוא טקסט מהקובץ. וודא שזה דוח דיגיטלי ולא סריקה.")
        else:
            # 2. שימוש במודל בגרסה הכי יציבה שלו
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            # בניית פרומפט ששולח רק טקסט
            prompt = f"""
            אתה מומחה פנסיוני. נתח את דמי הניהול מהטקסט הבא:
            1. דמי ניהול מהפקדה (תקרה מומלצת: 1%)
            2. דמי ניהול מצבירה (תקרה מומלצת: 0.145%)
            
            החזר תשובה בעברית: האם דמי הניהול גבוהים/סבירים/מעולים ומהם האחוזים שמצאת.
            
            הטקסט לניתוח:
            {full_text[:15000]}
            """
            
            # שליחה כטקסט פשוט - זה עוקף את שגיאת ה-404 של v1beta
            response = model.generate_content(prompt)
            
            st.success("תוצאת הבדיקה:")
            st.write(response.text)
            
    except Exception as e:
        # אם בכל זאת יש שגיאה, נדפיס אותה בצורה ברורה
        st.error(f"אירעה שגיאה: {e}")
