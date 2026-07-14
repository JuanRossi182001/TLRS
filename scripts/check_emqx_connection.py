import argparse
import json
import os
import ssl
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from paho.mqtt.client import CallbackAPIVersion, Client, MQTT_ERR_SUCCESS, MQTTMessage


DEFAULT_TOPIC = "manea/debug/chirpstack/check"
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / "infra" / "chirpstack" / ".env"


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_env(env_file: str | None) -> None:
    if env_file:
        load_dotenv(env_file, override=False)
        return

    if DEFAULT_ENV_FILE.exists():
        load_dotenv(DEFAULT_ENV_FILE, override=False)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EmqxConnectionCheck:
    def __init__(self, topic: str, timeout_seconds: float, subscribe: bool):
        self.topic = topic
        self.timeout_seconds = timeout_seconds
        self.subscribe = subscribe
        self.nonce = uuid4().hex
        self.connected = threading.Event()
        self.received = threading.Event()
        self.message_received = False

        self.host = required_env("EMQX_MQTT_HOST")
        self.port = int(os.getenv("EMQX_MQTT_PORT", "8883"))
        self.username = os.getenv("EMQX_MQTT_USERNAME")
        self.password = os.getenv("EMQX_MQTT_PASSWORD")
        self.use_tls = env_bool("EMQX_MQTT_USE_TLS", default=True)

        self.client = Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"chirpstack-emqx-check-{self.nonce[:8]}",
        )
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        if self.username:
            self.client.username_pw_set(username=self.username, password=self.password)

        if self.use_tls:
            self.client.tls_set(
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            self.client.tls_insecure_set(False)

    def on_connect(self, client: Client, userdata, flags, reason_code, properties=None) -> None:
        print(f"[EMQX CHECK] Connected. reason_code={reason_code}")
        self.connected.set()

        if self.subscribe:
            result, _mid = client.subscribe(self.topic, qos=1)
            if result == MQTT_ERR_SUCCESS:
                print(f"[EMQX CHECK] Subscribed to {self.topic}")
            else:
                print(f"[EMQX CHECK] Subscribe request failed with rc={result}")

    def on_disconnect(self, client: Client, userdata, disconnect_flags=None, reason_code=None, properties=None) -> None:
        if reason_code is None:
            reason_code = disconnect_flags
        print(f"[EMQX CHECK] Disconnected. reason_code={reason_code}")

    def on_message(self, client: Client, userdata, message: MQTTMessage) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except Exception as exc:
            print(f"[EMQX CHECK] Received non-JSON payload on {message.topic}: {exc}")
            self.received.set()
            return

        if payload.get("nonce") == self.nonce:
            self.message_received = True
            print(f"[EMQX CHECK] Received loopback message on {message.topic}")
            self.received.set()

    def run(self) -> int:
        payload = {
            "source": "scripts/check_emqx_connection.py",
            "time": now_iso(),
            "nonce": self.nonce,
            "message": "chirpstack emqx connectivity check",
        }

        print(f"[EMQX CHECK] Broker: {self.host}:{self.port}")
        print(f"[EMQX CHECK] TLS: {self.use_tls}")
        print(f"[EMQX CHECK] Username: {self.username}")
        print(f"[EMQX CHECK] Topic: {self.topic}")

        self.client.connect(host=self.host, port=self.port, keepalive=60)
        self.client.loop_start()

        try:
            if not self.connected.wait(timeout=self.timeout_seconds):
                raise TimeoutError("Timed out waiting for MQTT connection")

            publish_info = self.client.publish(self.topic, json.dumps(payload), qos=1)
            publish_info.wait_for_publish(timeout=self.timeout_seconds)
            if publish_info.rc != MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publish failed with rc={publish_info.rc}")

            print("[EMQX CHECK] Publish OK")

            if not self.subscribe:
                return 0

            if self.received.wait(timeout=self.timeout_seconds):
                return 0 if self.message_received else 1

            print("[EMQX CHECK] No loopback message received before timeout")
            print("[EMQX CHECK] This can still mean connect/publish worked but subscribe ACL is missing")
            return 0
        finally:
            self.client.loop_stop()
            self.client.disconnect()


def required_env(name: str) -> str:
    value = os.getenv(name)
    if value and value.strip():
        return value.strip()
    raise ValueError(f"Missing required environment variable: {name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate EMQX Cloud MQTT TLS credentials")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Path to env file")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="MQTT debug topic")
    parser.add_argument("--timeout-seconds", type=float, default=8.0, help="Timeout for connect/publish/loopback")
    parser.add_argument("--publish-only", action="store_true", help="Skip subscribe and loopback validation")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env(args.env_file)

    checker = EmqxConnectionCheck(
        topic=args.topic,
        timeout_seconds=args.timeout_seconds,
        subscribe=not args.publish_only,
    )
    return checker.run()


if __name__ == "__main__":
    raise SystemExit(main())
