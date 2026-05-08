import secrets

from cryptography.fernet import Fernet, InvalidToken

from src.settings import settings


class CredentialGenerator:
    def __init__(self, encryption_key: str | None = None):
        self.encryption_key = encryption_key or settings.credential_encryption_key

    def generate_mqtt_password(self) -> str:
        return secrets.token_urlsafe(32)

    def generate_hmac_secret(self) -> str:
        return secrets.token_urlsafe(48)

    def build_mqtt_username(self, serial: str) -> str:
        normalized = serial.lower().replace("-", "_")
        return f"device_{normalized}"

    def encrypt_password(self, password: str) -> str:
        fernet = self._get_fernet()
        return fernet.encrypt(password.encode("utf-8")).decode("utf-8")

    def decrypt_password(self, password: str) -> str:
        fernet = self._get_fernet()

        try:
            return fernet.decrypt(password.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Encrypted password token is invalid.") from exc

    def _get_fernet(self) -> Fernet:
        if not self.encryption_key:
            raise RuntimeError(
                "Set CREDENTIAL_ENCRYPTION_KEY before encrypting passwords."
            )

        return Fernet(self.encryption_key.encode("utf-8"))
