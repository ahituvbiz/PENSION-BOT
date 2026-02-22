import streamlit as st
import pypdf
import io
import gc
import re
import json
import hashlib
import time
import math
from openai import OpenAI

# הגדרות עמוד ועיצוב RTL
st.set_page_config(page_title="בודק הפנסיה - pensya.info", layout="centered", page_icon="🔍")

st.markdown("""
<style>
    body, .stApp { direction: rtl; }
    .stRadio > div { direction: rtl; }
    .stRadio label { direction: rtl; text-align: right; }
    .stRadio > div > div { flex-direction: row-reverse; justify-content: flex-start; }
    .stMarkdown, .stText, p, h1, h2, h3, h4, div { text-align: right; }
    .stAlert { direction: rtl; text-align: right; }
</style>
""", unsafe_allow_html=True)

# ─── קבועים ───────────────────────────────────────────
MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_TEXT_CHARS = 15_000
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW_SEC = 3600
PENSION_INTEREST = 0.0386  # 3.86% ריבית לחישובים

# ─── אבטחה וחיבור ─────────────────────────────────────
try:
    API_KEY = st.secrets["OPENAI_API_KEY"]
    client = OpenAI(api_key=API_KEY, default_headers={"OpenAI-No-Store": "true"})
except Exception:
    st.error("⚠️ שגיאה: מפתח ה-API לא נמצא בכספת (Secrets).")
    st.stop()

# ─── פונקציות עזר ──────────────────────────────────────

def _get_client_id():
    headers = st.context.headers if hasattr(st, "context") else {}
    raw_ip = headers.get("X-Forwarded-For", "") or headers.get("X-Real-Ip", "") or "unknown"
    return hashlib.sha256(raw_ip.encode()).hexdigest()[:16]

def is_vector_pdf(pdf_bytes):
    """בדיקה אם ה-PDF הוא וקטורי (ניתן לחילוץ טקסט)"""
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for i in range(min(len(reader.pages), 2)):
            text += reader.pages[i].extract_text() or ""
        return len(text.strip()) > 100
    except:
        return False

def validate_pension_type(text):
    """בדיקה אם זה דוח מקוצר של קרן פנסיה מקיפה"""
    # בדיקה שקיים הביטוי 'בקרן הפנסיה החדשה'
    if 'בקרן הפנסיה החדשה' not in text:
        return False, "הרובוט מחווה דעה רק על דוחות מקוצרים של קרן פנסיה מקיפה."
    
    # בדיקה שהמילה 'כללית' לא מופיעה בכותרת (נניח ב-500 התווים הראשונים)
    header = text[:500]
    if 'כללית' in header:
        return False, "הרובוט מחווה דעה רק על דוחות מקוצרים של קרן פנסיה מקיפה (ולא פנסיה כללית)."
    
    return True, ""

def extract_pdf_text(pdf_bytes):
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    full_text = ""
    for page in reader.pages:
        t = page.extract_text()
        if t: full_text += t + "\n"
    return full_text

def anonymize_pii(text: str) -> str:
    text = re.sub(r"\b\d{7,9}\b", "[ID]", text)
    text = re.sub(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}\b", "[DATE]", text)
    return text

# ─── לוגיקה עסקית וחישובים ─────────────────────────────

def calculate_analysis(data, gender, family_status):
    """ביצוע החישובים לפי הלוגיקה שביקשת"""
    
    # 1. אומדן גיל (מבוסס נוסחת NPER - מספר תקופות)
    # n = log(FV/PV) / log(1+r)
    try:
        pv = float(data.get('accumulation', 0))
        fv = float(data.get('expected_pension', 0)) * 190
        if pv > 0 and fv > 0:
            years_to_retirement = math.log(fv / pv) / math.log(1 + PENSION_INTEREST)
            estimated_age = 67 - years_to_retirement
        else:
            estimated_age = 0
            years_to_retirement = 0
    except:
        estimated_age = 0
        years_to_retirement = 0

    if estimated_age > 52:
        return "הרובוט עוד צעיר ועדיין לא למד לחוות דעה על דוחות של אנשים שיכולים לפרוש בתוך פחות מ-10 שנים. בעתיד הרובוט רוצה ללמוד לעזור גם להם."

    # 2. הכנסה מבוטחת
    try:
        disability_release = float(data.get('disability_release', 0))
        total_deposits = float(data.get('total_deposits', 1))
        total_salaries = float(data.get('total_salaries', 1))
        
        rep_deposit = disability_release / 0.94
        deposit_rate = total_deposits / total_salaries
        insured_salary = rep_deposit / deposit_rate
    except:
        insured_salary = 0

    # 3. בחינת כיסוי ביטוחי
    lines = []
    lines.append(f"### 📊 נתוני רקע שחושבו:")
    lines.append(f"- גיל משוער: **{estimated_age:.1f}**")
    lines.append(f"- שכר מבוטח מוערך: **₪{insured_salary:,.0f}**")
    lines.append("---")

    is_active = float(data.get('disability_cost', 0)) > 0
    if not is_active:
        return "❌ **קרן הפנסיה איננה פעילה ואין לך דרכה כיסויים ביטוחיים!** ממליץ לשקול לנייד את הכספים לקרן הפנסיה הפעילה שלך."

    # עלות ביטוח שארים שנתית (התאמה לפי רבעון)
    survivor_cost = abs(float(data.get('survivor_cost', 0)))
    quarter = data.get('report_quarter', 4) # ברירת מחדל שנתי
    multiplier = {1: 4, 2: 2, 3: 1.333, 4: 1}.get(quarter, 1)
    annual_survivor_cost = survivor_cost * multiplier

    # לוגיקה לפי מצב משפחתי
    if family_status == "רווק":
        if survivor_cost == 0:
            lines.append("💡 מומלץ לפנות לקרן הפנסיה בכדי לקנות **'ברות ביטוח'** מה שיחסוך לך את הצורך עבור חיתום ותקופת אכשרה אם תרצה לרכוש ביטוח שארים בעתיד. העלות זניחה.")
        elif annual_survivor_cost > 13:
            savings = annual_survivor_cost * (1.0386 ** (67 - estimated_age))
            lines.append("1. כרווק סביר מאוד שביטוח השארים מיותר עבורך. ממליץ לשקול לבטלו.")
            lines.append(f"2. ביטול הביטוח לשנתיים צפוי לשפר את הצבירה שלך בערך ב-**₪{savings:,.0f}**.")
            lines.append("3. ביטול הביטוח תקף לשנתיים ויש לחדשו אם המצב המשפחתי לא השתנה.")
        else:
            lines.append("✅ מעולה, אתה לא מבזבז כסף על רכישת ביטוח שארים. זכור לחדש את הויתור אחת לשנתיים.")

    elif family_status in ["נשוי", "לא נשוי אך יש ילדים"]:
        if annual_survivor_cost < 13:
            lines.append("⚠️ **ייתכן שאתה בתקופת ויתור שארים.** עליך לעדכן בהקדם את הקרן שאינך רווק כדי שירכשו לך ביטוח שארים.")

    # בדיקת כיסוי מקסימלי
    widow_pension = float(data.get('widow_pension', 0))
    disability_pension = float(data.get('disability_pension', 0))
    
    is_low_coverage = (widow_pension < 0.59 * insured_salary) or (disability_pension < 0.74 * insured_salary)
    
    if is_low_coverage:
        lines.append("\n<span style='color:red; font-weight:bold;'>🔴 הכיסוי הביטוחי בקרן הפנסיה איננו מקסימלי</span>")
        
        is_woman = gender == "אשה"
        is_young_man = (gender == "גבר" and years_to_retirement > 27)
        
        if is_woman or is_young_man:
            lines.append("💡 **מומלץ לשקול לשנות את מסלול הביטוח** כך שיקנה לך ולמשפחתך הגנה ביטוחית מקסימלית.")

    return "\n".join(lines)

