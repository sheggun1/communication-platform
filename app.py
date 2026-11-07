import os
import re
import csv
import io
import json
import uuid
from datetime import datetime
from functools import wraps

import pandas as pd
import psycopg
from psycopg.rows import dict_row
import requests
from docx import Document
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-only-change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
DB_PATH = os.path.join(app.instance_path, "communications.sqlite3")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ALLOWED_EXTENSIONS = {"csv", "xlsx", "xls", "docx"}
os.makedirs(app.instance_path, exist_ok=True)

def db():
    """Use Neon PostgreSQL when DATABASE_URL is set; otherwise use local SQLite."""
    if DATABASE_URL:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def sql(query):
    """Translate parameter placeholders for PostgreSQL while retaining local SQLite support."""
    return query.replace("?", "%s") if DATABASE_URL else query

def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY, name TEXT, channel TEXT, status TEXT,
            total INTEGER, sent INTEGER, failed INTEGER, created_at TEXT,
            details TEXT
        )""")
init_db()

def logged_in():
    return session.get("authenticated") is True

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not logged_in():
            if request.path.startswith("/api/"):
                return jsonify(error="Please log in again."), 401
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def clean_value(value):
    if pd.isna(value):
        return ""
    return str(value).strip()

def read_contacts(file_storage):
    filename = secure_filename(file_storage.filename or "")
    ext = filename.rsplit(".", 1)[-1].lower()
    raw = file_storage.read()
    if ext == "csv":
        frame = pd.read_csv(io.BytesIO(raw), dtype=str).fillna("")
    elif ext in ("xlsx", "xls"):
        frame = pd.read_excel(io.BytesIO(raw), dtype=str).fillna("")
    elif ext == "docx":
        doc = Document(io.BytesIO(raw))
        if not doc.tables:
            raise ValueError("The Word document must contain a table with a header row.")
        table = doc.tables[0]
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if len(rows) < 2:
            raise ValueError("The Word table needs a header row and at least one contact.")
        frame = pd.DataFrame(rows[1:], columns=rows[0]).fillna("")
    else:
        raise ValueError("Upload a CSV, Excel (.xlsx/.xls), or Word (.docx) file.")
    frame.columns = [str(c).strip() for c in frame.columns]
    frame = frame.loc[:, [c for c in frame.columns if c and not c.lower().startswith("unnamed")]]
    if frame.empty or len(frame.columns) == 0:
        raise ValueError("No contact rows or columns were found.")
    contacts = []
    for _, row in frame.head(500).iterrows():
        item = {str(k): clean_value(v) for k, v in row.to_dict().items()}
        if any(item.values()):
            contacts.append(item)
    if not contacts:
        raise ValueError("No usable contact records were found.")
    return contacts, list(frame.columns), len(frame)

def render_message(template, contact):
    def replace(match):
        key = match.group(1).strip()
        for column, value in contact.items():
            if column.lower() == key.lower():
                return value
        return match.group(0)
    return re.sub(r"{{\s*([^{}]+?)\s*}}", replace, template)

def send_email(contact, message, subject):
    api_key = os.getenv("BREVO_API_KEY")
    sender = os.getenv("BREVO_SENDER_EMAIL")
    recipient = contact.get("email") or contact.get("Email") or contact.get("EMAIL")
    if not api_key or not sender:
        raise ValueError("Email is not configured. Add BREVO_API_KEY and BREVO_SENDER_EMAIL.")
    if not recipient:
        raise ValueError("Recipient email address is missing.")
    payload = {
        "sender": {"name": os.getenv("BREVO_SENDER_NAME", "Communication Platform"), "email": sender},
        "to": [{"email": recipient}],
        "subject": subject or "Message",
        "textContent": message
    }
    r = requests.post("https://api.brevo.com/v3/smtp/email",
        headers={"api-key": api_key, "Content-Type": "application/json"},
        json=payload, timeout=25)
    if not r.ok:
        raise ValueError(f"Email provider error: {r.text[:250]}")
    return "Email accepted"

def send_whatsapp(contact, message):
    token = os.getenv("META_WHATSAPP_TOKEN")
    phone_id = os.getenv("META_WHATSAPP_PHONE_NUMBER_ID")
    recipient = contact.get("phone") or contact.get("Phone") or contact.get("PHONE") or contact.get("whatsapp")
    if not token or not phone_id:
        raise ValueError("WhatsApp is not configured. Add your Meta Cloud API credentials.")
    if not recipient:
        raise ValueError("Recipient phone number is missing.")
    recipient = re.sub(r"\D", "", recipient)
    payload = {"messaging_product": "whatsapp", "to": recipient,
        "type": "text", "text": {"preview_url": False, "body": message}}
    r = requests.post(f"https://graph.facebook.com/v23.0/{phone_id}/messages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload, timeout=25)
    if not r.ok:
        raise ValueError(f"WhatsApp provider error: {r.text[:250]}")
    return "WhatsApp accepted"

def send_sms(contact, message):
    key = os.getenv("TERMII_API_KEY")
    sender = os.getenv("TERMII_SENDER_ID", "Notify")
    recipient = contact.get("phone") or contact.get("Phone") or contact.get("PHONE") or contact.get("mobile")
    if not key:
        raise ValueError("SMS is not configured. Add TERMII_API_KEY.")
    if not recipient:
        raise ValueError("Recipient phone number is missing.")
    recipient = re.sub(r"\D", "", recipient)
    if recipient.startswith("0") and len(recipient) == 11:
        recipient = "234" + recipient[1:]
    payload = {"to": recipient, "from": sender, "sms": message,
        "type": "plain", "channel": "generic", "api_key": key}
    r = requests.post("https://api.ng.termii.com/api/sms/send", json=payload, timeout=25)
    if not r.ok:
        raise ValueError(f"SMS provider error: {r.text[:250]}")
    return "SMS accepted"

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = os.getenv("ADMIN_PASSWORD", "")
        supplied = request.form.get("password", "")
        if password and supplied == password:
            session["authenticated"] = True
            return redirect(url_for("index"))
        flash("Login failed. Check the admin password configured by the owner.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    with db() as conn:
        campaigns = conn.execute("SELECT * FROM campaigns ORDER BY created_at DESC LIMIT 20").fetchall()
    configured = {
        "email": bool(os.getenv("BREVO_API_KEY") and os.getenv("BREVO_SENDER_EMAIL")),
        "whatsapp": bool(os.getenv("META_WHATSAPP_TOKEN") and os.getenv("META_WHATSAPP_PHONE_NUMBER_ID")),
        "sms": bool(os.getenv("TERMII_API_KEY"))
    }
    return render_template("index.html", campaigns=campaigns, configured=configured)

@app.route("/api/preview", methods=["POST"])
@login_required
def preview():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify(error="Choose a contact file first."), 400
    if not allowed_file(upload.filename):
        return jsonify(error="Supported files: CSV, XLSX, XLS and DOCX."), 400
    try:
        contacts, columns, original_count = read_contacts(upload)
        return jsonify(contacts=contacts, columns=columns, count=len(contacts),
                       original_count=original_count, sample=contacts[:5])
    except Exception as exc:
        return jsonify(error=str(exc)), 400

@app.route("/api/send", methods=["POST"])
@login_required
def send_campaign():
    data = request.get_json(silent=True) or {}
    contacts = data.get("contacts") or []
    channel = data.get("channel", "").lower()
    mode = data.get("mode", "same")
    message = (data.get("message") or "").strip()
    subject = (data.get("subject") or "").strip()
    name = (data.get("name") or "Untitled campaign").strip()[:120]
    if not contacts or len(contacts) > 500:
        return jsonify(error="Upload between 1 and 500 contacts."), 400
    if channel not in ("email", "whatsapp", "sms"):
        return jsonify(error="Choose Email, WhatsApp or SMS."), 400
    if mode not in ("same", "personalised", "individual"):
        return jsonify(error="Invalid message mode."), 400
    if mode != "individual" and not message:
        return jsonify(error="Enter a message before sending."), 400
    if mode == "individual" and any(not str(c.get("_message", "")).strip() for c in contacts):
        return jsonify(error="Every contact needs an individual message."), 400
    campaign_id = str(uuid.uuid4())[:8]
    sent, failed, results = 0, 0, []
    with db() as conn:
        conn.execute(sql("INSERT INTO campaigns VALUES (?,?,?,?,?,?,?,?,?)"),
            (campaign_id, name, channel, "sending", len(contacts), 0, 0,
             datetime.utcnow().isoformat(timespec="seconds"), "[]"))
    for index, contact in enumerate(contacts):
        text = str(contact.get("_message", "")) if mode == "individual" else render_message(message, contact)
        try:
            if channel == "email":
                outcome = send_email(contact, text, subject)
            elif channel == "whatsapp":
                outcome = send_whatsapp(contact, text)
            else:
                outcome = send_sms(contact, text)
            sent += 1
            results.append({"recipient": contact.get("name") or contact.get("Name") or contact.get("email") or contact.get("phone") or f"Contact {index+1}", "status": "Accepted", "detail": outcome})
        except Exception as exc:
            failed += 1
            results.append({"recipient": contact.get("name") or contact.get("Name") or contact.get("email") or contact.get("phone") or f"Contact {index+1}", "status": "Failed", "detail": str(exc)[:250]})
        with db() as conn:
            conn.execute(sql("UPDATE campaigns SET sent=?, failed=?, status=?, details=? WHERE id=?"),
                (sent, failed, "completed" if index == len(contacts)-1 else "sending",
                 json.dumps(results), campaign_id))
    return jsonify(id=campaign_id, sent=sent, failed=failed, total=len(contacts), results=results)

@app.route("/api/campaigns")
@login_required
def campaign_list():
    with db() as conn:
        rows = conn.execute("SELECT * FROM campaigns ORDER BY created_at DESC LIMIT 100").fetchall()
    return jsonify(campaigns=[dict(r) for r in rows])

@app.route("/api/health")
def health():
    return jsonify(status="ok", application="Communication Platform")

@app.errorhandler(413)
def too_large(_):
    return jsonify(error="File is too large. Maximum upload size is 10MB."), 413

if __name__ == "__main__":
    app.run(debug=True)
