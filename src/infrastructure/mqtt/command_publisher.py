from __future__ import annotations

import json
import ssl
from typing import Any

from paho.mqtt.client import Client, MQTT_ERR_SUCCESS

from src.settings import settings


class MqttCommandPublishError(RuntimeError):
    pass


class MqttCommandPublisher:
    def __init__(
        self,
        client_id: str = "manea-command-dispatcher",
        keepalive: int = 60,
    ):
        self.client_id = client_id
        self.keepalive = keepalive

    def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        client = Client(client_id=self.client_id)
        client.username_pw_set(
            username=settings.mqtt_dispatcher_username,
            password=settings.mqtt_dispatcher_password,
        )
        self._configure_tls(client)

        try:
            client.connect(
                host=settings.mqtt_host,
                port=settings.mqtt_port,
                keepalive=self.keepalive,
            )
            client.loop_start()
            info = client.publish(
                topic=topic,
                payload=json.dumps(payload),
                qos=qos,
                retain=retain,
            )
            info.wait_for_publish(timeout=10)
            if info.rc != MQTT_ERR_SUCCESS:
                raise MqttCommandPublishError(f"MQTT publish failed with rc={info.rc}")
        except MqttCommandPublishError:
            raise
        except Exception as exc:
            raise MqttCommandPublishError(str(exc)) from exc
        finally:
            client.loop_stop()
            client.disconnect()

    def _configure_tls(self, client: Client) -> None:
        if not settings.mqtt_tls_enabled:
            return

        client.tls_set(
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        client.tls_insecure_set(False)
