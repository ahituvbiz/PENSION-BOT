import streamlit as st
import fitz
import os
import pandas as pd
import re
from collections import defaultdict

st.set_page_config(page_title="מנתח פנסיה - גירסה 32.0", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;700&display=swap');
    * { font-family: 'Assistant', sans-serif; direction: rtl; text-align: right; }
    .stTable { direction: rtl !important; width: 100%; }
    th, td { text-align: right !important; padding: 12px !important; white-space: nowrap; }
    .val-success { padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold;
        background-color: #f0fdf4; border: 1px solid #16a34a; color: #16a34a; }
    .val-error { padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold;
        background-color: #fef2f2; border: 1px solid #dc2626; color: #dc2626; }
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# חילוץ מילים עם קואורדינטות
# ════════════════════════════════════════════════════════════════════════════════

def extract_words(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    words = []
    for page_num, page in enumerate(doc):
        for w in page.get_text("words"):
            text = w[4].strip()
            if text:
                words.append({"page": page_num, "x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3], "text": text})
    return words

def group_lines(words, y_tol=3):
    by_page = defaultdict(list)
    for w in words:
        by_page[w["page"]].append(w)

    result = {}
    for page, ws in by_page.items():
        ws = sorted(ws, key=lambda w: (w["y0"], w["x0"]))
        lines, cur, cur_y = [], [], None
        for w in ws:
            ym = (w["y0"] + w["y1"]) / 2
            if cur_y is None or abs(ym - cur_y) <= y_tol:
                cur.append(w)
                cur_y = ym if cur_y is None else (cur_y + ym) / 2
            else:
                if cur: lines.append(sorted(cur, key=lambda w: w["x0"]))
                cur, cur_y = [w], ym
        if cur: lines.append(sorted(cur, key=lambda w: w["x0"]))
        result[page] = lines
    return result

def ltext(line):
    """טקסט מלא של שורה, מימין לשמאל (RTL)."""
    return " ".join(w["text"] for w in reversed(line))

def is_num(t):
    return bool(re.fullmatch(r'-?\d{1,3}(,\d{3})*(\.\d+)?|-?\d+(\.\d+)?', t.replace(",", "")))

def parse_num(t):
    try:
        return float(re.sub(r'[^\d\.\-]', '', t.replace(",", "")))
    except:
        return None

def line_numbers(line):
    """כל המספרים בשורה מסודרים מימין לשמאל."""
    nums = []
    for w in reversed(line):
        n = parse_num(w["text"])
        if n is not None and re.search(r'\d', w["text"]):
            nums.append((w["x0"], n, w["text"]))
    return nums  # (x, value, original_text)

# ════════════════════════════════════════════════════════════════════════════════
# איתור סעיפים
# ════════════════════════════════════════════════════════════════════════════════

SECTION_KEYWORDS = {
    "a": ["תשלומים צפויים"],
    "b": ["תנועות בקרן"],
    "c": ["דמי ניהול"],
    "d": ["מסלולי השקעה"],
    "e": ["פירוט הפקדות"],
}

def find_all_sections(lines_map):
    """
    מוצא את מיקום כל סעיף: {section_id: (page, line_idx, y0)}.
    שומר את ה-y0 כדי שנוכל לדעת איזה סעיף קודם לאיזה.
    """
    found = {}
    for page in sorted(lines_map.keys()):
        for i, line in enumerate(lines_map[page]):
            lt = ltext(line)
            for sec_id, kws in SECTION_KEYWORDS.items():
                if sec_id not in found and any(kw in lt for kw in kws):
                    found[sec_id] = (page, i, line[0]["y0"])
    return found

def get_lines_for_section(lines_map, sections, sec_id):
    """
    מחזיר את השורות השייכות לסעיף נתון —
    מהשורה שאחרי הכותרת עד לשורה שבה מתחיל הסעיף הבא (לפי מיקום Y).
    """
    if sec_id not in sections:
        return []

    s_page, s_line, s_y = sections[sec_id]

    # מצא את הסעיף הבא לפי Y — ללא קשר לאיזה סעיף זה
    next_y = float("inf")
    next_page = float("inf")
    for other_id, (o_page, o_line, o_y) in sections.items():
        if other_id == sec_id: continue
        if (o_page, o_y) > (s_page, s_y):
            if (o_page, o_y) < (next_page, next_y):
                next_page, next_y = o_page, o_y

    result = []
    for page in sorted(lines_map.keys()):
        if page < s_page: continue
        for i, line in enumerate(lines_map[page]):
            if page == s_page and i <= s_line: continue
            y = line[0]["y0"]
            if page > next_page or (page == next_page and y >= next_y):
                return result
            result.append(line)
    return result

# ════════════════════════════════════════════════════════════════════════════════
# חילוץ כל טבלה
# ════════════════════════════════════════════════════════════════════════════════

def extract_table_a(section_lines):
    """
    תשלומים צפויים.
    תיקון: בשורה עם "בגיל 67" — הגיל הוא לא הסכום.
    הסכום הוא המספר הגדול ביותר בשורה (לאחר הגיל).
    """
    rows = []
    AGE_RE = re.compile(r'בגיל\s+\d+')

    for line in section_lines:
        lt = ltext(line)
        nums = line_numbers(line)
        if not nums: continue

        # בשורה עם "בגיל XX" — הסר את הגיל מרשימת המספרים
        if AGE_RE.search(lt):
            age_match = re.search(r'\b(\d{2})\b', lt)
            if age_match:
                age_val = float(age_match.group(1))
                nums = [(x, v, t) for x, v, t in nums if v != age_val]

        if not nums: continue

        # הסכום הוא המספר הגדול ביותר
        amount = max(nums, key=lambda n: abs(n[1]))

        # תיאור: כל הטקסט שאינו מספרים
        desc_words = [w["text"] for w in reversed(line) if not is_num(w["text"])]
        # הסר גיל אם הוא הוטמע בטקסט
        desc = " ".join(desc_words).strip()
        desc = re.sub(r'\s*\d{2}\.\d{2}\s*', ' ', desc).strip()

        if desc:
            rows.append({"תיאור": desc, 'סכום בש"ח': f"{int(amount[1]):,}"})
    return rows

def extract_table_b(section_lines):
    """תנועות בקרן — תיאור + סכום, עם תמיכה בערכים שליליים."""
    rows = []
    for line in section_lines:
        lt = ltext(line)
        nums = line_numbers(line)
        if not nums: continue

        desc_words = [w["text"] for w in reversed(line) if not is_num(w["text"])]
        desc = " ".join(desc_words).strip()
        if not desc: continue

        # הסכום — המספר הגדול ביותר בערך מוחלט
        amount = max(nums, key=lambda n: abs(n[1]))

        # בדיקת שליליות: האם יש מינוס בטקסט המקורי לפני המספר
        raw = " ".join(w["text"] for w in line)
        neg_pattern = r'[-−]' + re.escape(str(int(abs(amount[1]))).replace(",", ""))
        is_neg = bool(re.search(neg_pattern, raw.replace(",", "")))
        val = -abs(amount[1]) if is_neg else amount[1]

        rows.append({"תיאור": desc, 'סכום בש"ח': f"{int(val):,}"})
    return rows

def extract_table_c(section_lines):
    """דמי ניהול — תיאור + אחוז."""
    rows = []
    for line in section_lines:
        lt = ltext(line)
        pct = re.search(r'(\d+\.\d+)%?', lt)
        if not pct: continue
        desc_words = [w["text"] for w in reversed(line)
                      if not re.search(r'\d+\.\d+', w["text"])]
        desc = " ".join(desc_words).strip()
        if desc:
            rows.append({"תיאור": desc, "אחוז": pct.group(0) if "%" in lt else pct.group(0) + "%"})
    return rows

def extract_table_d(section_lines):
    """מסלולי השקעה — מסלול + תשואה, עם איחוד שמות גולשים."""
    rows = []
    pending = None
    for line in section_lines:
        lt = ltext(line)
        pct = re.search(r'-?\d+\.?\d*%', lt)
        if pct:
            name_words = [w["text"] for w in reversed(line)
                          if not re.search(r'-?\d+\.?\d*%', w["text"])
                          and not re.match(r'\d+\.\d+$', w["text"])]
            name = " ".join(name_words).strip()
            if pending:
                name = (pending + " " + name).strip()
                pending = None
            if name:
                rows.append({"מסלול": name, "תשואה": pct.group(0)})
        elif lt.strip() and not any(c.isdigit() for c in lt):
            pending = (pending + " " + lt.strip()) if pending else lt.strip()
    return rows

def extract_table_e(section_lines, employer_from_header=""):
    """
    פירוט הפקדות.
    תומך בשני פורמטים:
    - מיטב: שם מעסיק בכל שורה
    - אלטשולר: שם מעסיק רק בכותרת הדוח
    """
    DATE_FULL  = re.compile(r'\d{2}/\d{2}/\d{4}')
    MONTH_RE   = re.compile(r'\d{2}/\d{4}')

    rows = []
    pending_employer = None

    for line in section_lines:
        lt = ltext(line)

        # שורת סיכום
        if 'סה"כ' in lt:
            nums_raw = line_numbers(line)
            nums = [n for _, n, _ in nums_raw if n > 0]
            if len(nums) >= 3:
                nums_sorted = sorted(nums, reverse=True)
                rows.append({
                    "שם המעסיק": 'סה"כ', "מועד": "", "חודש": "", "שכר": "",
                    'סה"כ':     f"{int(nums_sorted[0]):,}",
                    "פיצויים":  f"{int(nums_sorted[1]):,}",
                    "מעסיק":    f"{int(nums_sorted[2]):,}",
                    "עובד":     f"{int(nums_sorted[3]):,}" if len(nums_sorted) > 3 else "0",
                })
            continue

        # שורה עם תאריך הפקדה
        date_m = DATE_FULL.search(lt)
        if date_m:
            deposit_date = date_m.group()
            months = MONTH_RE.findall(lt)
            salary_month = months[-1] if months else ""

            nums_raw = line_numbers(line)
            nums = [n for _, n, _ in nums_raw if n > 0]

            # שם מעסיק: מה שמופיע לפני התאריך בשורה, או ה-pending, או מהכותרת
            employer_words = []
            for w in reversed(line):
                if DATE_FULL.search(w["text"]) or MONTH_RE.search(w["text"]):
                    break
                if not is_num(w["text"]):
                    employer_words.append(w["text"])
            employer_inline = " ".join(employer_words).strip()

            if pending_employer:
                employer = (pending_employer + " " + employer_inline).strip()
                pending_employer = None
            elif employer_inline:
                employer = employer_inline
            else:
                employer = employer_from_header  # אלטשולר — שם מהכותרת

            if len(nums) >= 4:
                rows.append({
                    "שם המעסיק": employer,
                    "מועד":       deposit_date,
                    "חודש":       salary_month,
                    "שכר":        f"{int(nums[4]):,}" if len(nums) > 4 else "",
                    "עובד":       f"{int(nums[3]):,}" if len(nums) > 3 else "",
                    "מעסיק":      f"{int(nums[2]):,}" if len(nums) > 2 else "",
                    "פיצויים":    f"{int(nums[1]):,}",
                    'סה"כ':       f"{int(nums[0]):,}",
                })
            continue

        # שורת טקסט ללא מספרים ולא תאריך = שם מעסיק גולש
        if lt.strip() and not any(c.isdigit() for c in lt):
            skip_words = ["שם המעסיק", "מועד", "חודש", "שכר", "עובד", "מעסיק", "פיצויים", 'סה"כ', "הפקדה", "משכורת"]
            if not any(sw in lt for sw in skip_words):
                pending_employer = (pending_employer + " " + lt.strip()) if pending_employer else lt.strip()

    # תיקון שכר בשורת סיכום
    salary_sum = sum(
        float(str(r.get("שכר", "0")).replace(",", ""))
        for r in rows if r.get("מועד")
    )
    for r in rows:
        if r.get("שם המעסיק") == 'סה"כ':
            r["שכר"] = f"{int(salary_sum):,}"

    return rows

# ════════════════════════════════════════════════════════════════════════════════
# חילוץ שם מעסיק מכותרת הדוח (לאלטשולר)
# ════════════════════════════════════════════════════════════════════════════════

def extract_employer_from_header(lines_map):
    """
    מחפש "שם המעסיק:" ומחזיר את הערך שאחריו.
    """
    for page in sorted(lines_map.keys()):
        for line in lines_map[page]:
            lt = ltext(line)
            if "שם המעסיק" in lt:
                # המעסיק הוא הטקסט שמגיע אחרי "שם המעסיק:"
                m = re.search(r'שם המעסיק[:\s]+(.+)', lt)
                if m:
                    emp = m.group(1).strip()
                    # הסר פרטי עמית שעשויים להיות באותה שורה
                    emp = re.sub(r'מספר ת\.ז.*', '', emp).strip()
                    if emp:
                        return emp
    return ""

# ════════════════════════════════════════════════════════════════════════════════
# אימות ותצוגה
# ════════════════════════════════════════════════════════════════════════════════

def clean_num(val):
    try:
        return float(str(val).replace(",", ""))
    except:
        return 0.0

def cross_validate(table_b, table_e):
    dep_b = 0.0
    for r in table_b:
        if any(kw in str(r.get("תיאור", "")) for kw in ["הופקדו", "שהופקדו"]):
            dep_b = clean_num(r.get('סכום בש"ח', 0))
            break
    dep_e = clean_num(table_e[-1].get('סה"כ', 0)) if table_e else 0.0
    if abs(dep_b - dep_e) < 5 and dep_e > 0:
        st.markdown(f'<div class="val-success">✅ אימות הצלבה עבר: סכום ההפקדות ({dep_e:,.0f} ₪) תואם במדויק.</div>', unsafe_allow_html=True)
    elif dep_e > 0:
        st.markdown(f'<div class="val-error">⚠️ שגיאת אימות: טבלה ב\' ({dep_b:,.0f} ₪) לעומת טבלה ה\' ({dep_e:,.0f} ₪).</div>', unsafe_allow_html=True)

def display_table(rows, title, cols):
    if not rows:
        st.warning(f"{title} — לא נמצאו נתונים")
        return
    df = pd.DataFrame(rows)
    existing = [c for c in cols if c in df.columns]
    df = df[existing].fillna("")
    df.index = range(1, len(df) + 1)
    st.subheader(title)
    st.table(df)

# ════════════════════════════════════════════════════════════════════════════════
# ממשק
# ════════════════════════════════════════════════════════════════════════════════

st.title("📋 חילוץ נתונים פנסיוני - גירסה 32.0")
st.caption("חילוץ לפי קואורדינטות XY — תומך במיטב, אלטשולר ופורמטים נוספים")

file = st.file_uploader("העלה דוח PDF", type="pdf")
if file:
    file_bytes = file.read()

    with st.spinner("מחלץ..."):
        words     = extract_words(file_bytes)
        lines_map = group_lines(words)
        sections  = find_all_sections(lines_map)
        employer  = extract_employer_from_header(lines_map)

        sec_lines = {k: get_lines_for_section(lines_map, sections, k) for k in "abcde"}

        table_a = extract_table_a(sec_lines["a"])
        table_b = extract_table_b(sec_lines["b"])
        table_c = extract_table_c(sec_lines["c"])
        table_d = extract_table_d(sec_lines["d"])
        table_e = extract_table_e(sec_lines["e"], employer_from_header=employer)

    cross_validate(table_b, table_e)

    display_table(table_a, "א. תשלומים צפויים",   ["תיאור", 'סכום בש"ח'])
    display_table(table_b, "ב. תנועות בקרן",       ["תיאור", 'סכום בש"ח'])
    display_table(table_c, "ג. דמי ניהול והוצאות", ["תיאור", "אחוז"])
    display_table(table_d, "ד. מסלולי השקעה",       ["מסלול", "תשואה"])
    display_table(table_e, "ה. פירוט הפקדות",
                  ["שם המעסיק", "מועד", "חודש", "שכר", "עובד", "מעסיק", "פיצויים", 'סה"כ'])

    if st.checkbox("🔍 Debug — שורות לפי סעיף"):
        for sec_id in "abcde":
            with st.expander(f"סעיף {sec_id} — {len(sec_lines[sec_id])} שורות"):
                for ln in sec_lines[sec_id]:
                    st.text(ltext(ln))import streamlit as st
import fitz
import json
import os
import pandas as pd
import re
from collections import defaultdict

st.set_page_config(page_title="מנתח פנסיה - גירסה 31.0 (קואורדינטות)", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;700&display=swap');
    * { font-family: 'Assistant', sans-serif; direction: rtl; text-align: right; }
    .stTable { direction: rtl !important; width: 100%; }
    th, td { text-align: right !important; padding: 12px !important; white-space: nowrap; }
    .val-success { padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold;
        background-color: #f0fdf4; border: 1px solid #16a34a; color: #16a34a; }
    .val-error { padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold;
        background-color: #fef2f2; border: 1px solid #dc2626; color: #dc2626; }
    .debug-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
        padding: 12px; font-size: 0.8rem; direction: ltr; text-align: left; }
</style>
""", unsafe_allow_html=True)

def clean_num(val):
    if val is None or val == "" or str(val).strip() in ["-", "nan", ".", "0"]: return 0.0
    try:
        cleaned = re.sub(r'[^\d\.\-]', '', str(val).replace(",", "").replace("−", "-"))
        return float(cleaned) if cleaned else 0.0
    except: return 0.0

# ════════════════════════════════════════════════════════════════════════════════
# ליבת החילוץ — קואורדינטות XY מדויקות מ-PDF וקטורי
# ════════════════════════════════════════════════════════════════════════════════

def extract_words_with_coords(file_bytes):
    """
    מחזיר רשימת מילים עם מיקום מדויק מכל עמודי הדוח.
    word = (page, x0, y0, x1, y1, text)
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    all_words = []
    for page_num, page in enumerate(doc):
        # get_text("words") מחזיר: (x0, y0, x1, y1, "text", block_no, line_no, word_no)
        for w in page.get_text("words"):
            all_words.append({
                "page": page_num,
                "x0": w[0], "y0": w[1],
                "x1": w[2], "y1": w[3],
                "text": w[4].strip()
            })
    return all_words

def group_into_lines(words, y_tolerance=3):
    """
    מקבץ מילים לשורות לפי קואורדינטת Y (עם סבלנות קטנה לאי-יישור).
    מחזיר: {page: [[(y_center, x_center, text), ...], ...]}
    """
    by_page = defaultdict(list)
    for w in words:
        by_page[w["page"]].append(w)

    result = {}
    for page, ws in by_page.items():
        # מיון לפי Y ואז X
        ws_sorted = sorted(ws, key=lambda w: (w["y0"], w["x0"]))
        lines = []
        current_line = []
        current_y = None

        for w in ws_sorted:
            y_mid = (w["y0"] + w["y1"]) / 2
            if current_y is None or abs(y_mid - current_y) <= y_tolerance:
                current_line.append(w)
                current_y = y_mid if current_y is None else (current_y + y_mid) / 2
            else:
                if current_line:
                    lines.append(sorted(current_line, key=lambda w: w["x0"]))
                current_line = [w]
                current_y = y_mid

        if current_line:
            lines.append(sorted(current_line, key=lambda w: w["x0"]))
        result[page] = lines

    return result

def line_text(line):
    """חיבור מילים בשורה לטקסט מלא, מימין לשמאל."""
    return " ".join(w["text"] for w in reversed(line))  # RTL

def line_nums(line):
    """חילוץ מספרים מהשורה לפי X, מימין לשמאל."""
    nums = []
    for w in reversed(line):
        t = w["text"].replace(",", "")
        # מספר עם אפשרות למינוס
        m = re.fullmatch(r'-?\d+\.?\d*', t)
        if m:
            nums.append(float(m.group()))
    return nums

def is_number(text):
    t = text.replace(",", "").replace("-", "")
    return bool(re.fullmatch(r'\d+\.?\d*%?', t))

# ════════════════════════════════════════════════════════════════════════════════
# חילוץ כל טבלה
# ════════════════════════════════════════════════════════════════════════════════

def find_section_start(lines_by_page, keyword):
    """מוצא את מיקום (page, line_idx) של כותרת סעיף לפי מילת מפתח."""
    for page, lines in sorted(lines_by_page.items()):
        for i, line in enumerate(lines):
            lt = line_text(line)
            if keyword in lt:
                return (page, i)
    return None

def extract_two_col_table(lines_by_page, start_keyword, stop_keywords, col1_name, col2_name):
    """
    חילוץ טבלה דו-עמודתית: תיאור + מספר.
    עוצרת כשנתקלת באחד ממילות העצירה.
    """
    start = find_section_start(lines_by_page, start_keyword)
    if not start:
        return []

    rows = []
    page, line_idx = start
    all_pages = sorted(lines_by_page.keys())

    collecting = False
    for p in all_pages:
        if p < page:
            continue
        lines = lines_by_page[p]
        start_i = line_idx + 1 if p == page else 0

        for i in range(start_i, len(lines)):
            lt = line_text(lines[i])

            # בדיקת עצירה
            if any(kw in lt for kw in stop_keywords):
                return rows

            # שורה עם לפחות מספר אחד = שורת נתונים
            nums = line_nums(lines[i])
            if nums:
                # הטקסט = כל מה שאינו מספר
                words_text = [w["text"] for w in reversed(lines[i]) if not is_number(w["text"].replace(",", ""))]
                desc = " ".join(words_text).strip()
                # ערך שלילי: אם יש מינוס לפני המספר בטקסט המקורי
                raw_line = " ".join(w["text"] for w in lines[i])
                sign = -1 if re.search(r'[-−]' + re.escape(str(int(abs(nums[0])))), raw_line) else 1
                val = sign * abs(nums[0])
                if desc:
                    rows.append({col1_name: desc, col2_name: f"{val:,.0f}" if val == int(val) else f"{val}"})
            collecting = True

    return rows

def extract_table_a(lines_by_page):
    return extract_two_col_table(
        lines_by_page,
        start_keyword="תשלומים צפויים",
        stop_keywords=["תנועות בקרן", "דמי ניהול", "מסלולי השקעה"],
        col1_name="תיאור",
        col2_name='סכום בש"ח'
    )

def extract_table_b(lines_by_page):
    return extract_two_col_table(
        lines_by_page,
        start_keyword="תנועות בקרן",
        stop_keywords=["מסלולי השקעה", "פירוט הפקדות", "דמי ניהול"],
        col1_name="תיאור",
        col2_name='סכום בש"ח'
    )

def extract_table_c(lines_by_page):
    return extract_two_col_table(
        lines_by_page,
        start_keyword="דמי ניהול",
        stop_keywords=["תנועות בקרן", "מסלולי השקעה", "פירוט הפקדות"],
        col1_name="תיאור",
        col2_name="אחוז"
    )

def extract_table_d(lines_by_page):
    """
    חילוץ מסלולי השקעה.
    כל שורה: שם מסלול (טקסט) + תשואה (מספר עם %).
    שמות גולשים לשורה שנייה: מאוחדים אוטומטית.
    """
    start = find_section_start(lines_by_page, "מסלולי השקעה")
    if not start:
        return []

    rows = []
    page, line_idx = start
    pending_name = None

    for p in sorted(lines_by_page.keys()):
        if p < page:
            continue
        lines = lines_by_page[p]
        start_i = line_idx + 1 if p == page else 0

        for i in range(start_i, len(lines)):
            lt = line_text(lines[i])
            if "פירוט הפקדות" in lt or "הפקדות לקרן" in lt:
                return rows

            # מחפשים אחוז תשואה
            pct_match = re.search(r'(\d+\.?\d*)%', lt)
            if pct_match:
                # יש תשואה בשורה הזו
                tshoa = pct_match.group(0)
                words_no_num = [w["text"] for w in reversed(lines[i])
                                if not re.search(r'\d+\.?\d*%', w["text"]) and not is_number(w["text"].replace(",", ""))]
                name_part = " ".join(words_no_num).strip()
                if pending_name:
                    full_name = (pending_name + " " + name_part).strip()
                    pending_name = None
                else:
                    full_name = name_part
                if full_name:
                    rows.append({"מסלול": full_name, "תשואה": tshoa})
            elif lt.strip() and not re.search(r'^\d', lt.strip()):
                # שורת טקסט בלי מספר = שם מסלול גולש
                if pending_name:
                    pending_name += " " + lt.strip()
                else:
                    pending_name = lt.strip()

    return rows

def extract_table_e(lines_by_page):
    """
    חילוץ פירוט הפקדות.
    עמודות: שם המעסיק | מועד | חודש | שכר | עובד | מעסיק | פיצויים | סה"כ
    לוגיקה: שורת נתונים = שורה עם תאריך (dd/mm/yyyy) + לפחות 4 מספרים.
    """
    start = find_section_start(lines_by_page, "פירוט הפקדות")
    if not start:
        return []

    DATE_RE    = re.compile(r'\d{2}/\d{2}/\d{4}')
    MONTH_RE   = re.compile(r'\d{2}/\d{4}')
    NUM_RE     = re.compile(r'^\d{1,3}(,\d{3})*$|^\d+$')

    rows = []
    pending_employer = None
    page, line_idx = start

    for p in sorted(lines_by_page.keys()):
        if p < page:
            continue
        lines = lines_by_page[p]
        start_i = line_idx + 1 if p == page else 0

        for i in range(start_i, len(lines)):
            line = lines[i]
            lt = line_text(line)
            words = [w["text"] for w in line]

            # שורת סיכום
            if 'סה"כ' in lt and len(line_nums(line)) >= 3:
                ns = line_nums(line)
                if len(ns) >= 4:
                    rows.append({
                        "שם המעסיק": 'סה"כ',
                        "מועד": "", "חודש": "", "שכר": "",
                        "עובד":     f"{int(ns[-3]):,}",
                        "מעסיק":    f"{int(ns[-2]):,}",
                        "פיצויים":  f"{int(ns[-1]):,}",  # ← מה שנמצא בעמודה האחרונה בשורת הסיכום
                        'סה"כ':     f"{int(ns[0]):,}"    # ← הסכום הכולל (הגדול ביותר, בצד שמאל)
                    })
                    # מיון סה"כ לפי גודל
                    last = rows[-1]
                    all_ns = sorted([clean_num(last["עובד"]), clean_num(last["מעסיק"]),
                                     clean_num(last["פיצויים"]), clean_num(last['סה"כ'])], reverse=True)
                    last['סה"כ']    = f"{int(all_ns[0]):,}"
                    last["עובד"]    = f"{int(all_ns[3]):,}"
                    last["מעסיק"]   = f"{int(all_ns[2]):,}"
                    last["פיצויים"] = f"{int(all_ns[1]):,}"
                continue

            # שורה עם תאריך הפקדה
            date_match = DATE_RE.search(lt)
            if date_match:
                deposit_date = date_match.group()
                month_matches = MONTH_RE.findall(lt)
                salary_month = month_matches[-1] if month_matches else ""

                # המספרים בשורה מימין לשמאל: סה"כ, פיצויים, מעסיק, עובד, שכר
                nums = line_nums(line)

                # שם מעסיק: הטקסט לפני התאריך, או ממשיך משורה קודמת
                employer_words = []
                for w in reversed(line):
                    if DATE_RE.search(w["text"]) or MONTH_RE.search(w["text"]):
                        break
                    if not NUM_RE.match(w["text"].replace(",", "")):
                        employer_words.append(w["text"])
                employer = " ".join(employer_words).strip()

                if pending_employer:
                    employer = (pending_employer + " " + employer).strip()
                    pending_employer = None

                if len(nums) >= 5:
                    rows.append({
                        "שם המעסיק": employer,
                        "מועד":       deposit_date,
                        "חודש":       salary_month,
                        "שכר":        f"{int(nums[4]):,}",
                        "עובד":       f"{int(nums[3]):,}",
                        "מעסיק":      f"{int(nums[2]):,}",
                        "פיצויים":    f"{int(nums[1]):,}",
                        'סה"כ':       f"{int(nums[0]):,}",
                    })
                pending_employer = None
            elif lt.strip() and not any(c.isdigit() for c in lt) and pending_employer is None:
                # שורת טקסט בלי מספרים ובלי תאריך = שם מעסיק גולש
                if "שם המעסיק" not in lt and "מועד" not in lt:
                    pending_employer = lt.strip()

    # תיקון שכר בשורת סיכום
    data_rows = [r for r in rows if r.get("מועד")]
    salary_sum = sum(clean_num(r.get("שכר", 0)) for r in data_rows)
    for r in rows:
        if r.get("שם המעסיק") == 'סה"כ':
            r["שכר"] = f"{int(salary_sum):,}"

    return rows

# ════════════════════════════════════════════════════════════════════════════════
# אימות ותצוגה
# ════════════════════════════════════════════════════════════════════════════════

def perform_cross_validation(table_b_rows, table_e_rows):
    dep_b = 0.0
    for r in table_b_rows:
        if any(kw in str(r.get("תיאור", "")) for kw in ["הופקדו", "שהופקדו"]):
            dep_b = clean_num(r.get('סכום בש"ח', 0))
            break
    dep_e = clean_num(table_e_rows[-1].get('סה"כ', 0)) if table_e_rows else 0.0
    if abs(dep_b - dep_e) < 5 and dep_e > 0:
        st.markdown(f'<div class="val-success">✅ אימות הצלבה עבר: סכום ההפקדות ({dep_e:,.0f} ₪) תואם במדויק.</div>', unsafe_allow_html=True)
    elif dep_e > 0:
        st.markdown(f'<div class="val-error">⚠️ שגיאת אימות: טבלה ב\' ({dep_b:,.0f} ₪) לעומת טבלה ה\' ({dep_e:,.0f} ₪).</div>', unsafe_allow_html=True)

def display_table(rows, title, col_order):
    if not rows:
        st.warning(f"{title} — לא נמצאו נתונים")
        return
    df = pd.DataFrame(rows)
    existing = [c for c in col_order if c in df.columns]
    df = df[existing]
    df.index = range(1, len(df) + 1)
    st.subheader(title)
    st.table(df)

# ════════════════════════════════════════════════════════════════════════════════
# ממשק משתמש
# ════════════════════════════════════════════════════════════════════════════════

st.title("📋 חילוץ נתונים פנסיוני - גירסה 31.0")
st.caption("חילוץ מדויק 100% לפי קואורדינטות XY — ללא AI, ללא עיגולים")

file = st.file_uploader("העלה דוח PDF", type="pdf")
if file:
    file_bytes = file.read()
    with st.spinner("מחלץ לפי קואורדינטות..."):
        words      = extract_words_with_coords(file_bytes)
        lines_map  = group_into_lines(words)

        table_a = extract_table_a(lines_map)
        table_b = extract_table_b(lines_map)
        table_c = extract_table_c(lines_map)
        table_d = extract_table_d(lines_map)
        table_e = extract_table_e(lines_map)

    perform_cross_validation(table_b, table_e)

    display_table(table_a, "א. תשלומים צפויים",   ["תיאור", 'סכום בש"ח'])
    display_table(table_b, "ב. תנועות בקרן",       ["תיאור", 'סכום בש"ח'])
    display_table(table_c, "ג. דמי ניהול והוצאות", ["תיאור", "אחוז"])
    display_table(table_d, "ד. מסלולי השקעה",       ["מסלול", "תשואה"])
    display_table(table_e, "ה. פירוט הפקדות",
                  ["שם המעסיק", "מועד", "חודש", "שכר", "עובד", "מעסיק", "פיצויים", 'סה"כ'])

    # Debug: הצגת כל המילים עם קואורדינטות (אופציונלי)
    if st.checkbox("🔍 הצג נתוני debug (מילים + קואורדינטות)"):
        st.subheader("מילים שחולצו")
        df_words = pd.DataFrame(words)
        st.dataframe(df_words, use_container_width=True)

