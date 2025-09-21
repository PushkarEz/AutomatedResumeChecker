# app.py
"""
Resume Skill Matcher + Email Feedback (keyword-only version).
Auto-detects email in uploaded resumes and allows sending polite feedback.
"""

import streamlit as st
import pandas as pd
import io
import os
import re
import tempfile
import smtplib
import ssl
from email.mime.text import MIMEText

# --- optional backends (import inside try/except to avoid crashes) ---
PDF_BACKEND = None
DOCX_BACKEND = None

try:
    import pdfplumber
    PDF_BACKEND = "pdfplumber"
except Exception:
    try:
        import PyPDF2
        from PyPDF2 import PdfReader
        PDF_BACKEND = "pypdf2"
    except Exception:
        PDF_BACKEND = None

try:
    from docx import Document as DocxDocument
    DOCX_BACKEND = "python-docx"
except Exception:
    try:
        import docx2txt
        DOCX_BACKEND = "docx2txt"
    except Exception:
        DOCX_BACKEND = None

# ---------------------------
# Utility functions
# ---------------------------
def extract_text_from_pdf_bytes(file_bytes):
    if not PDF_BACKEND:
        return None, "no_pdf_backend"
    try:
        if PDF_BACKEND == "pdfplumber":
            text = ""
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                for p in pdf.pages:
                    text += p.extract_text() or ""
            return text, None
        elif PDF_BACKEND == "pypdf2":
            reader = PdfReader(io.BytesIO(file_bytes))
            text = ""
            for p in reader.pages:
                try:
                    t = p.extract_text() or ""
                except:
                    try:
                        t = p.get_text() or ""
                    except:
                        t = ""
                text += t
            return text, None
    except Exception as e:
        return None, str(e)
    return None, "unsupported_pdf_backend"

def extract_text_from_docx_bytes(file_bytes):
    if not DOCX_BACKEND:
        return None, "no_docx_backend"
    try:
        if DOCX_BACKEND == "python-docx":
            doc = DocxDocument(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return text, None
        elif DOCX_BACKEND == "docx2txt":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                txt = docx2txt.process(tmp_path)
            finally:
                try:
                    os.remove(tmp_path)
                except:
                    pass
            return txt, None
    except Exception as e:
        return None, str(e)
    return None, "unsupported_docx_backend"

def clean_text(text):
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r'\s+', ' ', t)
    t = re.sub(r'[^a-z0-9\s@._+-]', ' ', t)  # keep @ . _ + - for email extraction
    return t.strip()

EMAIL_REGEX = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"

def extract_email_from_text(text):
    """Return first email found or None."""
    if not text:
        return None
    m = re.findall(EMAIL_REGEX, text)
    return m[0].strip() if m else None

def classify_verdict(score):
    if score >= 75:
        return "High"
    elif score >= 50:
        return "Medium"
    else:
        return "Low"

def generate_feedback_text(row):
    """Return a polite feedback email body given one result row (dict)."""
    name_line = ""
    # we can't reliably get name; keep it generic and respectful
    lines = []
    lines.append("Hello,")
    lines.append("")
    lines.append(f"We reviewed the resume you submitted. Here is the summary:")
    lines.append(f"- Relevance Score: {row['score']} ({row['verdict']})")
    lines.append(f"- Matched skills: {row['matched_must'] if row['matched_must']!='-' else row['matched_good']}")
    lines.append(f"- Missing must-have skills: {row['missing_must'] if row['missing_must']!='-' else 'None'}")
    lines.append("")
    lines.append("Suggested next steps to improve your candidacy:")
    if row['missing_must'] != "-" and row['missing_must'].strip():
        for s in row['missing_must'].split(","):
            s = s.strip()
            if not s:
                continue
            lines.append(f"- Add a short project or one-line demo that shows {s} (e.g., GitHub repo link).")
            lines.append(f"- Consider a short online course/certificate in {s} and include it in your resume.")
    else:
        lines.append("- Your resume already contains the required must-have skills. Keep your experience and projects clear and concise.")
    lines.append("")
    lines.append("If you'd like, you can share an updated resume and we'll re-evaluate it.")
    lines.append("")
    lines.append("Best regards,")
    lines.append("Placement Team")
    return "\n".join(lines)

def send_email_smtp(receiver, subject, body):
    """
    Sends email using SMTP creds from environment:
    SMTP_USER, SMTP_PASSWORD, SMTP_SERVER (optional), SMTP_PORT(optional)
    Returns (True, "Sent") or (False, "error message")
    """
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", os.getenv("SMTP_PORT", 465)))

    if not smtp_user or not smtp_pass:
        return False, "SMTP_USER and SMTP_PASSWORD environment variables are not set."

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = receiver

    try:
        if smtp_port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, receiver, msg.as_string())
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, receiver, msg.as_string())
        return True, "Sent"
    except Exception as e:
        return False, str(e)

# ---------------------------
# Streamlit UI
# ---------------------------
st.set_page_config(page_title="Resume Skill Matcher + Email Feedback", layout="wide", page_icon="📨")
st.title("📨 Automated Resume Relevance Check System")

st.sidebar.header("Job Description (JD) & Skills")
default_jd = ("We are hiring a Python developer. Must: Python, Linux, Networking. "
              "Good to have: Docker, Cloud, Security.")
jd_text = st.sidebar.text_area("Paste Job Description (JD) here", value=default_jd, height=180)

must_input = st.sidebar.text_input("Must-have skills (comma separated)", "Python, Linux, Networking")
good_input = st.sidebar.text_input("Good-to-have skills (comma separated)", "Docker, Cloud, Vulnerability Assessment")

must_skills = [s.strip().lower() for s in must_input.split(",") if s.strip()]
good_skills = [s.strip().lower() for s in good_input.split(",") if s.strip()]

