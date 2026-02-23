def step1_read_report_v2(pdf_bytes: bytes) -> str | None:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = ""
    
    for page in doc:
        # חילוץ טקסט עם שמירה על מיקומים (blocks)
        # זה עוזר ל-AI להבין מה נמצא ליד מה
        blocks = page.get_text("blocks")
        for b in blocks:
            full_text += f"{b[4]}\n" # b[4] הוא הטקסט עצמו
    
    prompt = f"""אתה מנתח דוחות פנסיה. לפניך טקסט שחולץ מ-PDF. 
המשימה שלך היא לארגן את הנתונים בטבלאות JSON מדויקות.

הטקסט הגולמי:
{full_text}

חוקים:
1. בטבלה ב' (תנועות): ודא שאתה כולל את שורת "הפסדים/רווחים" ואת כל רכיבי הביטוח (נכות ומוות).
2. בטבלה ה' (הפקדות): שים לב שכל שורה מכילה: מועד הפקדה, חודש שכר, משכורת, עובד, מעסיק, פיצויים וסה"כ. 
3. אל תעגל מספרים.
4. אם יש סימן מינוס (-), שמור עליו."""

    # כאן שולחים רק טקסט ל-Model (זה גם הרבה יותר זול ומהיר!)
    response = client.chat.completions.create(
        model="gpt-4o", # אפשר אפילו gpt-4o-mini כי הטקסט כבר אצלנו
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return response.choices[0].message.content
