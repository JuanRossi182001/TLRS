from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883

    mqtt_username: str = "gps_worker"
    mqtt_password: str = "password"

    mqtt_location_topic: str = "gps/devices/+/location"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()