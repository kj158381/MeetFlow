"""
utils/helpers.py
Shared utility functions: email building, SMTP sending, email templates.
"""
import smtplib, logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logger = logging.getLogger(__name__)

AVATAR_COLORS = [
    "#5b6af0", "#8b5cf6", "#059669", "#dc2626",
    "#d97706", "#0891b2", "#be185d", "#0d9488",
]

def pick_avatar_color(name: str) -> str:
    return AVATAR_COLORS[len(name) % len(AVATAR_COLORS)]

# ── Email HTML template ───────────────────────────────────────────────────────

def email_html_template(title: str, greeting: str, body_html: str,
                        cta_url: str = "", cta_text: str = "", footer: str = "") -> str:
    """
    Returns a clean, spam-filter-friendly HTML email.
    Uses only inline CSS — works in Gmail, Outlook, Yahoo, Apple Mail, Google Workspace.
    """
    cta_block = ""
    if cta_url and cta_text:
        cta_block = f"""
        <tr><td style="padding:8px 0 24px 0;text-align:center;">
          <a href="{cta_url}" target="_blank"
             style="display:inline-block;background:#5b6af0;color:#ffffff;font-family:Arial,sans-serif;
                    font-size:16px;font-weight:700;text-decoration:none;padding:14px 32px;
                    border-radius:8px;text-align:center;">
            {cta_text}
          </a>
        </td></tr>"""

    footer_text = footer or datetime.now().strftime("%B %d, %Y")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background-color:#f0f4ff;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f0f4ff;padding:24px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" border="0"
             style="background:#ffffff;border-radius:16px;overflow:hidden;
                    box-shadow:0 4px 24px rgba(91,106,240,0.10);max-width:560px;">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#5b6af0 0%,#8b5cf6 100%);
                     padding:32px 40px;text-align:center;">
            <p style="margin:0 0 4px 0;font-size:12px;color:rgba(255,255,255,0.75);
                      font-family:Arial,sans-serif;letter-spacing:2px;text-transform:uppercase;">
              Meeting Automation
            </p>
            <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;
                       font-family:Arial,sans-serif;line-height:1.3;">
              {title}
            </h1>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:32px 40px 8px 40px;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr><td style="padding-bottom:16px;">
                <p style="margin:0;color:#374151;font-size:16px;font-family:Arial,sans-serif;
                          font-weight:600;line-height:1.5;">{greeting}</p>
              </td></tr>
              <tr><td style="color:#4b5563;font-size:15px;font-family:Arial,sans-serif;
                             line-height:1.7;padding-bottom:8px;">{body_html}</td></tr>
              {cta_block}
            </table>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f8faff;border-top:1px solid #e5e7eb;
                     padding:20px 40px;text-align:center;">
            <p style="margin:0;color:#9ca3af;font-size:12px;font-family:Arial,sans-serif;">
              Meeting Automation &nbsp;•&nbsp; {footer_text}
            </p>
            <p style="margin:6px 0 0 0;color:#d1d5db;font-size:11px;font-family:Arial,sans-serif;">
              You received this email because someone used Meeting Automation to contact you.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

# ── SMTP helpers ──────────────────────────────────────────────────────────────

def _build_mime_message(smtp_user: str, to_email: str, subject: str,
                        html_body: str, text_body: str = "", reply_to: str = ""):
    msg = MIMEMultipart("alternative")
    msg["Subject"]  = subject
    msg["From"]     = f"Meeting Automation <{smtp_user}>"
    msg["To"]       = to_email
    msg["X-Mailer"] = "MeetingAutomation/3.0"
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(text_body or "Please view this email in an HTML-capable email client.", "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def send_gmail_smtp(smtp_user: str, smtp_pass: str, to_email: str,
                    subject: str, html_body: str, text_body: str = "", reply_to: str = ""):
    """
    Send via Gmail SMTP.
    smtp_pass must be a 16-character App Password (spaces allowed — stripped internally).
    Tries STARTTLS:587 first, falls back to SSL:465.
    """
    import ssl as ssl_mod
    smtp_pass_clean = smtp_pass.replace(" ", "").strip()

    if not smtp_user or not smtp_pass_clean:
        raise ValueError("Gmail address and App Password are required.")
    if len(smtp_pass_clean) != 16:
        raise smtplib.SMTPAuthenticationError(
            535,
            b"App Password must be exactly 16 characters. "
            b"Get it: myaccount.google.com -> Security -> App passwords"
        )

    msg = _build_mime_message(smtp_user, to_email, subject, html_body, text_body, reply_to or smtp_user)
    last_error = None

    # Strategy 1: STARTTLS port 587
    try:
        ctx = ssl_mod.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=25) as srv:
            srv.ehlo("meetingauto")
            srv.starttls(context=ctx)
            srv.ehlo("meetingauto")
            srv.login(smtp_user, smtp_pass_clean)
            srv.sendmail(smtp_user, [to_email], msg.as_string())
            logger.info(f"✅ Email sent via STARTTLS:587 → {to_email}")
            return
    except smtplib.SMTPAuthenticationError as e:
        raise smtplib.SMTPAuthenticationError(
            e.smtp_code,
            ("❌ Gmail auth failed. Use a 16-char App Password from "
             "myaccount.google.com → Security → App passwords").encode()
        )
    except smtplib.SMTPRecipientsRefused as e:
        raise ValueError(f"Recipient rejected: {to_email} — {e}")
    except Exception as e:
        last_error = e
        logger.warning(f"STARTTLS:587 failed ({type(e).__name__}), trying SSL:465…")

    # Strategy 2: SSL port 465
    try:
        ctx = ssl_mod.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=25) as srv:
            srv.ehlo("meetingauto")
            srv.login(smtp_user, smtp_pass_clean)
            srv.sendmail(smtp_user, [to_email], msg.as_string())
            logger.info(f"✅ Email sent via SSL:465 → {to_email}")
            return
    except smtplib.SMTPAuthenticationError as e:
        raise smtplib.SMTPAuthenticationError(
            e.smtp_code,
            b"Gmail auth failed on SSL:465. Use a 16-char App Password."
        )
    except Exception as e:
        last_error = e

    raise ConnectionError(
        f"Could not connect to Gmail SMTP. Both ports 587 and 465 failed.\n"
        f"Last error: {last_error}"
    )


def send_to_multiple(smtp_user: str, smtp_pass: str, recipients: list,
                     subject: str, html_body: str, text_body: str = "") -> dict:
    """Send individual emails to multiple recipients. Returns {email: 'sent'|'failed', ...}."""
    results = {}
    for email in recipients:
        email = email.strip()
        if not email or "@" not in email:
            results[email] = "skipped (invalid)"
            continue
        try:
            send_gmail_smtp(smtp_user, smtp_pass, email, subject, html_body, text_body)
            results[email] = "sent"
        except Exception as e:
            results[email] = f"failed: {str(e)[:100]}"
            logger.warning(f"Failed to send to {email}: {e}")
    return results
