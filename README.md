# Communication Platform

A mobile-friendly bulk communication dashboard built with Python Flask. It imports contact lists from CSV, Excel and Word tables, previews the contacts, and supports shared, personalised and individual messages through email, WhatsApp and SMS providers.

## Features
- CSV, XLSX, XLS and DOCX contact import (up to 500 contacts per campaign; 10MB upload limit).
- Shared messages, personalised placeholders such as `{{name}}`, and per-contact messages.
- Email through Brevo, WhatsApp through Meta WhatsApp Cloud API, SMS through Termii.
- Campaign history stored in SQLite.
- Admin password login and responsive mobile layout.

## Run locally
1. Install Python 3.11 or newer.
2. Run `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and set a strong `SECRET_KEY` and `ADMIN_PASSWORD`.
4. Run `python app.py`.
5. Open `http://127.0.0.1:5000`.

## Deploy on Render
Create a **Web Service** connected to this GitHub repository.
- Runtime: Python 3
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

Add environment variables in Render. Never put real API keys in GitHub:
- `SECRET_KEY` (long random secret)
- `ADMIN_PASSWORD` (strong admin password)
- `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, optional `BREVO_SENDER_NAME`
- `META_WHATSAPP_TOKEN`, `META_WHATSAPP_PHONE_NUMBER_ID`
- `TERMII_API_KEY`, optional `TERMII_SENDER_ID`

Set a persistent disk on Render and mount it at the path used for the SQLite database if you need campaign history to survive redeploys/restarts. For a multi-user or high-volume production system, move to managed PostgreSQL and a background job queue.

## Contact file format
Use a header row. Recommended columns:
- `name`
- `email`
- `phone`

For personalised messages, reference any column by its header, for example:
`Hello {{name}}, your appointment is {{appointment_date}}.`

Word import expects a DOCX document containing a table. The first row is the column header.

## Important sending notes
- Configure and verify sender identities with your providers before sending.
- Meta WhatsApp rules may require an approved template for business-initiated messages outside the customer service window. The current starter sends text messages only.
- Respect consent, provider policies, opt-outs and applicable privacy/data-protection laws. Do not use this tool for unsolicited bulk messaging.
- “Accepted” means the provider accepted the request; it does not guarantee delivery to the recipient. Add provider webhooks for delivery receipts.
- Sending is currently sequential and request-based. For large campaigns, add a durable queue, retries, rate limits and delivery webhooks before production use.
