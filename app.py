import streamlit as st
import google.generativeai as genai
import pypdf

# --- הגדרת המפתח שלך ---
# החלף את הטקסט במרכאות במפתח ה-API האמיתי שלך
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
        
        # זיהוי סוג הקובץ וקריאת התוכן
        if file.type == "application/pdf":
            # קריאת טקסט ישירות מה-PDF - עוקף את שגיאת ה-404
            reader = pypdf.PdfReader(file)
            pdf_text = ""
            for page in reader.pages:
                pdf_text += page.extract_text()
            
            prompt = f"מתוך הטקסט הבא של דוח פנסיוני, מצא את דמי הניהול מהפקדה ומצבירה. אם דמי הניהול מהפקדה מעל 1% או מצבירה מעל 0.145%, ציין שהם גבוהים. החזר תשובה בעברית הכוללת את המספרים שנמצאו:\n\n{pdf_text}"
            response = model.generate_content(prompt)
        else:
            # טיפול בתמונה (צילום מסך)
            from PIL import Image
            img = Image.open(file)
            prompt = "נתח את דמי הניהול בתמונה המצורפת: הפקדה (מעל 1% זה גבוה) וצבירה (מעל 0.145% זה גבוה). החזר תשובה בעברית עם האחוזים שמצאת."
            response = model.generate_content([prompt, img])
        
        st.success("תוצאת הבדיקה:")
        st.write(response.text)
        
    except Exception as e:
        st.error(f"שגיאה בניתוח: {e}")