# ─── ממשק משתמש (שלוש השאלות) ──────────────────────────

st.title("🔍 בודק דמי ניהול וביטוח פנסיוני")

# שלב 1: שאלות
col1, col2, col3 = st.columns(3)
with col1:
    q_gender = st.radio("מגדר:", ["גבר", "אשה"], index=None)
with col2:
    q_emp = st.radio("סטטוס הפקדות בדו\"ח:", ["שכיר בלבד", "עצמאי בלבד", "שכיר + עצמאי"], index=None)
with col3:
    q_family = st.radio("מצב משפחתי:", ["נשוי", "רווק", "לא נשוי אך יש ילדים"], index=None)

# בדיקת תנאי תעסוקה
if q_emp and q_emp != "שכיר בלבד":
    st.warning("בשלב זה הבוט לא למד לחוות דעה על דוחות של מי שאינם רק שכירים.")
    st.stop()

# הצגת כפתור העלאה רק אם הכל מולא
if all([q_gender, q_emp, q_family]):
    st.markdown("---")
    file = st.file_uploader("📄 כעת ניתן להעלות את הדו\"ח המקוצר (PDF מקורי בלבד)", type=["pdf"])

    if file:
        pdf_bytes = file.read()
        
        # ולידציה 1: וקטורי
        if not is_vector_pdf(pdf_bytes):
            st.error("הבוט לא יודע לקרוא קבצים שאינם הקבצים המקוריים מאתר קרן הפנסיה (סריקות או צילומים לא נתמכים).")
            st.stop()
        
        # חילוץ טקסט
        full_text = extract_pdf_text(pdf_bytes)
        
        # ולידציה 2: סוג דוח
        is_valid_type, error_msg = validate_pension_type(full_text)
        if not is_valid_type:
            st.error(error_msg)
            st.stop()
            
        # שליחה ל-AI לחילוץ נתונים
        with st.spinner("🔄 מנתח את נתוני הדוח..."):
            try:
                system_prompt = """אתה מחלץ נתונים מדוח פנסיה. החזר JSON בלבד עם השדות:
                accumulation (יתרת כספים בקרן בסוף התקופה מטבלה ב),
                expected_pension (קצבה חודשית צפויה בפרישה),
                disability_release (שחרור מתשלום הפקדות - שורה תחתונה טבלה א),
                total_deposits (סה"כ הפקדות בתקופה),
                total_salaries (סה"כ משכורות בתקופה),
                disability_cost (עלות ביטוח נכות/נכות מלאה),
                survivor_cost (עלות ביטוח שארים/מוות),
                widow_pension (קצבה לאלמן/ה),
                disability_pension (קצבה במקרה נכות מלאה),
                report_quarter (1-4 או 4 אם שנתי)"""
                
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": anonymize_pii(full_text[:MAX_TEXT_CHARS])}
                    ],
                    response_format={"type": "json_object"}
                )
                
                extracted_data = json.loads(response.choices[0].message.content)
                
                # הרצת הניתוח הלוגי
                result_markdown = calculate_analysis(extracted_data, q_gender, q_family)
                
                st.success("✅ הניתוח הושלם")
                st.markdown(result_markdown, unsafe_allow_html=True)
                
            except Exception as e:
                st.error(f"אירעה שגיאה בעיבוד הנתונים. נסה שוב מאוחר יותר.")
