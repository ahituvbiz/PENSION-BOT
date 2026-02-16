import streamlit as st
import google.generativeai as genai
import pypdf

# הגדרות עמוד
st.set_page_config(
    page_title="בודק הפנסיה - pensya.info", 
    layout="centered",
    page_icon="🔍"
)

# אבטחה: משיכת המפתח
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
except Exception as e:
    st.error("⚠️ שגיאה: מפתח ה-API לא נמצא בכספת (Secrets).")
    st.info("וודא שהוספת את המפתח GEMINI_API_KEY ב-Streamlit Secrets")
    st.stop()

# כותרת ומידע
st.title("🔍 בודק דמי ניהול אוטומטי")
st.write("העלה דוח פנסיוני בפורמט PDF לניתוח מהיר של דמי הניהול")

with st.expander("ℹ️ מה הסטנדרטים?"):
    st.write("""
    **דמי ניהול תקינים:**
    - 🏦 מהפקדה: עד 1.0%
    - 💰 על צבירה: עד 0.145% בשנה
    
    דמי ניהול גבוהים יכולים לשחוק עשרות אלפי שקלים מהפנסיה לאורך שנים!
    """)

# העלאת קובץ
file = st.file_uploader("📄 בחר קובץ PDF", type=['pdf'])

@st.cache_data
def extract_pdf_text(pdf_file):
    """חילוץ טקסט מ-PDF עם cache"""
    reader = pypdf.PdfReader(pdf_file)
    full_text = ""
    for page in reader.pages:
        t = page.extract_text()
        if t: 
            full_text += t + "\n"
    return full_text

def analyze_with_gemini(text):
    """ניתוח הטקסט עם Gemini"""
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    
    prompt = f"""אתה מומחה לניתוח דוחות פנסיה ישראליים.

נתח את הדוח הבא וחלץ בדיוק:
1. **דמי ניהול מהפקדה** (באחוזים) - חפש ביטויים כמו "דמי ניהול מהפקדה", "עמלת הפקדה"
2. **דמי ניהול על צבירה** (באחוזים שנתיים) - חפש ביטויים כמו "דמי ניהול על צבירה", "עמלה שנתית"

**סטנדרטים לבדיקה:**
- דמי ניהול מהפקדה: מעל 1.0% = גבוה
- דמי ניהול על צבירה: מעל 0.145% = גבוה

**פורמט התשובה (חובה):**

### 📊 התוצאות שמצאתי:
- דמי ניהול מהפקדה: [X]%
- דמי ניהול על צבירה: [Y]%

### ⚖️ הערכה:
[האם הדמי הניהול גבוהים/סבירים/נמוכים ביחס לסטנדרט]

### 💡 המלצה:
[המלצה קצרה - 1-2 משפטים]

---

**טקסט הדוח:**
{text[:15000]}"""
    
    response = model.generate_content(prompt)
    return response.text

if file:
    try:
        with st.spinner("🔄 מנתח את הדוח... אנא המתן"):
            # חילוץ טקסט
            full_text = extract_pdf_text(file)
            
            # בדיקת תקינות
            if not full_text or len(full_text.strip()) < 50:
                st.error("❌ לא הצלחתי לקרוא טקסט מהקובץ.")
                st.warning("""
                **סיבות אפשריות:**
                - הקובץ מוצפן או מוגן
                - הקובץ הוא תמונה סרוקה (לא PDF טקסטואלי)
                - הקובץ פגום
                
                💡 נסה להמיר את הקובץ או להוריד מחדש מהבנק/חברת הפנסיה
                """)
                st.stop()
            
            # ניתוח עם Gemini
            analysis = analyze_with_gemini(full_text)
            
            # הצגת תוצאות
            st.success("✅ הניתוח הושלם!")
            st.markdown(analysis)
            
            # כפתור להורדת התוצאות
            st.download_button(
                label="📥 הורד תוצאות",
                data=analysis,
                file_name="pension_analysis.txt",
                mime="text/plain"
            )
            
    except Exception as e:
        error_msg = str(e)
        
        # טיפול חכם בשגיאות
        if "404" in error_msg:
            st.error("❌ שגיאת 404: המודל לא נמצא")
            st.info("בדוק את שם המודל או את תקינות מפתח ה-API")
        elif "quota" in error_msg.lower() or "resource" in error_msg.lower():
            st.error("❌ חריגה מהמכסה היומית של Gemini API")
            st.info("המתן מספר דקות או השתמש במפתח API אחר")
        elif "api" in error_msg.lower():
            st.error(f"❌ שגיאת API: {error_msg}")
            st.info("ייתכן שהמפתח אינו תקף או שהשירות אינו זמין כרגע")
        else:
            st.error(f"❌ אירעה שגיאה: {error_msg}")
            
        # הצגת פרטים טכניים במצב debug
        with st.expander("🔧 פרטים טכניים (למפתחים)"):
            st.code(error_msg)

# כותרת תחתונה
st.markdown("---")
st.caption("🏦 פותח על ידי pensya.info | שימו לב: זהו כלי עזר בלבד ואינו מהווה ייעוץ פנסיוני")
