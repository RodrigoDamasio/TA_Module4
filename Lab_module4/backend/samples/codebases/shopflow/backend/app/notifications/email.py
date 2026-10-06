"""Order confirmation emails."""

import smtplib
from email.message import EmailMessage

from ..config import get_settings


def send_order_confirmation(to: str, order) -> None:
    """Send a plain-text confirmation through the SMTP server from SMTP_HOST / SMTP_PORT.
    Failures are swallowed: an order is never rolled back because an email failed."""
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to
    message["Subject"] = f"Your Shopflow order #{order.id}"
    message.set_content(f"Thanks! Order #{order.id} is paid. Total: {order.total} USD.")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.send_message(message)
    except OSError:
        pass
