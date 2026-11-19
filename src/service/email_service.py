import asyncio
import logging
import smtplib
from email.message import EmailMessage

from src.settings import settings


logger = logging.getLogger(__name__)


def _send_message(message: EmailMessage) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        raise RuntimeError("SMTP email delivery is not configured.")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.ehlo()
        if settings.smtp_use_tls:
            smtp.starttls()
            smtp.ehlo()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(message)


async def send_email_action_link(
    *,
    recipient: str,
    action: str,
    link: str,
) -> bool:
    """Send an account email action without exposing provider errors to callers."""
    subject, instruction = {
        "verify": (
            "Verifica tu correo de Manea",
            "Confirma tu dirección de correo abriendo este enlace:",
        ),
        "activate": (
            "Activa tu cuenta de Manea",
            "Para activar tu cuenta y elegir tu contraseña, abre este enlace:",
        ),
        "reset": (
            "Recupera tu contraseña de Manea",
            "Para elegir una contraseña nueva, abre este enlace:",
        ),
    }[action]

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_email or "noreply@example.invalid"
    message["To"] = recipient
    message.set_content(
        f"{instruction}\n\n{link}\n\n"
        f"El enlace vence en {settings.email_action_token_expire_minutes} minutos. "
        "Si no solicitaste esta acción, puedes ignorar este correo."
    )

    try:
        await asyncio.to_thread(_send_message, message)
    except Exception:
        # Never log the recipient, action URL, or token.
        logger.warning("Account action email could not be delivered.")
        return False
    return True
