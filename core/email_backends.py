"""
Email backend for the Brevo (Sendinblue) transactional HTTP API.

Many free hosts (including Render's free tier) block outgoing SMTP ports, so
sending over HTTPS is the reliable option. Brevo's free plan allows 300
emails/day and only needs a verified sender address — no custom domain.
"""

import logging
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"


def _address(value):
    name, email = parseaddr(value)
    return {"email": email, "name": name} if name else {"email": email}


class BrevoEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            try:
                self._send(message)
                sent += 1
            except Exception:
                logger.exception("Brevo email to %s failed", message.to)
                if not self.fail_silently:
                    raise
        return sent

    def _send(self, message):
        payload = {
            "sender": _address(message.from_email or settings.DEFAULT_FROM_EMAIL),
            "to": [_address(addr) for addr in message.to],
            "subject": message.subject,
            "textContent": message.body,
        }
        if message.reply_to:
            payload["replyTo"] = _address(message.reply_to[0])
        for content, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html":
                payload["htmlContent"] = content
        response = requests.post(
            BREVO_ENDPOINT,
            json=payload,
            headers={"api-key": settings.BREVO_API_KEY, "accept": "application/json"},
            timeout=settings.EMAIL_TIMEOUT,
        )
        response.raise_for_status()
