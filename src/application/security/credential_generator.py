import secrets


class CredentialGenerator:
    def generate_mqtt_password(self) -> str:
        return secrets.token_urlsafe(32)

    def generate_hmac_secret(self) -> str:
        return secrets.token_urlsafe(48)

    def build_mqtt_username(self, serial: str) -> str:
        normalized = serial.lower().replace("-", "_")
        return f"device_{normalized}"