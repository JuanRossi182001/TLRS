import os
from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, field_validator


class SettingsConfigDict(TypedDict, total=False):
    env_file: str
    env_file_encoding: str
    extra: str
    secrets_dir: str


class BaseSettings(BaseModel):
    def __init__(self, **data: Any) -> None:
        config = getattr(self, "model_config", {})
        env_file = config.get("env_file")
        env_file_encoding = config.get("env_file_encoding") or "utf-8"
        secrets_dir = config.get("secrets_dir")

        values: dict[str, Any] = {}
        if env_file:
            values.update(self._read_env_file(Path(env_file), env_file_encoding))
        if secrets_dir:
            values.update(self._read_secrets_dir(Path(secrets_dir), env_file_encoding))

        for field_name in type(self).model_fields:
            env_value = self._read_env_value(field_name)
            if env_value is not None:
                values[field_name] = env_value

        values.update(data)
        super().__init__(**values)

    @staticmethod
    def _read_env_file(path: Path, encoding: str) -> dict[str, str]:
        if not path.exists():
            return {}

        values: dict[str, str] = {}
        for raw_line in path.read_text(encoding=encoding).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            values[key.strip().lower()] = BaseSettings._clean_env_value(value)

        return values

    @staticmethod
    def _read_secrets_dir(path: Path, encoding: str) -> dict[str, str]:
        if not path.exists() or not path.is_dir():
            return {}

        values: dict[str, str] = {}
        for secret_file in path.iterdir():
            if secret_file.is_file():
                values[secret_file.name.lower()] = secret_file.read_text(
                    encoding=encoding
                ).strip()

        return values

    @staticmethod
    def _read_env_value(field_name: str) -> str | None:
        for key in (field_name, field_name.upper()):
            if key in os.environ:
                return BaseSettings._clean_env_value(os.environ[key])

        return None

    @staticmethod
    def _clean_env_value(value: str) -> str:
        cleaned = value.strip()
        if cleaned.startswith("="):
            cleaned = cleaned[1:].strip()
        return cleaned.strip("\"'")


class Settings(BaseSettings):
    db_connection_url: str | None = None
    database_url: str | None = None
    db_schema_name: str = "public"

    mqtt_host: str 
    mqtt_port: int

    mqtt_username: str = "gps_worker"
    mqtt_password: str = "password"

    mqtt_location_topic: str = "gps/devices/+/location"
    mqtt_tls_enabled: bool = False
    credential_encryption_key: str | None = None
    

    emqx_api_base_url: str
    emqx_api_key: str
    emqx_api_secret: str
    emqx_authentication_id: str = "password_based:built_in_database"
    emqx_authorization_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        secrets_dir="/run/secrets",
    )

    jwt_secret_key: str | None = None
    jwt_algorithm: str | None = None
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30
    environment: str = "development"
    refresh_token_cookie_secure: bool | None = None
    refresh_token_cookie_samesite: str = "lax"
    refresh_token_cookie_path: str = "/user/auth"
    user_session_max_active_sessions: int = 5
    user_session_cleanup_retention_days: int = 2
    user_session_cleanup_interval_hours: int = 6

    @field_validator("refresh_token_cookie_secure", mode="before")
    @classmethod
    def validate_refresh_token_cookie_secure(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().strip("\"'").lower()
            if normalized in {"", "none", "null", "bool | none = none"}:
                return None
        return value

    @property
    def sqlalchemy_database_url(self) -> str:
        database_url = self.db_connection_url or self.database_url
        if database_url:
            return database_url

        raise RuntimeError(
            "Database connection is not configured. Set DB_CONNECTION_URL, "
            "DATABASE_URL, or mount /run/secrets/db_connection_url."
        )


settings = Settings()
