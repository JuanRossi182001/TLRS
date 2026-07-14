from __future__ import annotations

import base64
import json
import ssl

from paho.mqtt.client import CallbackAPIVersion, Client, MQTT_ERR_SUCCESS

from src.integrations.chirpstack.downlink_encoder import EncodedChirpStackDownlink
from src.settings import settings


class ChirpStackDownlinkPublishError(RuntimeError):
    pass


class ChirpStackDownlinkClient:
    def __init__(
        self,
        client_id: str = "manea-chirpstack-downlink",
        keepalive: int = 60,
    ):
        self.client_id = client_id
        self.keepalive = keepalive

    def build_topic(
        self,
        application_id: str,
        dev_eui: str,
    ) -> str:
        return f"application/{application_id}/device/{dev_eui}/command/down"

    def build_payload(
        self,
        dev_eui: str,
        encoded_downlink: EncodedChirpStackDownlink,
        confirmed: bool = True,
    ) -> dict[str, object]:
        return {
            "devEui": dev_eui,
            "confirmed": encoded_downlink.confirmed if confirmed is True else confirmed,
            "fPort": encoded_downlink.f_port,
            "data": base64.b64encode(encoded_downlink.data).decode("ascii"),
            "commandId": encoded_downlink.command_id,
            "commandSeq": encoded_downlink.command_seq,
        }

    def publish(
        self,
        topic: str,
        payload: dict[str, object],
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        client = Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
        )

        username = settings.chirpstack_event_mqtt_username
        password = settings.chirpstack_event_mqtt_password
        if username:
            client.username_pw_set(username=username, password=password)

        self._configure_tls(client)

        try:
            client.connect(
                host=settings.chirpstack_event_mqtt_host,
                port=settings.chirpstack_event_mqtt_port,
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
                raise ChirpStackDownlinkPublishError(
                    f"ChirpStack downlink publish failed with rc={info.rc}"
                )
        except ChirpStackDownlinkPublishError:
            raise
        except Exception as exc:
            raise ChirpStackDownlinkPublishError(str(exc)) from exc
        finally:
            client.loop_stop()
            client.disconnect()

    def _configure_tls(self, client: Client) -> None:
        if not settings.chirpstack_event_mqtt_tls_enabled:
            return

        client.tls_set(
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        client.tls_insecure_set(False)
