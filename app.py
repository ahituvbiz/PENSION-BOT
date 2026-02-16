import streamlit as st
import google.generativeai as genai
import pypdf

# --- הגדרת המפתח שלך ---
API_KEY = "AIzaSyBrvKibfRFWjnmSm4LTFHtaqLEoZZVcrgU"
genai.configure(api_key=API_KEY)

st.set_page_config(page_title="בודק הפנסיה - pensya.info", layout="centered")
st.title("🔍 בודק דמי ניהול אוטומטי")
st.write("העלה דוח שנתי או רבעוני (PDF או תמונה)")

file = st.file_uploader("בחר קובץ", type=['png', 'jpg', 'jpeg', 'pdf'])

if file:
    st.info("מנתח נתונים, אנא המתן...")
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        content_to_analyze = []
        
        if file.type == "application/pdf":
            # קריאת טקסט מתוך ה-PDF בצורה ישירה
            reader = pypdf.PdfReader(file)
            text = ""
            for page in reader.pages:
                text += page.extract_text()
            content_to_analyze.append(f"נתח את נתוני דמי הניהול מהטקסט הבא:\n\n{text}")
        else:
            # טיפול בתמונה
            from PIL import Image
            img = Image.open(file)
            content_to_analyze.append("נתח את דמי הניהול בתמונה המצורפת:")
            content_to_analyze.append(img)

        prompt = """
        משימה: מצא את דמי הניהול בדו"ח.
        1. דמי ניהול מהפקדה (מעל 1% זה גבוה).
        2. דמי ניהול מצבירה (מעל 0.145% זה גבוה).
        
        החזר תשובה בעברית: האם הם גבוהים, סבירים או מעולים, ופרט את האחוזים שמצאת.
        """
        
        content_to_analyze.insert(0, prompt)
        response = model.generate_content(content_to_analyze)
        
        st.success("תוצאת הבדיקה:")
        st.write(response.text)
        
    except Exception as e:
        st.error(f"שגיאה בניתוח: {e}")
