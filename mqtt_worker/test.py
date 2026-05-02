import json
from datetime import datetime, timezone

from paho.mqtt.client import Client


BROKER_HOST = "localhost"
BROKER_PORT = 1883

MQTT_USERNAME = "device_aaa_001"
MQTT_PASSWORD = "devicepass123"

DEVICE_SERIAL = "AAA-001"
TOPIC = f"gps/devices/{DEVICE_SERIAL}/location"


payload = {
    "device_serial": "AAA-999",
    "lat": -31.4135,
    "lng": -64.1810,
    "timestamp": int(datetime.now(timezone.utc).timestamp()),
    "accuracy": 4.2,
    "altitude": 430.5,
    "speed": 12.8,
    "battery": 87,
}


client = Client(client_id="gps-test-publisher")
client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

client.connect(BROKER_HOST, BROKER_PORT)
client.loop_start()

result = client.publish(
    topic=TOPIC,
    payload=json.dumps(payload),
    qos=1,
)

result.wait_for_publish()

print("Mensaje publicado:")
print(json.dumps(payload, indent=2))

client.loop_stop()
client.disconnect()