import os
import sys
from pathlib import Path

import grpc
from chirpstack_api import api

from src.integrations.chirpstack.downlink_encoder import encode_command_downlink
from src.models.device_command import DeviceCommandType


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or not value.strip():
        raise RuntimeError(f"Environment variable {name} is required")
    return value.strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    host = env("CHIRPSTACK_API_HOST")
    port = env("CHIRPSTACK_API_PORT", "8080")
    token = env("CHIRPSTACK_API_TOKEN")
    dev_eui = os.getenv("DEV_EUI") or os.getenv("CHIRPSTACK_DEV_EUI")
    if dev_eui is None or not dev_eui.strip():
        raise RuntimeError("Environment variable DEV_EUI or CHIRPSTACK_DEV_EUI is required")

    target = f"{host}:{port}"
    use_tls = env_bool("CHIRPSTACK_API_USE_TLS", default=False)
    timeout_seconds = float(os.getenv("CHIRPSTACK_API_TIMEOUT_SECONDS", "10"))

    if use_tls:
        channel = grpc.secure_channel(target, grpc.ssl_channel_credentials())
    else:
        channel = grpc.insecure_channel(target)

    try:
        client = api.DeviceServiceStub(channel)
        request = api.EnqueueDeviceQueueItemRequest()
        request.queue_item.dev_eui = "".join(dev_eui.split()).lower()
        encoded = encode_command_downlink(
            command_uuid="grpc-smoke-test",
            command_seq=1,
            command_type=DeviceCommandType.REQUEST_STATUS,
            payload_fields={},
        )
        request.queue_item.confirmed = encoded.confirmed
        request.queue_item.f_port = encoded.f_port
        request.queue_item.data = encoded.data

        response = client.Enqueue(
            request,
            metadata=[("authorization", f"Bearer {token}")],
            timeout=timeout_seconds,
        )
    finally:
        channel.close()

    print(f"queueItemId={response.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
