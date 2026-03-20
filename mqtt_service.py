"""
mqtt_service.py – MQTT publisher for conveyor zone counts.

Publishes a JSON snapshot to the topic::

    Conveyor/Current_Count/Day_Total_Count

Payload format::

    {
      "L1Z1": {"current": 3, "day_total": 45},
      "L1Z2": {"current": 2, "day_total": 38},
      ...
    }

Requires paho-mqtt (``pip install paho-mqtt``).
If paho-mqtt is not installed the service degrades gracefully (no publish).
"""

import json
import logging

try:
    import paho.mqtt.client as mqtt
    _PAHO_OK = True
except ImportError:
    _PAHO_OK = False
    logging.warning(
        "paho-mqtt not installed – MQTT publishing is disabled. "
        "Install it with:  pip install paho-mqtt"
    )

log = logging.getLogger(__name__)

MQTT_TOPIC = "Conveyor/Current_Count/Day_Total_Count"


class MQTTService:
    """Non-blocking MQTT publisher using paho-mqtt's async loop."""

    def __init__(self, broker="localhost", port=1883, client_id="conveyor_pc"):
        self._broker = broker
        self._port = int(port)
        self._client_id = client_id
        self._client = None
        self._connected = False

    # ── connection ─────────────────────────────────────────────────────

    def connect(self):
        """Start the async MQTT connection.  Returns True on success."""
        if not _PAHO_OK:
            return False
        try:
            self._client = mqtt.Client(client_id=self._client_id)
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.connect_async(self._broker, self._port, keepalive=60)
            self._client.loop_start()
            return True
        except Exception as exc:
            log.error("MQTT connect error: %s", exc)
            return False

    def disconnect(self):
        """Stop the MQTT loop and disconnect."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
        self._connected = False

    @property
    def is_connected(self):
        return self._connected

    # ── publishing ─────────────────────────────────────────────────────

    def publish(self, zones_snapshot):
        """
        Publish a zone-count snapshot dict to the MQTT topic.

        :param zones_snapshot: dict as returned by ZoneTracker.get_snapshot()
        """
        if not self._client or not self._connected:
            return
        try:
            payload = json.dumps(zones_snapshot)
            self._client.publish(MQTT_TOPIC, payload, qos=0, retain=True)
            log.debug("Published to %s: %s", MQTT_TOPIC, payload)
        except Exception as exc:
            log.error("MQTT publish error: %s", exc)

    # ── paho callbacks ─────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        self._connected = rc == 0
        if rc == 0:
            log.info("MQTT connected to %s:%d", self._broker, self._port)
        else:
            log.warning("MQTT connection failed, rc=%d", rc)

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            log.warning("MQTT unexpected disconnect (rc=%d), will auto-reconnect", rc)
