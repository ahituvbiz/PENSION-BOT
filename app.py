import streamlit as st
import anthropic
import base64
import json
import math
import re
from collections import defaultdict
from html import escape as html_escape

from core.pension_core import (
    SYSTEM_PROMPT, USER_PROMPT,
    format_number, g,
    get_payment_value, get_movement_value,
    detect_deposit_source, validate_report,
    compute_analysis, check_insurance,
    FUND_PLANS, ADVISOR_PLAN, MAX_FEES,
    extract_fee_rates, calc_annual_fee,
    EQUITY_TRACKS, MADEDEI_WARNING_FUNDS,
    find_fund_key, is_equity_track, is_age_related_track,
    GOV_EMPLOYERS, GOV_ADVISORY_URL, is_gov_employer,
)

# ─── Security Constants ───
MAX_PDF_SIZE_KB = 400  # Maximum PDF size in KB
MAX_ANALYSES_PER_SESSION = 10  # Rate limit per session


# ─── Safe HTML helper ───
def safe(text):
    """Escape text for safe HTML rendering. Prevents XSS."""
    if text is None:
        return "—"
    return html_escape(str(text))

# ─── Page Config ───
# VERSION: 2026-03-04-v13 (auto-detect שכיר/עצמאי)
st.set_page_config(
    page_title="מנתח דוחות פנסיה",
    page_icon="📊",
    layout="centered",
)

# ─── Custom CSS for RTL + Dark styling ───
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;600;700;800&family=Alef:wght@400;700&display=swap');

/* Global RTL */
.stApp, .main, .block-container {
    direction: rtl;
    font-family: 'Alef', sans-serif !important;
    font-size: 1.15rem !important;
}

/* Headings use Heebo */
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] h4 {
    font-family: 'Heebo', sans-serif !important;
    text-align: right;
    direction: rtl;
}

/* Hide anchor links next to headers */
.stMarkdown h1 a, .stMarkdown h2 a, .stMarkdown h3 a, .stMarkdown h4 a,
[data-testid="stMarkdownContainer"] h1 a,
[data-testid="stMarkdownContainer"] h2 a,
[data-testid="stMarkdownContainer"] h3 a,
[data-testid="stMarkdownContainer"] h4 a {
    display: none !important;
}

/* Force right-align and font on all markdown and alert content */
.stMarkdown, .stAlert, .stMarkdown p,
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] span,
[data-testid="stAlert"] p,
[data-testid="stAlert"] span {
    text-align: right;
    direction: rtl;
    font-family: 'Alef', sans-serif !important;
    font-size: 1.15rem !important;
}

/* Table cells */
.pension-table td, .pension-table th {
    font-family: 'Alef', sans-serif !important;
    font-size: 1.05rem !important;
}

