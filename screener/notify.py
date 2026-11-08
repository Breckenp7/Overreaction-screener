"""Sends results to your phone. Credentials come from environment variables
(GitHub "Secrets"), never from files in the repo.

  NTFY_TOPIC          -> push notification via ntfy.sh (free app, no account)
  EMAIL_USER          -> e.g. yourname@gmail.com (sender)
  EMAIL_APP_PASSWORD  -> a Gmail "App Password" (NOT your normal password)
  EMAIL_TO            -> where to send (can be the same address)
  SMTP_HOST / SMTP_PORT (optional; default smtp.gmail.com / 465)
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests


def _ascii(s):
    return s.encode("ascii", "ignore").decode()


def send_push(title, body, click_url=None, priority="default", tags="chart_with_downwards_trend", log=print):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        log("Push skipped: NTFY_TOPIC not set.")
        return False
    headers = {"Title": _ascii(title), "Priority": priority, "Tags": tags}
    if click_url:
        headers["Click"] = click_url
    try:
        r = requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), headers=headers, timeout=20)
        r.raise_for_status()
        log("Push sent.")
        return True
    except Exception as e:
        log(f"Push FAILED: {type(e).__name__}: {e}")
        return False


def send_email(subject, html, text, log=print):
    user = os.environ.get("EMAIL_USER", "").strip()
    pw = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    to = os.environ.get("EMAIL_TO", "").strip() or user
    if not (user and pw and to):
        log("Email skipped: EMAIL_USER / EMAIL_APP_PASSWORD / EMAIL_TO not all set.")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    try:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, pw)
            s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
        log("Email sent.")
        return True
    except Exception as e:
        log(f"Email FAILED: {type(e).__name__}: {e}")
        return False
