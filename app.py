import streamlit as st
import google.generativeai as genai
import google.ai.generativelanguage as gql

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
        # תיקון שגיאת ה-404 על ידי הגדרת גרסת ה-API הנכונה
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        doc_data = file.read()
        
        prompt = """
        נתח את דמי הניהול בטבלה שבמסמך המצורף.
        תנאי הסף שלך הם:
        1. דמי ניהול מהפקדה - מעל 1% נחשב גבוה.
        2. דמי ניהול מצבירה - מעל 0.145% נחשב גבוה.
        
        החזר תשובה בעברית ברורה הכוללת:
        - שורה תחתונה: 'גבוה', 'סביר' או 'מעולה'.
        - מהם האחוזים המדויקים שמצאת עבור הפקדה וצבירה.
        """
        
        # שימוש בגרסת v1beta כדי לאפשר קריאת קבצים ישירה
        response = model.generate_content(
            [
                prompt,
                {"mime_type": file.type, "data": doc_data}
            ],
            generation_config={"top_p": 1, "top_k": 32}
        )
        
        st.success("הנה הניתוח המהיר:")
        st.write(response.text)
        
    except Exception as e:
        # אם יש שגיאה, נציג אותה בצורה ברורה
        st.error(f"אירעה שגיאה: {e}")
        st.info("נסה להעלות צילום מסך (תמונה) במקום PDF אם הבעיה נמשכת.")
