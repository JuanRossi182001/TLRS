from warnings import warn

from src.settings import Settings, settings

warn(
    "mqtt_worker.config is deprecated; import settings from src.settings instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["Settings", "settings"]