st.markdown("**Available backends**:")
st.markdown(f"- PDF backend: `{PDF_BACKEND or 'none'}`")
st.markdown(f"- DOCX backend: `{DOCX_BACKEND or 'none'}`")

st.header("Upload resumes (PDF or DOCX) — batch supported")
uploaded_files = st.file_uploader("Upload resumes", type=["pdf", "docx"], accept_multiple_files=True)

results = []
errors = []

if uploaded_files:
    for up in uploaded_files:
        try:
            bytes_data = up.read()
        except Exception as e:
            errors.append((up.name, f"Could not read uploaded file: {e}"))
            continue

        lower_name = up.name.lower()
        text = ""
        extraction_error = None

        if lower_name.endswith(".pdf"):
            text, extraction_error = extract_text_from_pdf_bytes(bytes_data)
        elif lower_name.endswith(".docx"):
            text, extraction_error = extract_text_from_docx_bytes(bytes_data)
        else:
            extraction_error = "unsupported file type"

        if extraction_error:
            errors.append((up.name, extraction_error))
            results.append({
                "filename": up.name,
                "score": 0.0,
                "verdict": "Low",
                "matched_must": "-",
                "matched_good": "-",
                "missing_must": ", ".join(must_skills) if must_skills else "-",
                "email": "-",
                "error": extraction_error
            })
            continue

        # extract email BEFORE cleaning (to preserve @ and dots)
        detected_email = extract_email_from_text(text)

        text_clean = clean_text(text)

        matched_must = [s for s in must_skills if s in text_clean]
        matched_good = [s for s in good_skills if s in text_clean]
        missing_must = [s for s in must_skills if s not in matched_must]

        hard_score = (len(matched_must) / max(1, len(must_skills))) * 100 if must_skills else 100
        final_score = round(hard_score, 2)

        results.append({
            "filename": up.name,
            "score": final_score,
            "verdict": classify_verdict(final_score),
            "matched_must": ", ".join(matched_must) if matched_must else "-",
            "matched_good": ", ".join(matched_good) if matched_good else "-",
            "missing_must": ", ".join(missing_must) if missing_must else "-",
            "email": detected_email or "-",
            "error": ""
        })

# show errors
if errors:
    st.error("Some files had issues:")
    for n, e in errors:
        st.write(f"- **{n}**: {e}")

# Display results
if results:
    df = pd.DataFrame(results).sort_values("score", ascending=False).reset_index(drop=True)
    display_df = df[["filename", "score", "verdict", "matched_must", "matched_good", "missing_must", "email"]]
    st.subheader("Shortlist")
    st.dataframe(display_df, use_container_width=True)

    csv = display_df.to_csv(index=False).encode("utf-8")
    st.download_button("Export shortlist CSV", data=csv, file_name="shortlist.csv", mime="text/csv")

    # Drilldown + sending feedback
    st.subheader("Resume Drilldown & Feedback")
    sel = st.selectbox("Select resume to preview feedback", [r["filename"] for r in results])
    row = next(r for r in results if r["filename"] == sel)

    st.markdown(f"**Score:** {row['score']}  |  **Verdict:** {row['verdict']}")
    st.markdown(f"**Detected email:** {row['email']}")
    st.markdown(f"**Matched must-have:** {row['matched_must']}")
    st.markdown(f"**Missing must-have:** {row['missing_must']}")

    feedback_body = generate_feedback_text(row)
    st.subheader("Preview feedback email")
    st.text_area("Email body (editable)", value=feedback_body, height=240, key="feedback_preview")

    # Send button
    st.markdown("**Send feedback**")
    info = "To send real emails, set SMTP credentials in environment variables: SMTP_USER, SMTP_PASSWORD (and optionally SMTP_SERVER, SMTP_PORT)."
    st.caption(info)

    if row["email"] == "-" or not row["email"]:
        st.warning("No email detected in this resume. You can copy the feedback and send manually.")
    else:
        if st.button("Send feedback to detected email"):
            # read the possibly edited content from the text_area
            body_to_send = st.session_state.get("feedback_preview", feedback_body)
            subject = f"Feedback on your resume — Score {row['score']}"
            ok, msg = send_email_smtp(row["email"], subject, body_to_send)
            if ok:
                st.success(f"Feedback sent to {row['email']}")
            else:
                st.error(f"Failed to send email: {msg}")
                st.info("You can copy the email body below and send manually if SMTP not configured.")
                st.code(body_to_send)

    # Optional: mass send to all detected emails (use with caution)
    st.markdown("---")
    if st.checkbox("Enable: Send feedback to ALL detected emails (use with caution)"):
        if st.button("Send to ALL detected"):
            sent = 0
            errors_out = []
            for r in results:
                if r.get("email") and r["email"] != "-":
                    body = generate_feedback_text(r)
                    ok, msg = send_email_smtp(r["email"], f"Feedback on your resume — Score {r['score']}", body)
                    if ok:
                        sent += 1
                    else:
                        errors_out.append((r["email"], msg))
            st.success(f"Emails sent: {sent}")
            if errors_out:
                st.error("Some sends failed:")
                for e in errors_out:
                    st.write(f"- {e[0]}: {e[1]}")

else:
    st.info("Upload resumes to see results. (Detected email shown in table; click a resume to preview feedback.)")

# small help text
st.markdown("---")
st.markdown("**Notes:**")
st.markdown("- SMTP credentials must be set as environment variables for automatic sending (SMTP_USER, SMTP_PASSWORD).")
st.markdown("- For Gmail, create an App Password (Google Account → Security → App passwords) and use it as SMTP_PASSWORD.")
st.markdown("- If SMTP is not configured, the app shows the email body so you can copy/paste and send manually.")
