"""Dispatch encrypted authentication mail: python -m app.auth_mail.

Run periodically with the same AUTH_DELIVERY_KEY as the API. SMTP always uses STARTTLS.
Tokens are never printed or retained after successful dispatch.
"""

import json
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlencode

from sqlalchemy import select

from app.auth_routes import delivery_cipher
from app.config import get_settings
from app.db import SessionLocal
from app.models import AuthChallenge, AuthDelivery, utcnow


def dispatch():
    settings, cipher = get_settings(), delivery_cipher()
    with SessionLocal() as db:
        for _ in range(100):
            row = db.scalar(
                select(AuthDelivery)
                .where(
                    AuthDelivery.sent_at.is_(None),
                    AuthDelivery.encrypted_payload.is_not(None),
                    AuthDelivery.attempts < 5,
                )
                .order_by(AuthDelivery.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                break
            challenge = db.get(AuthChallenge, row.challenge_id)
            if challenge.consumed_at or challenge.expires_at <= utcnow():
                row.encrypted_payload = None
                db.commit()
                continue
            row.attempts += 1
            payload = json.loads(cipher.decrypt(row.encrypted_payload.encode()))
            message = EmailMessage()
            message["From"], message["To"] = settings.smtp_from, payload["email"]
            message["Subject"] = "PamatiAI account instructions"
            link = settings.auth_public_url.rstrip("/") + "/auth/" + payload["purpose"]
            # Fragment avoids sending the secret to web servers and referer logs.
            message.set_content(
                "Use this expiring, single-use link: "
                + link
                + "#"
                + urlencode({"token": payload["token"]})
            )
            try:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                    smtp.starttls(context=ssl.create_default_context())
                    if settings.smtp_username:
                        smtp.login(settings.smtp_username, settings.smtp_password)
                    smtp.send_message(message)
            except (OSError, smtplib.SMTPException):
                db.commit()  # No server error text or email contents in logs.
                continue
            row.sent_at, row.encrypted_payload = utcnow(), None
            db.commit()


if __name__ == "__main__":
    dispatch()
