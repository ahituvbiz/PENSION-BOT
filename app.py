import streamlit as st
import google.generativeai as genai
import pypdf

# --- הגדרת אבטחה: משיכת המפתח מהכספת של סטרימליט ---
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
except Exception:
    st.error("שגיאה: מפתח ה-API לא נמצא בכספת (Secrets). אנא הגדר אותו בלוח הבקרה של Streamlit.")
    st.stop()

# עיצוב דף האפליקציה
st.set_page_config(page_title="בודק הפנסיה - pensya.info", layout="centered")
st.title("🔍 בודק דמי ניהול אוטומטי")
st.write("העלה דוח פנסיוני בפורמט PDF (שנתי או רבעוני)")

# העלאת הקובץ
file = st.file_uploader("בחר קובץ PDF", type=['pdf'])

if file:
    st.info("מנתח נתונים, אנא המתן...")
    try:
        # 1. חילוץ טקסט מה-PDF אצלנו בשרת (עוקף שגיאות API של גוגל)
        reader = pypdf.PdfReader(file)
        full_text = ""
        for page in reader.pages:
            content = page.extract_text()
            if content:
                full_text += content
        
        if len(full_text.strip()) < 50:
            st.error("לא הצלחתי לקרוא טקסט מהקובץ. וודא שזהו דוח דיגיטלי (לא סריקה חשוכה) או נסה להעלות דוח אחר.")
        else:
            # 2. הגדרת המודל (גרסה יציבה)
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            # 3. בניית הנחיה (Prompt) מקצועית עבור יועץ פנסיוני
            prompt = f"""
            אתה מומחה פנסיוני אובייקטיבי. לפניך טקסט מתוך דוח שנתי/רבעוני של קופת גמל או פנסיה.
            
            המשימה:
            1. מצא את אחוז דמי הניהול מהפקדה (נקרא גם 'מהתשלומים').
            2. מצא את אחוז דמי הניהול מצבירה (נקרא גם 'מהחיסכון').
            
            כללי הדירוג:
            - דמי ניהול מהפקדה: מעל 1% נחשב גבוה.
            - דמי ניהול מצבירה: מעל 0.145% נחשב גבוה.
            
            החזר תשובה בעברית ברורה:
            - שורה תחתונה: האם דמי הניהול 'מעולים', 'סבירים' או 'גבוהים'.
            - פרט את המספרים המדויקים שמצאת.
            - הוסף המלצה קצרה (למשל: "כדאי להתמקח" או "דמי ניהול מצוינים").
            
            הטקסט לניתוח:
            {full_text[:15000]}
            """
            
            # שליחה כטקסט פשוט כדי למנוע שגיאות 404
            response = model.generate_content(prompt)
            
            st.success("תוצאת הניתוח:")
            st.write(response.text)
            
    except Exception as e:
        st.error(f"אירעה שגיאה בתהליך הניתוח: {e}")

# קרדיט בתחתית
st.markdown("---")
st.caption("הכלי פותח עבור pensya.info - ייעוץ פנסיוני אובייקטיבי")