/* Hero section */
.hero-title {
    text-align: center;
    font-size: 2.4rem;
    font-weight: 800;
    font-family: 'Heebo', sans-serif;
    background: linear-gradient(135deg, #38bdf8, #a78bfa, #f472b6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 4px;
}
.hero-sub {
    text-align: center;
    color: #94a3b8;
    font-size: 1rem;
    margin-bottom: 32px;
}

/* Summary cards */
.summary-row {
    display: flex;
    gap: 12px;
    margin-bottom: 24px;
    flex-wrap: wrap;
}
.summary-card {
    flex: 1;
    min-width: 140px;
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid #1e293b;
    border-radius: 12px;
    padding: 16px;
    text-align: center;
}
.sc-label {
    font-size: 0.75rem;
    color: #64748b;
    margin-bottom: 4px;
}
.sc-value {
    font-size: 1.1rem;
    font-weight: 700;
    color: #e2e8f0;
}
.sc-highlight {
    background: linear-gradient(135deg, #38bdf8, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

/* Table styling */
.pension-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.88rem;
    direction: rtl;
}
.pension-table thead th {
    padding: 12px 14px;
    background: rgba(30, 41, 59, 0.7);
    color: #94a3b8;
    font-weight: 600;
    font-size: 0.8rem;
    text-align: right;
    border-bottom: 1px solid #334155;
}
.pension-table tbody td {
    padding: 11px 14px;
    border-bottom: 1px solid rgba(30, 41, 59, 0.5);
    color: #cbd5e1;
}
.pension-table tbody tr:hover td {
    background: rgba(56, 189, 248, 0.03);
}
.num-cell {
    text-align: left;
    font-variant-numeric: tabular-nums;
    font-weight: 500;
    direction: ltr;
    unicode-bidi: embed;
}
.neg {
    color: #f87171 !important;
}
.label-cell {
    font-weight: 600;
    color: #94a3b8;
    width: 160px;
}
.value-cell {
    color: #e2e8f0;
    font-weight: 500;
}
.total-row td {
    background: rgba(56, 189, 248, 0.06) !important;
    font-weight: 700 !important;
    border-top: 2px solid rgba(56, 189, 248, 0.2);
    color: #38bdf8 !important;
}
.total-cell {
    color: #38bdf8 !important;
    font-weight: 700;
}
.empty-msg {
    text-align: center;
    color: #475569;
    padding: 24px;
    font-style: italic;
}

/* Hide Streamlit defaults */
.stDeployButton, header[data-testid="stHeader"] { display: none !important; }
[data-testid="stToolbar"] { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }
.viewerBadge_container__r5tak { display: none !important; }
iframe[title="streamlit_app"] + div { display: none !important; }
#MainMenu { display: none !important; }
footer { display: none !important; }

/* Radio buttons RTL fix */
.stRadio > div { direction: rtl; }
.stRadio label { font-family: 'Alef', sans-serif; }
.stCheckbox label { font-family: 'Alef', sans-serif; }
</style>
""", unsafe_allow_html=True)

# ─── Helper Functions (app.py-only) ───
def is_negative(n):
    """Check if a value is negative."""
    if n is None or n == "":
        return False
    try:
        return float(n) < 0
    except (ValueError, TypeError):
        return False


def num_td(value, is_total=False):
    """Generate a table cell for a number, with red color if negative."""
    classes = ["num-cell"]
    if is_negative(value):
        classes.append("neg")
    if is_total:
        classes.append("total-cell")
    return f'<td class="{" ".join(classes)}">{safe(format_number(value))}</td>'


def call_anthropic(pdf_bytes):
    """Send PDF to Anthropic API and return parsed JSON."""
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        st.error("מפתח API לא הוגדר. הגדר ANTHROPIC_API_KEY ב-Secrets.")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": USER_PROMPT},
                    ],
                }
            ],
        )
    except anthropic.BadRequestError as e:
        error_msg = str(e.message) if hasattr(e, 'message') else str(e)
        if "credit balance" in error_msg.lower():
            st.error("שגיאה: אין מספיק קרדיט ב-API. יש לרכוש קרדיט נוסף.")
        else:
            st.error("שגיאה בעיבוד הדוח. נסה שוב או העלה דוח אחר.")
        return None
    except anthropic.APIError:
        st.error("שגיאה בתקשורת עם שרת ה-AI. נסה שוב מאוחר יותר.")
        return None

    text = "".join(block.text for block in message.content if hasattr(block, "text"))
    clean = text.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        st.error("שגיאה בפענוח התשובה מה-AI. נסה שוב.")
        return None




def render_insurance_analysis(data, user_profile, analysis=None):
    """Render the insurance analysis section."""
    if analysis is None:
        analysis = compute_analysis(data, user_profile)
    warnings = check_insurance(analysis, user_profile)

    st.markdown("### 🛡️ בחינת הכיסויים הביטוחיים בקרן")

    # ── Show computed values ──
    age = analysis.get("estimated_age")
    if age:
        st.markdown(f"**גיל משוער:** {age:.0f}")

    if analysis.get("deposit_source") == "שכיר + עצמאי":
        # This shouldn't happen (caught earlier) but just in case
        pass
    elif analysis.get("can_calc_income"):
        income = analysis["insured_income"]
        rate = analysis["deposit_rate"]
        deposit_source = analysis.get("deposit_source", "שכיר")
        rate_note = ""
        if deposit_source == "עצמאי" and analysis.get("deposit_rate_non_default"):
            rate_note = " (שים לב - החישוב נעשה שלא לפי שיעור הפקדה ברירת מחדל – 16%)"
        st.markdown(f"**הכנסה מבוטחת:** ₪{income:,} &nbsp;|&nbsp; **שיעור הפקדה:** {rate}%{rate_note}", unsafe_allow_html=True)

    st.markdown("---")

    # ── Show warnings if any ──
    if warnings:
        for icon, msg in warnings:
            formatted = msg.replace("\n", "  \n")
            if icon == "🔴":
                st.error(f"{icon} {formatted}")
            else:
                st.warning(f"{icon} {formatted}")
        # Show disability info even when there are warnings
        disability_val_num = analysis.get("disability_pension", 0)
        if disability_val_num > 0:
            disability_val = format_number(disability_val_num)
            st.info(f"במקרה של נכות של 75% ומעלה הקרן תשלם קצבה חודשית של **₪{disability_val}**.")
    else:
        # ── Default: everything looks good ──
        gender = user_profile.get("gender", "גבר")
        spouse_word = "לאשתך" if gender == "גבר" else "לבעלך"

        spouse_val_num = analysis.get("spouse_pension", 0)
        orphan_val_num = analysis.get("orphan_pension", 0)
        total_survivors = spouse_val_num + orphan_val_num
        spouse_val = format_number(spouse_val_num)
        orphan_val = format_number(orphan_val_num)
        total_survivors_val = format_number(total_survivors)
        disability_val = format_number(analysis.get("disability_pension", 0))

        nimtsa = g(gender, "נמצא", "נמצאת")
        msg = f"""מהדוח נראה ש{g(gender, 'אתה', 'את')} {nimtsa} במסלול ביטוח עם כיסויים מקסימליים.

הקרן מבטיחה {spouse_word} קצבה חודשית של **₪{spouse_val}** לכל החיים אם ח"ו יקרה לך משהו.
בנוסף הקרן תשלם **₪{orphan_val}** בכל חודש עד שהילד הקטן יגיע לגיל 21, ובסך הכל **₪{total_survivors_val}**.

במקרה של נכות של 75% ומעלה הקרן תשלם קצבה חודשית של **₪{disability_val}**."""
        st.success(msg)


# ─── בדיקת דמי ניהול ───


def build_gauge_svg(value_pct, cheapest_amount=0, max_amount=0):
    """Build an SVG half-circle gauge. 0% = cheapest (right/green), 100% = most expensive (left/red)."""
    # Angle: 0 (right, green/cheap) to 180 (left, red/expensive)
    angle = (value_pct / 100) * 180
    angle_rad = math.radians(angle)

    cheap_label = f"₪{cheapest_amount:,}" if cheapest_amount else ""
    expensive_label = f"₪{max_amount:,}" if max_amount else ""

    svg = f"""
    <svg viewBox="0 0 380 180" xmlns="http://www.w3.org/2000/svg" style="max-width:420px;margin:0 auto;display:block;">
      <defs>
        <linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" style="stop-color:#ef4444"/>
          <stop offset="50%" style="stop-color:#f59e0b"/>
          <stop offset="100%" style="stop-color:#22c55e"/>
        </linearGradient>
      </defs>
      <!-- Arc background -->
      <path d="M 70 145 A 120 120 0 0 1 310 145" fill="none" stroke="#1e293b" stroke-width="22" stroke-linecap="round"/>
      <!-- Colored arc -->
      <path d="M 70 145 A 120 120 0 0 1 310 145" fill="none" stroke="url(#gaugeGrad)" stroke-width="18" stroke-linecap="round"/>
      <!-- Needle -->
      <line x1="190" y1="145" x2="{190 + 93 * math.cos(angle_rad):.1f}" y2="{145 - 93 * math.sin(angle_rad):.1f}" stroke="#000000" stroke-width="3" stroke-linecap="round"/>
      <circle cx="190" cy="145" r="6" fill="#000000"/>
      <!-- Labels outside edges -->
      <text x="28" y="150" fill="#ef4444" font-size="13" font-family="Alef" font-weight="600" text-anchor="middle">יקר</text>
      <text x="352" y="150" fill="#22c55e" font-size="13" font-family="Alef" font-weight="600" text-anchor="middle">זול</text>
      <!-- Fee amounts near edges -->
      <text x="82" y="172" fill="#94a3b8" font-size="10" font-family="Alef" text-anchor="middle">{expensive_label}</text>
      <text x="298" y="172" fill="#94a3b8" font-size="10" font-family="Alef" text-anchor="middle">{cheap_label}</text>
    </svg>
    """
    return svg


def render_fee_analysis(data, analysis, user_profile):
    """Render fee analysis section with gauge and comparison table."""
    st.markdown("### 🏷️ בחינת דמי ניהול")
    gender = user_profile.get("gender", "גבר")

    closing_balance = analysis.get("closing_balance", 0)
    if not closing_balance or closing_balance <= 0:
        st.info("אין מספיק נתונים לבחינת דמי ניהול.")
        return

    # Extract current fee rates
    deposit_fee, savings_fee = extract_fee_rates(data)
    if deposit_fee == 0 and savings_fee == 0:
        st.info("לא נמצאו נתוני דמי ניהול בדוח.")
        return

    # Calculate projected annual deposit from actual deposits in report
    total_deposits = analysis.get("total_deposits", 0)
    report_period = analysis.get("report_period", "")
    if "רבעון 1" in report_period or "רבעון ראשון" in report_period:
        annual_deposit = total_deposits * 4
    elif "רבעון 2" in report_period or "רבעון שני" in report_period:
        annual_deposit = total_deposits * 2
    elif "רבעון 3" in report_period or "רבעון שלישי" in report_period:
        annual_deposit = round(total_deposits * 4 / 3)
    elif "רבעון 4" in report_period or "רבעון רביעי" in report_period:
        annual_deposit = total_deposits
    else:
        annual_deposit = total_deposits
    monthly_deposit = annual_deposit / 12
    avg_savings = closing_balance * 1.02 + 6 * monthly_deposit

    # Current fees
    current_fee = calc_annual_fee(deposit_fee, savings_fee, annual_deposit, avg_savings)

    # Maximum fees
    max_fee = calc_annual_fee(MAX_FEES[0], MAX_FEES[1], annual_deposit, avg_savings)

    # Build all options with fund names: (fund_name, dep%, sav%, annual_fee)
    all_options = []
    for fund_name, plans in FUND_PLANS.items():
        for dep, sav in plans:
            fee = calc_annual_fee(dep, sav, annual_deposit, avg_savings)
            all_options.append((fund_name, dep, sav, fee))

    adv_fee = calc_annual_fee(ADVISOR_PLAN[0], ADVISOR_PLAN[1], annual_deposit, avg_savings)

    # Find cheapest (including current)
    all_fees = [current_fee] + [o[3] for o in all_options] + [adv_fee]
    cheapest_fee = min(all_fees)

    # Gauge position: 0% = cheapest, 100% = max
    if max_fee > cheapest_fee:
        gauge_pct = ((current_fee - cheapest_fee) / (max_fee - cheapest_fee)) * 100
        gauge_pct = max(0, min(100, gauge_pct))
    else:
        gauge_pct = 50

    # ── Display current fees ──
    st.markdown(f"""
**דמי הניהול שלך:** {deposit_fee}% מהפקדה + {savings_fee}% מצבירה
**עלות שנתית צפויה:** ₪{format_number(round(current_fee))}
""")

    # ── Gauge ──
    st.markdown(build_gauge_svg(gauge_pct, round(cheapest_fee), round(max_fee)), unsafe_allow_html=True)
    st.markdown(f'<div style="text-align:center;color:#94a3b8;font-size:0.85rem;margin-top:4px;">דמי הניהול שלך ביחס לטווח האפשרויות</div>', unsafe_allow_html=True)

    # ── Recommendations ──

    # Sort non-advisor options by fee
    all_options.sort(key=lambda x: x[3])

    # Find cheapest non-advisor option (may have multiple funds with same fee)
    cheapest_fund_fee = all_options[0][3] if all_options else None
    cheapest_fund_dep = all_options[0][1] if all_options else None
    cheapest_fund_sav = all_options[0][2] if all_options else None

    # All fund names that offer the cheapest plan
    cheapest_fund_names = []
    if cheapest_fund_fee is not None:
        cheapest_fund_names = list(set(
            o[0] for o in all_options if abs(o[3] - cheapest_fund_fee) < 1
        ))

    # Is advisor cheapest overall?
    advisor_is_cheapest = adv_fee < cheapest_fund_fee if cheapest_fund_fee else False

    # Max possible saving
    max_saving = current_fee - cheapest_fee

    if current_fee <= cheapest_fee * 1.05:
        st.success("✅ דמי הניהול שלך ברמה תחרותית מאוד!")
    elif max_saving < 100:
        st.success("✅ דמי הניהול שלך ברמה תחרותית מאוד!")
    elif advisor_is_cheapest and adv_fee < current_fee:
        # Advisor is cheapest - show second best (fund) first, then advisor
        fund_saving = current_fee - cheapest_fund_fee
        adv_saving = current_fee - adv_fee
        fund_names_str = " / ".join(cheapest_fund_names)

        msg = f"""בקרן הפנסיה של **{fund_names_str}** {g(gender, 'תוכל', 'תוכלי')} לקבל דמי ניהול של {cheapest_fund_dep}% מהפקדה + {cheapest_fund_sav}% מצבירה.
{g(gender, 'תוכל', 'תוכלי')} לחסוך בשנה הבאה בערך **₪{format_number(round(fund_saving))}**.

יועץ פנסיוני יוכל להשיג לך דמי ניהול של 1% על ההפקדה ו-0.145% מהצבירה.
כך {g(gender, 'תחסוך', 'תחסכי')} בשנה הבאה בערך **₪{format_number(round(adv_saving))}**."""
        st.info(f"💡 {msg}")
        if any("אלטשולר" in name for name in cheapest_fund_names):
            st.warning(f"⚠️ יחד עם זאת {g(gender, 'קח', 'קחי')} בחשבון שהתשואות של אלטשולר בלטו לרעה בשנים האחרונות.")
    elif cheapest_fund_fee is not None and cheapest_fund_fee < current_fee:
        # Fund is cheapest
        fund_saving = current_fee - cheapest_fund_fee
        fund_names_str = " / ".join(cheapest_fund_names)

        msg = f"""בקרן הפנסיה של **{fund_names_str}** {g(gender, 'תוכל', 'תוכלי')} לקבל דמי ניהול של {cheapest_fund_dep}% מהפקדה + {cheapest_fund_sav}% מצבירה.
{g(gender, 'תוכל', 'תוכלי')} לחסוך בשנה הבאה בערך **₪{format_number(round(fund_saving))}**."""
        st.info(f"💡 {msg}")
        if any("אלטשולר" in name for name in cheapest_fund_names):
            st.warning(f"⚠️ יחד עם זאת {g(gender, 'קח', 'קחי')} בחשבון שהתשואות של אלטשולר בלטו לרעה בשנים האחרונות.")

        # Also mention advisor if even cheaper
        if adv_fee < current_fee:
            adv_saving = current_fee - adv_fee
            st.info(f"💡 יועץ פנסיוני יוכל להשיג לך דמי ניהול של 1% על ההפקדה ו-0.145% מהצבירה. כך {g(gender, 'תחסוך', 'תחסכי')} בשנה הבאה בערך **₪{format_number(round(adv_saving))}**.")

    # ── Menorah warning ──
    fund_name_str = analysis.get("fund_name", "")
    if "מנורה" in fund_name_str:
        actuarial_cost = get_movement_value(data.get("movements", []), "אקטוארי")
        msg = f"""{g(gender, 'שים', 'שימי')} לב, בדוח מופיע שהורידו לך **₪{format_number(round(actuarial_cost))}** בתקופת הדוח בגלל הגרעון האקטוארי של הקרן.
קרן הפנסיה של מנורה היא באופן כמעט עקבי עם האיזון האקטוארי הגרוע ביותר מה שגורע מהצבירה הפנסיונית שלך.
ב-5 השנים האחרונות הגרעון הממוצע של הקרן היה 0.19% בשעה שיש קרנות שהחזירו כסף לחוסכים אצלם!
ההשפעה של גרעון אקטוארי שקולה להשפעה של דמי ניהול מצבירה.
{g(gender, 'שקול', 'שיקלי')} לעבור לקרן פנסיה אחרת ובפרט קרנות שהציגו איזון אקטוארי חיובי, גם אם דמי הניהול יהיו מעט יותר גבוהים."""
        formatted = msg.replace("\n", "  \n")
        st.warning(f"⚠️ {formatted}")

# ─── עד כאן בדיקת דמי ניהול ───


# ─── בחינת הפקדות ───

def render_deposit_chart(data, analysis, user_profile):
    """Render a bar chart of monthly salaries deposited."""
    deposit_source = detect_deposit_source(data)
    gender = st.session_state.get("user_profile", {}).get("gender", "גבר")
    st.markdown("### 💰 בדיקת הפקדות")
    if deposit_source == "עצמאי":
        st.markdown("**📊 ההפקדות החודשיות לקרן**")
    else:
        st.markdown("**📊 השכר החודשי עליו בוצעו הפקדות לקרן**")

    deposits = data.get("deposits", [])
    late_deposits = data.get("late_deposits", [])
    all_deposits = deposits + late_deposits

    if not all_deposits:
        st.info("אין נתוני הפקדות להצגה.")
        return

    # Determine report year from report_period
    report_period = data.get("header", {}).get("report_period", "")
    report_date = data.get("header", {}).get("report_date", "")

    # Extract report year
    report_year = None
    year_match = re.search(r'20\d{2}', report_period)
    if year_match:
        report_year = int(year_match.group())
    elif report_date:
        year_match = re.search(r'20\d{2}', report_date)
        if year_match:
            report_year = int(year_match.group())

    if not report_year:
        st.info("לא ניתן לזהות את שנת הדוח.")
        return

    # Group data by month - only current year, skip previous years
    # salary_month format: "MM/YYYY"
    # For עצמאי: show total deposits. For שכיר: show salary.
    monthly_salaries = defaultdict(list)
    value_field = "total" if deposit_source == "עצמאי" else "salary"

    for dep in all_deposits:
        sm = dep.get("salary_month", "")
        value = dep.get(value_field)
        if value is None:
            value = dep.get("salary")
        if value is None:
            value = dep.get("total")
        if not value:
            continue

        # For self-employed, salary_month may be missing - fall back to deposit_date
        if not sm:
            dd = dep.get("deposit_date", "")
            if dd:
                # deposit_date format: DD/MM/YYYY or DD.MM.YYYY
                try:
                    parts = dd.replace(".", "/").split("/")
                    if len(parts) == 3:
                        sm = f"{parts[1]}/{parts[2]}"
                except Exception:
                    pass
        if not sm:
            continue

        try:
            parts = sm.split("/")
            if len(parts) == 2:
                month_num = int(parts[0])
                year_num = int(parts[1])
                # Handle 2-digit year (e.g. "24" -> 2024)
                if year_num < 100:
                    year_num += 2000
                if year_num == report_year and 1 <= month_num <= 12:
                    monthly_salaries[month_num].append(float(value))
        except (ValueError, IndexError):
            continue

    if not monthly_salaries:
        st.info("אין נתוני הפקדות לשנת הדוח להצגה.")
        return

    # ── Determine report period end month ──
    period_end_month = 12  # default: annual
    last_month_name = "דצמבר"
    period_label = "השנה"

    if "רבעון 1" in report_period or "רבעון ראשון" in report_period or "הרבעון הראשון" in report_period:
        period_end_month = 3
        last_month_name = "מרץ"
        period_label = "הרבעון"
    elif "רבעון 2" in report_period or "רבעון שני" in report_period or "הרבעון השני" in report_period:
        period_end_month = 6
        last_month_name = "יוני"
        period_label = "הרבעון"
    elif "רבעון 3" in report_period or "רבעון שלישי" in report_period or "הרבעון השלישי" in report_period:
        period_end_month = 9
        last_month_name = "ספטמבר"
        period_label = "הרבעון"
    elif "רבעון 4" in report_period or "רבעון רביעי" in report_period or "הרבעון הרביעי" in report_period:
        period_end_month = 12
        last_month_name = "דצמבר"
        period_label = "הרבעון"

    # Build SVG bar chart - show months up to period end
    months = list(range(1, period_end_month + 1))
    num_months = len(months)
    max_salary = max(sum(monthly_salaries.get(m, [0])) for m in months)
    if max_salary == 0:
        max_salary = 1

    chart_w = 600
    chart_h = 250
    bar_area_h = 180
    margin_top = 30
    margin_bottom = 40
    bar_w = min(36, int((chart_w - 20) / num_months * 0.7))
    gap = (chart_w - num_months * bar_w) / (num_months + 1)

    # Check if last month of period has a deposit (for asterisk in chart)
    last_month_has_deposit = bool(monthly_salaries.get(period_end_month))

    svg = f'<svg viewBox="0 0 {chart_w} {chart_h}" xmlns="http://www.w3.org/2000/svg" style="max-width:100%;margin:0 auto;display:block;direction:ltr;">'

    # Bars
    for i, m in enumerate(months):
        x = gap + i * (bar_w + gap)
        salaries = monthly_salaries.get(m, [])
        total = sum(salaries)

        # Draw single bar based on net total (not stacked)
        if total > 0:
            bar_h = (total / max_salary) * bar_area_h if max_salary > 0 else 0
            y_top = margin_top + bar_area_h - bar_h
            color = "#38bdf8"
            svg += f'<rect x="{x}" y="{y_top:.1f}" width="{bar_w}" height="{bar_h:.1f}" rx="3" fill="{color}" opacity="0.85"/>'

        # Month label below - add red * to last month if no deposit found
        if m == period_end_month and not last_month_has_deposit:
            svg += f'<text x="{x + bar_w/2}" y="{margin_top + bar_area_h + 18}" text-anchor="middle" font-size="12" font-family="Alef">'
            svg += f'<tspan fill="#94a3b8">{m}</tspan>'
            svg += f'<tspan fill="#ef4444" font-size="16" font-weight="bold" dy="-4">*</tspan>'
            svg += '</text>'
        else:
            svg += f'<text x="{x + bar_w/2}" y="{margin_top + bar_area_h + 18}" text-anchor="middle" fill="#94a3b8" font-size="12" font-family="Alef">{m}</text>'

        # Total salary above bar
        if total > 0:
            bar_total_h = (total / max_salary) * bar_area_h
            y_label = margin_top + bar_area_h - bar_total_h - 6
            svg += f'<text x="{x + bar_w/2}" y="{y_label:.1f}" text-anchor="middle" fill="#e2e8f0" font-size="9" font-family="Alef">{total:,.0f}</text>'

    svg += '</svg>'
    st.markdown(svg, unsafe_allow_html=True)

    # ── Summary ──
    expected_months = list(range(1, period_end_month))  # months 1 to end-1
    display_months = list(range(1, period_end_month + 1))  # for display including last

    all_totals = [sum(monthly_salaries.get(m, [])) for m in display_months if monthly_salaries.get(m)]
    if all_totals:
        avg_val = sum(all_totals) / len(all_totals)
        months_with_deposits = len(all_totals)
        total_expected = len(display_months)
        avg_label = "הפקדה ממוצעת" if deposit_source == "עצמאי" else "שכר ממוצע"
        st.markdown(f"**{avg_label}:** ₪{format_number(round(avg_val))} &nbsp;|&nbsp; **חודשים עם הפקדות בשנת {report_year}:** {months_with_deposits}/{total_expected}", unsafe_allow_html=True)

    # Check missing deposits only for months that SHOULD have been deposited during the period
    missing_expected = [m for m in expected_months if not monthly_salaries.get(m)]
    if missing_expected:
        missing_str = ", ".join(str(m) for m in missing_expected)
        if deposit_source == "עצמאי":
            st.warning(f"⚠️ לא נמצאו הפקדות עבור חודשים: {missing_str}. {g(gender, 'וודא', 'וודאי')} שלא ביצעת הפקדות נוספות שלא נקלטו בחשבונך בקרן.")
        else:
            st.warning(f"⚠️ לא נמצאו הפקדות עבור חודשים: {missing_str}. יש לוודא שהמעסיק הפקיד את כל ההפקדות.")

    # Note about last month deposit - with matching red asterisk
    if not last_month_has_deposit:
        st.markdown(f'<div style="background:#dbeafe;border-radius:8px;padding:14px 18px;color:#1e40af;font-size:1.1rem;direction:rtl;text-align:right;margin-top:8px;"><span style="color:#ef4444;font-weight:bold;font-size:1.4rem;">*</span> ההפקדה בגין חודש {last_month_name} בדרך כלל מתבצעת אחרי סוף {period_label} ולכן לא מופיעה בדוח זה.</div>', unsafe_allow_html=True)

    # Low deposit rate warning (moved here from insurance section)
    deposit_source_val = analysis.get("deposit_source", "שכיר")
    deposit_rate_val = analysis.get("deposit_rate", 0)
    can_calc_val = analysis.get("can_calc_income", False)
    if can_calc_val and deposit_source_val == "שכיר" and deposit_rate_val < 18.48:
        gender = user_profile.get("gender", "גבר")
        low_rate_msg = f"""{g(gender, 'שים', 'שימי')} לב, שיעור ההפקדות מתוך השכר נראה נמוך מהמינימום לפי חוק (6% תגמולי עובד + 6.5% תגמולי מעסיק + 6% פיצויים).
ייתכן שמופקד לך לפנסיה גם על החזרי הוצאות (במקרה זה מקובל להפקיד רק 5% עובד ו-5% מעסיק). אחרת {g(gender, 'בדוק', 'בדקי')} מה הסיבה לכך."""
        formatted_lr = low_rate_msg.replace("\n", "  \n")
        st.error(f"⚠️ {formatted_lr}")

    # Self-employed excess deposit warning (above tax benefit threshold)
    if deposit_source_val == "עצמאי" and report_year and report_year >= 2025:
        gender = user_profile.get("gender", "גבר")
        # Check last 3 months of reporting period
        last_3_months = list(range(max(1, period_end_month - 2), period_end_month + 1))
        last_3_totals = [sum(monthly_salaries.get(m, [])) for m in last_3_months]
        last_3_above = all(t > 3201 for t in last_3_totals if t > 0)
        # Also check if more than 3 months above threshold
        all_monthly_totals = [sum(monthly_salaries.get(m, [])) for m in range(1, period_end_month + 1) if monthly_salaries.get(m)]
        months_above = sum(1 for t in all_monthly_totals if t > 3201)
        # Annual total
        annual_total_deposits = sum(sum(monthly_salaries.get(m, [])) for m in range(1, period_end_month + 1))
        # Annualize if quarterly report
        if period_end_month <= 3:
            projected_annual = annual_total_deposits * 4
        elif period_end_month <= 6:
            projected_annual = annual_total_deposits * 2
        elif period_end_month <= 9:
            projected_annual = round(annual_total_deposits * 4 / 3)
        else:
            projected_annual = annual_total_deposits

        if (last_3_above and len([t for t in last_3_totals if t > 0]) >= 3) or months_above > 3 or projected_annual > 38412:
            excess_msg = f"""{g(gender, 'אתה מפקיד', 'את מפקידה')} סכום שהוא מעבר לסכום שמקנה לך הטבות מס.
ייתכן מאוד שכדאי להתייעץ האם נכון יותר {g(gender, 'עבורך', 'עבורך')} להפנות חלק מההפקדה לכלים פיננסיים אחרים שבהם {g(gender, 'אינך מוותר', 'אינך מוותרת')} על הנזילות של הכסף."""
            formatted_ex = excess_msg.replace("\n", "  \n")
            st.warning(f"⚠️ {formatted_ex}")

# ─── עד כאן בחינת הפקדות ───


# ─── בחינת מסלולי השקעה ───


def render_investment_analysis(data, analysis, user_profile):
    """Render investment track analysis."""
    st.markdown("### 📈 בחינת מסלולי השקעה")
    gender = user_profile.get("gender", "גבר")

    tracks = data.get("investment_tracks", [])
    if not tracks:
        st.info("אין נתוני מסלולי השקעה בדוח.")
        return

    # Show current tracks and returns
    html = '<table class="pension-table"><thead><tr><th>מסלול השקעה</th><th>תשואה</th></tr></thead><tbody>'
    for row in tracks:
        rate = row.get("return_rate", "")
        neg_cls = " neg" if str(rate).startswith("-") else ""
        html += f'<tr><td>{safe(row.get("track_name", ""))}</td><td class="num-cell{neg_cls}">{safe(rate)}</td></tr>'
    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)
    st.markdown("")

    age = analysis.get("estimated_age")
    if not age:
        st.info("לא ניתן לחשב גיל משוער לצורך ניתוח מסלולי השקעה.")
        return

    fund_name = analysis.get("fund_name", "")
    fund_key = find_fund_key(fund_name)
    gender = user_profile.get("gender", "גבר")
    multiplier = 196 if gender == "גבר" else 194

    # Classify user's tracks
    user_track_names = [t.get("track_name", "") for t in tracks]
    equity_tracks = []
    non_equity_tracks = []
    has_sp500 = False
    has_madedei = False
    has_age_track = False
    has_halacha = False

    for name in user_track_names:
        name_lower = name.lower().strip()
        if "s&p" in name_lower or "s&amp;p" in name_lower or "500" in name_lower:
            has_sp500 = True
        if "מדדי מניות" in name or "עוקב מדדי מניות" in name:
            has_madedei = True
        if "הלכה" in name:
            has_halacha = True

        if fund_key and is_equity_track(name, fund_key):
            equity_tracks.append(name)
        else:
            non_equity_tracks.append(name)

        if is_age_related_track(name):
            has_age_track = True

    # ── Age <= 52: recommend equity ──
    if age <= 52:
        if non_equity_tracks:
            # Has at least one non-equity track
            pension_at_67 = analysis.get("pension_at_67", 0)
            closing_balance = analysis.get("closing_balance", 0)
            years_to_67 = 67 - age

            # FV calculation with 5.25% for improved return scenario
            improved_fv = closing_balance * ((1 + 0.0525) ** years_to_67) if years_to_67 > 0 else closing_balance
            improved_pension = round(improved_fv / multiplier)

            msg = f"""בהתחשב בטווח השנים שנותר לך עד לפרישה אני ממליץ {g(gender, 'שתבחר', 'שתבחרי')} במסלול או במסלולים מנייתיים בלבד.
ב-5 השנים האחרונות המסלולים המנייתיים הניבו תשואה עודפת של כ-1.25% ביחס למסלולי 'בני 50 ומטה' (ופער גדול יותר מול יתר המסלולים).
הקצבה מהכספים {g(gender, 'שצברת', 'שצברת')} עד סוף תקופת הדוח היא **₪{format_number(pension_at_67)}**.
אם {g(gender, 'תשפר', 'תשפרי')} את התשואה ב-1.25% הקצבה על אותם כספים תגדל ל-**₪{format_number(improved_pension)}**.
כמובן שהפער יהיה גדול יותר כי התשואה העודפת תהיה גם על הכספים שיופקדו לקרן בעתיד."""
            formatted = msg.replace("\n", "  \n")
            st.info(f"💡 {formatted}")

            # Check if mixed equity + age-based track
            if equity_tracks and has_age_track:
                non_eq_names = ", ".join(non_equity_tracks)
                deposit_source = analysis.get("deposit_source", "שכיר")
                if deposit_source == "עצמאי":
                    msg2 = f"""הכסף שלך מפוצל בין מסלול מנייתי לבין מסלול שאיננו מנייתי ({non_eq_names}).
סביר להניח שבמסלול הלא מנייתי נמצאים כספי פיצויים.
{g(gender, 'בדוק', 'בדקי')} עם הקרן מה צריך לעשות בכדי להעביר אותם למסלול ההשקעה {g(gender, 'שבחרת', 'שבחרת')}."""
                else:
                    msg2 = f"""הכסף שלך מפוצל בין מסלול מנייתי לבין מסלול שאיננו מנייתי ({non_eq_names}).
סביר להניח שבמסלול הלא מנייתי נמצאים כספי הפיצויים שלך המהווים כ-30%-40% מהפנסיה שלך.
בכדי להעביר גם אותם למסלול מנייתי יש צורך באישור של המעסיק."""
                formatted2 = msg2.replace("\n", "  \n")
                st.warning(f"ℹ️ {formatted2}")

    # ── Age > 52: recommend gradual reduction ──
    else:
        st.info("💡 בהתחשב בשנים שנותרו לך לפרישה יש לבחון איך להתאים את שיעור החשיפה למניות כך שהוא יפחת באופן הדרגתי לקראת היציאה לפנסיה.")

    # ── S&P 500 warning (any age) - BEFORE recommendation ──
    if has_sp500:
        msg_sp = f"""{g(gender, 'אתה מושקע', 'את מושקעת')} במדד S&P 500. מדד זה סובל היום מריכוזיות גבוהה.
המשקל של 9 החברות הגדולות הכלולות בו הוא כ-40% מה שמגדיל את הסיכון הכרוך בהשקעה בו.
בנוסף התימחור של המניות הכלולות בו משקף מידה רבה של אופטימיות שאם היא תתברר כמוגזמת התשואה שהמדד יניב תהיה נמוכה.
מעבר לכך אין לך חשיפה למניות של חברות מוצלחות מיתר העולם."""
        formatted_sp = msg_sp.replace("\n", "  \n")
        st.warning(f"⚠️ {formatted_sp}")

    # ── מדדי מניות concentration warning (specific funds, any age) ──
    if has_madedei and fund_key in MADEDEI_WARNING_FUNDS:
        msg_md = """בפנסיה אנחנו צריכים לנהוג בזהירות. מסלול מדדי מניות הוא מסלול עם רמת ריכוז גבוהה מאוד וממילא סיכון גבוה.
המניות הכלולות בו אמנם הניבו תשואה חריגה בעבר אבל זה כרוך בסיכון שלגמרי לא בטוח שמתאים לכספי פנסיה."""
        formatted_md = msg_md.replace("\n", "  \n")
        st.warning(f"⚠️ {formatted_md}")

    # ── Halacha track warning (age <= 52, not Infinity) ──
    if has_halacha and age <= 52 and fund_key != "אינפיניטי":
        msg_hl = f"""במסלול ההלכה בקרן בה {g(gender, 'אתה נמצא', 'את נמצאת')} החשיפה למניות איננה מקסימלית.
הצפי הוא שהתשואה שלך תהיה נמוכה יותר בגלל זה.
{g(gender, 'שקול', 'שיקלי')} לעבור למסלול מותאם להלכה שיש בו חשיפה מנייתית מקסימלית בכדי לשפר את הפנסיה שלך."""
        formatted_hl = msg_hl.replace("\n", "  \n")
        st.warning(f"⚠️ {formatted_hl}")

    # ── Fund recommendation - AFTER warnings ──
    if age <= 52 and fund_key and EQUITY_TRACKS[fund_key]["recommendation"]:
        st.success(f"🤖 **המסלול המומלץ בקרן שלך:**  \n{EQUITY_TRACKS[fund_key]['recommendation']}")

# ─── עד כאן בחינת מסלולי השקעה ───


# ─── Main App ───
st.markdown('<div class="hero-title">רובייקטיבי</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-sub">מנתח דוחות פנסיה אובייקטיבי · ללא אינטרס</div>', unsafe_allow_html=True)

# ─── Questionnaire ───
st.markdown("##### פרטים אישיים")

col1, col2 = st.columns(2)

with col1:
    gender = st.radio("מין", ["גבר", "אשה"], index=None, horizontal=True)

with col2:
    marital_status = st.radio("סטטוס משפחתי", ["נשוי/אה", "רווק/ה", "גרוש/ה", "אלמן/ה"], index=None)

has_minor_children = False
if marital_status in ["גרוש/ה", "אלמן/ה"]:
    has_minor_children = st.checkbox("יש לי ילדים מתחת לגיל 21")

# Store user profile in session
st.session_state["user_profile"] = {
    "gender": gender or "גבר",
    "marital_status": marital_status or "נשוי/אה",
    "has_minor_children": has_minor_children,
}

st.markdown("---")

# ─── File Upload + Auto Analysis ───
# Custom CSS to clean up file uploader
st.markdown("""
<style>
/* Hide the default uploader label */
[data-testid="stFileUploader"] > label {
    display: none !important;
}
/* Make dropzone more compact */
[data-testid="stFileUploaderDropzone"] {
    padding: 12px 16px !important;
}
/* Hebrew upload instructions above the uploader */
.upload-instructions {
    text-align: center;
    padding: 12px 16px;
    margin-bottom: -10px;
    font-family: 'Alef', sans-serif;
}
.upload-instructions .main-text {
    font-size: 1.1rem;
    font-weight: 700;
    color: #000000;
    margin-bottom: 4px;
}
.upload-instructions .sub-text {
    font-size: 0.85rem;
    color: #64748b;
}
</style>
""", unsafe_allow_html=True)

# Prevent upload before selections
if gender is None or marital_status is None:
    st.info("יש לבחור מין וסטטוס משפחתי לפני העלאת הדוח.")
    uploaded = None
else:
    st.markdown("""
    <div class="upload-instructions">
        <div class="main-text">📄 העלה דוח פנסיה בפורמט PDF</div>
        <div class="sub-text">עד 4 עמודים · PDF בלבד</div>
    </div>
    """, unsafe_allow_html=True)
    uploaded = st.file_uploader("העלה דוח פנסיה", type=["pdf"], label_visibility="collapsed")

if uploaded is not None:
    # Auto-analyze: run if this is a new file
    file_key = f"{uploaded.name}_{uploaded.size}"
    if st.session_state.get("last_file_key") != file_key:
        # ── File size check ──
        file_size_kb = uploaded.size / 1024
        if file_size_kb > MAX_PDF_SIZE_KB:
            st.error("הקובץ גדול מדי. דוח פנסיה רגיל שוקל עד 400KB. ודא שהעלית את הקובץ הנכון.")
        else:
            # ── Rate limiting ──
            analysis_count = st.session_state.get("analysis_count", 0)
            if analysis_count >= MAX_ANALYSES_PER_SESSION:
                st.error("הגעת למגבלת הניתוחים לסשן זה. רענן את הדף כדי להתחיל מחדש.")
            else:
                result = None
                with st.spinner("מנתח את הדוח באמצעות AI... (עשוי לקחת עד דקה)"):
                    uploaded.seek(0)
                    pdf_bytes = uploaded.read()
                    if not pdf_bytes:
                        st.error("שגיאה: הקובץ ריק. נסה להעלות שוב.")
                    else:
                        result = call_anthropic(pdf_bytes)

                if result:
                    st.session_state["pension_data"] = result
                    st.session_state["last_file_key"] = file_key
                    st.session_state["analysis_count"] = analysis_count + 1
                    st.rerun()

# ─── Display Results ───
if "pension_data" in st.session_state:
    data = st.session_state["pension_data"]

    # Validate report type
    is_valid, validation_error = validate_report(data)
    if not is_valid:
        st.error(f"⚠️ {validation_error}")
    else:
        # Check for mixed deposits (שכיר + עצמאי)
        deposit_source = detect_deposit_source(data)
        if deposit_source == "שכיר + עצמאי":
            st.error("⚠️ עדיין לא למדתי לנתח דוח פנסיה שבוצעו אליה גם הפקדות כשכיר וגם הפקדות כעצמאי.")
        else:
            st.markdown('<div style="text-align:center;font-family:Heebo,sans-serif;font-size:2.2rem;font-weight:700;margin-bottom:24px;">📋 ניתוח רובייקטיבי של דוח הפנסיה</div>', unsafe_allow_html=True)
            user_profile = st.session_state.get("user_profile", {})
            analysis = compute_analysis(data, user_profile)
            render_insurance_analysis(data, user_profile, analysis)
            st.markdown("---")
            render_deposit_chart(data, analysis, user_profile)
            st.markdown("---")
            render_fee_analysis(data, analysis, user_profile)
            st.markdown("---")
            render_investment_analysis(data, analysis, user_profile)

            # ── Government employer advisory subsidy ──
            gender = user_profile.get("gender", "גבר")
            employer = data.get("header", {}).get("employer", "")
            # Also check employer from deposits table
            if not is_gov_employer(employer):
                for dep in data.get("deposits", []):
                    dep_employer = dep.get("employer", "")
                    if dep_employer and is_gov_employer(dep_employer):
                        employer = dep_employer
                        break
            if is_gov_employer(employer):
                st.markdown("---")
                gov_msg = f'החשב הכללי מעודד את עובדי המדינה לקחת ייעוץ פנסיוני אובייקטיבי. לשם כך הוא נותן סבסוד של 600 ש"ח לעובד מדינה שלוקח ייעוץ. {g(gender, "קח", "קחי")} ייעוץ פנסיוני {g(gender, "ונצל", "ונצלי")} את ההטבה הזו. <a href="{safe(GOV_ADVISORY_URL)}" target="_blank">לצפייה בחוזר החשב הכללי {g(gender, "לחץ", "לחצי")} כאן</a>.'
                st.markdown(f'<div style="background:#f0fdf4;border-radius:8px;padding:14px 18px;color:#166534;font-size:1.1rem;direction:rtl;text-align:right;">💡 {gov_msg}</div>', unsafe_allow_html=True)

            # ── High income recommendation (before CTA) ──
            insured_income = analysis.get("insured_income", 0)
            if insured_income and insured_income > 20000:
                high_income_msg = """בהתאם לגובה ההכנסות שלכם יש סיכוי גבוה שתוכלו להניב תועלת גדולה מייעוץ פנסיוני אובייקטיבי.
יועץ פנסיוני (בניגוד לרובוט) יכול לראות את התמונה המלאה של הכלים הפיננסיים בהם אתם עושים שימוש — תכניות הפנסיה השונות, קרנות השתלמות, גמל להשקעה ועוד — וכן של הביטוחים שאתם רוכשים.
מכיוון שהוא לא נמצא בניגוד עניינים אתכם (אסור לו לפי חוק לקבל עמלות מהחברות) תוכלו להיות רגועים שאתם בוחרים בצורה אופטימלית במוצרים הפיננסיים השונים."""
                formatted_hi = high_income_msg.replace("\n", "  \n")
                st.markdown("---")
                st.info(f"💡 {formatted_hi}")

            # ── Consultation CTA ──
            st.markdown("---")
            st.markdown("""
            <div style="text-align:center;padding:24px 16px;margin-top:8px;">
                <div style="font-family:'Alef',sans-serif;font-size:1.1rem;color:#000000;margin-bottom:16px;direction:rtl;">
                    🗣️ רוצה שיועץ פנסיוני יעבור איתך על הדוח ויענה על השאלות שלך?
                </div>
                <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
                    <a href="https://meshulam.co.il/s/9b71389b-1564-a6c6-5f08-883647e04c53" target="_blank"
                       style="display:inline-block;padding:14px 32px;font-family:'Heebo',sans-serif;font-size:1.05rem;font-weight:700;
                       color:white;background:linear-gradient(135deg,#38bdf8,#a78bfa);border-radius:10px;text-decoration:none;
                       box-shadow:0 4px 16px rgba(56,189,248,0.25);">
                        📅 לקביעת שיחת הסבר
                    </a>
                    <a href="https://api.whatsapp.com/send/?phone=972527700599&text=%D7%90%D7%97%D7%99%D7%98%D7%95%D7%91+%D7%A9%D7%9C%D7%95%D7%9D.+%D7%90%D7%A9%D7%9E%D7%97+%D7%9C%D7%A7%D7%91%D7%9C+%D7%A4%D7%A8%D7%98%D7%99%D7%9D+%D7%A2%D7%9C+%D7%99%D7%99%D7%A2%D7%95%D7%A5+%D7%A4%D7%A0%D7%A1%D7%99%D7%95%D7%A0%D7%99+%D7%9E%D7%A7%D7%99%D7%A3+%D7%95%D7%90%D7%95%D7%91%D7%99%D7%99%D7%A7%D7%98%D7%99%D7%91%D7%99" target="_blank"
                       style="display:inline-block;padding:14px 32px;font-family:'Heebo',sans-serif;font-size:1.05rem;font-weight:700;
                       color:white;background:#25D366;border-radius:10px;text-decoration:none;
                       box-shadow:0 4px 16px rgba(37,211,102,0.25);">
                        💬 שלח הודעה בווצאפ
                    </a>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # ── Print CSS for PDF export ──
            st.markdown("""
            <style>
            @media print {
                .stRadio, .stCheckbox, [data-testid="stFileUploader"],
                [data-testid="stToolbar"], [data-testid="stHeader"],
                .stDeployButton, .stSpinner, #MainMenu, footer,
                .no-print, [data-testid="stFileUploaderDropzone"],
                .upload-instructions, .save-pdf-area {
                    display: none !important;
                }
                body, .stApp, .main, .block-container {
                    direction: rtl !important;
                    font-family: 'Alef', sans-serif !important;
                }
                /* Force color printing */
                * {
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                    color-adjust: exact !important;
                }
                .stApp, .main, .block-container, [data-testid="stAppViewContainer"] {
                    background: white !important;
                }
                .stMarkdown, .stMarkdown p, [data-testid="stMarkdownContainer"] p {
                    color: black !important;
                }
                .sc-value, .sc-label, .num-cell, .pension-table td, .pension-table th {
                    color: black !important;
                }
                .summary-card {
                    background: #f8fafc !important;
                    border: 1px solid #e2e8f0 !important;
                }
                .sc-highlight {
                    -webkit-text-fill-color: #0369a1 !important;
                    color: #0369a1 !important;
                }
                .total-row td, .total-cell {
                    color: #0369a1 !important;
                    -webkit-text-fill-color: #0369a1 !important;
                }
                .neg { color: #dc2626 !important; }
                /* Hide the save-as-PDF iframe */
                iframe { display: none !important; }
            }
            </style>
            """, unsafe_allow_html=True)

            # ── Save as PDF button (uses components.html for JS) ──
            st.markdown("---")
            import streamlit.components.v1 as components
            components.html("""
            <div style="text-align:center;padding:8px;">
                <button onclick="window.parent.print()"
                    style="padding:12px 28px;font-family:'Heebo',sans-serif;font-size:1rem;font-weight:600;
                    color:#475569;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:8px;cursor:pointer;
                    direction:rtl;">
                    🖨️ שמור כ-PDF
                </button>
                <div style="font-size:0.75rem;color:#94a3b8;margin-top:6px;direction:rtl;font-family:'Alef',sans-serif;">
                    בחלון שייפתח בחר "שמור כ-PDF" כיעד ההדפסה
                </div>
            </div>
            """, height=80)

# Version marker for debugging
st.markdown('<div style="text-align:center;color:#94a3b8;font-size:0.8rem;margin-top:40px;direction:rtl;line-height:1.8;">⚠️ הניתוח מבוסס על בינה מלאכותית ועלולות ליפול בו טעויות. אין להסתמך עליו כייעוץ פנסיוני.</div>', unsafe_allow_html=True)
st.markdown('<div style="text-align:center;color:#4a5568;font-size:0.75rem;margin-top:8px;">גירסת בטא</div>', unsafe_allow_html=True)
