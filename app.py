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
PENSION_INTEREST = 0.0386  # 3.86%
MAX_TEXT_CHARS = 15_000

# ─── חיבור ל-API ─────────────────────────────────────
try:
    API_KEY = st.secrets["OPENAI_API_KEY"]
    client = OpenAI(api_key=API_KEY, default_headers={"OpenAI-No-Store": "true"})
except Exception:
    st.error("⚠️ מפתח ה-API לא נמצא ב-Secrets.")
    st.stop()

# ─── פונקציות ולידציה וזיהוי ─────────────────────────────

def is_vector_pdf(pdf_bytes):
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for i in range(min(len(reader.pages), 2)):
            text += reader.pages[i].extract_text() or ""
        return len(text.strip()) > 100
    except:
        return False

def validate_pension_type(text):
    """בדיקת סוג דוח לפי כותרת"""
    header = text[:1500]
    # בדיקת טקסט רגיל והפוך (RTL)
    search_text = header + "\n" + "\n".join(line[::-1] for line in header.split("\n"))
    
    if 'כללית' in search_text:
        return False, "הרובוט מחווה דעה רק על דוחות מקוצרים של קרן פנסיה מקיפה (ולא פנסיה כללית)."
    if 'מפורט' in search_text:
        return False, "הרובוט מחווה דעה רק על דוחות מקוצרים (ולא מפורטים)."
    if 'בקרן הפנסיה החדשה' not in search_text and 'קרן הפנסיה' not in search_text:
        return False, "הרובוט מחווה דעה רק על דוחות מקוצרים של קרן פנסיה מקיפה."
    
    return True, ""

# ─── לוגיקת AI וחילוץ נתונים ──────────────────────────

def build_prompt_messages(text):
    system_prompt = """אתה מחלץ נתונים מדוח פנסיה. החזר JSON בלבד עם השדות הבאים (מספרים בלבד):
    accumulation (יתרת הכספים בסוף התקופה - טבלה ב),
    expected_pension (קצבה חודשית צפויה בפרישה גיל 67),
    disability_release (שחרור מתשלום הפקדות - טבלה א),
    total_deposits (סה"כ הפקדות בגין התקופה),
    total_salaries (סה"כ משכורות/שכר מבוטח בגין התקופה),
    disability_cost (עלות ביטוח נכות - טבלה ב, כמספר חיובי),
    survivor_cost (עלות ביטוח מוות/שארים - טבלה ב, כמספר חיובי),
    widow_pension (קצבה חודשית לאלמן/ה),
    disability_pension (קצבה חודשית בנכות מלאה),
    report_quarter (1, 2, 3 או 4 אם שנתי)."""
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"נתח את הטקסט הבא:\n\n{text[:MAX_TEXT_CHARS]}"}
    ]

# ─── חישובים וניתוח לוגי ──────────────────────────────

def perform_analysis(data, gender, family_status):
    # 1. אומדן גיל (NPER)
    try:
        pv = float(data.get('accumulation', 0))
        fv = float(data.get('expected_pension', 0)) * 190
        nper = math.log(fv / pv) / math.log(1 + PENSION_INTEREST)
        est_age = 67 - nper
    except:
        return "⚠️ לא ניתן היה לחשב אומדן גיל. וודא שהעלית דוח תקין."

    if est_age > 52:
        return "הרובוט עוד צעיר ועדיין לא למד לחוות דעה על דוחות של אנשים שיכולים לפרוש בתוך פחות מ-10 שנים. בעתיד הרובוט רוצה ללמוד לעזור גם להם."

    # 2. הכנסה מבוטחת
    try:
        release = float(data.get('disability_release', 0))
        rep_deposit = release / 0.94
        dep_rate = float(data.get('total_deposits', 1)) / float(data.get('total_salaries', 1))
        insured_salary = rep_deposit / dep_rate
    except:
        insured_salary = 0

    lines = [f"### 📋 ניתוח נתונים משוערים:"]
    lines.append(f"- גיל משוער: **{est_age:.1f}**")
    lines.append(f"- שכר מבוטח מוערך: **₪{insured_salary:,.0f}**")
    lines.append("---")

    # 3. בחינת כיסוי ביטוחי
    dis_cost = float(data.get('disability_cost', 0))
    if dis_cost <= 0:
        return "🔴 **קרן הפנסיה איננה פעילה ואין לך דרכה כיסויים ביטוחיים!** מומלץ לנייד את הכספים לקרן פעילה."

    surv_cost = float(data.get('survivor_cost', 0))
    q = data.get('report_quarter', 4)
    ann_surv_cost = surv_cost * {1: 4, 2: 2, 3: 1.333, 4: 1}.get(q, 1)

    if family_status == "רווק":
        if surv_cost == 0:
            lines.append("💡 מומלץ לקנות **'ברות ביטוח'** כדי לחסוך חיתום בעתיד. העלות זניחה.")
        elif ann_surv_cost > 13:
            savings = ann_surv_cost * (1.0386 ** (67 - est_age))
            lines.append(f"1. כרווק, ביטוח השארים (₪{ann_surv_cost:,.0f} לשנה) כנראה מיותר. מומלץ לשקול לבטלו.")
            lines.append(f"2. ביטול לשנתיים ישפר את הצבירה בערך ב-**₪{savings:,.0f}**.")
            lines.append("3. ביטול תקף לשנתיים ויש לחדשו אם המצב לא השתנה.")
        else:
            lines.append("✅ מעולה, אתה לא מבזבז כסף על ביטוח שארים מיותר. זכור לחדש ויתור כל שנתיים.")
    
    elif ann_surv_cost < 13:
        lines.append("⚠️ **נראה שאתה בוויתור שארים בטעות.** עדכן את הקרן שאינך רווק.")

    # 4. כיסוי מקסימלי
    widow = float(data.get('widow_pension', 0))
    dis_pension = float(data.get('disability_pension', 0))
    if widow < 0.59 * insured_salary or dis_pension < 0.74 * insured_salary:
        lines.append("\n<span style='color:red; font-weight:bold;'>🔴 הכיסוי הביטוחי בקרן הפנסיה איננו מקסימלי</span>")
        if gender == "אשה" or (67 - est_age > 27):
            lines.append("💡 מומלץ לשקול שינוי מסלול ביטוח להגנה מקסימלית.")

    return "\n".join(lines)

# ─── ממשק משתמש ──────────────────────────────────────────

st.title("🔍 בודק הפנסיה האוטומטי")

# שלב השאלות
gender = st.radio("1. מגדר:", ["גבר", "אשה"], index=None, horizontal=True)
emp = st.radio("2. סוג הפקדות בדו"ח:", ["שכיר בלבד", "עצמאי בלבד", "שכיר + עצמאי"], index=None, horizontal=True)
family = st.radio("3. מצב משפחתי:", ["נשוי", "רווק", "לא נשוי אך יש ילדים מתחת לגיל 21"], index=None, horizontal=True)

if emp and emp != "שכיר בלבד":
    st.warning("בשלב זה הבוט לא למד לחוות דעה על דוחות של מי שאינם רק שכירים.")
    st.stop()

if all([gender, emp, family]):
    st.markdown("---")
    file = st.file_uploader("📄 העלה דוח מקוצר (PDF מקורי)", type=["pdf"])
    
    if file:
        raw_bytes = file.read()
        if not is_vector_pdf(raw_bytes):
            st.error("הבוט לא יודע לקרוא סריקות. העלה קובץ PDF מקורי מהאתר.")
            st.stop()
            
        text = pypdf.PdfReader(io.BytesIO(raw_bytes)).pages[0].extract_text()
        valid, msg = validate_pension_type(text)
        if not valid:
            st.error(msg)
            st.stop()
            
        with st.spinner("🔄 מנתח..."):
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=build_prompt_messages(text),
                    response_format={"type": "json_object"}
                )
                data = json.loads(response.choices[0].message.content)
                st.markdown(perform_analysis(data, gender, family), unsafe_allow_html=True)
            except:
                st.error("אירעה שגיאה בניתוח ה-AI.")
