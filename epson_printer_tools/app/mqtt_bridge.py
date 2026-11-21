"""Optional MQTT bridge: expose the printer as Home Assistant entities via discovery."""

import json
import threading

from mqtt_min import MiniMqtt

DISCOVERY_PREFIX = "homeassistant"
NODE_ID = "epson_printer_tools"


class MqttBridge:
    def __init__(self, config, on_command):
        self.config = config
        self.on_command = on_command
        self.client = None
        self.topic_prefix = config.get("mqtt_prefix") or "epson_printer"
        self.ok = False

    @property
    def enabled(self):
        return bool(self.config.get("mqtt_enabled"))

    def start(self):
        if not self.enabled:
            return False
        host = self.config.get("mqtt_host") or "core-mosquitto"
        port = int(self.config.get("mqtt_port") or 1883)
        client = MiniMqtt(
            host,
            port,
            username=self.config.get("mqtt_username") or None,
            password=self.config.get("mqtt_password") or None,
        )
        client.on_message = self._on_message
        try:
            client.connect()
        except OSError:
            self.ok = False
            return False
        self.client = client
        self.ok = True
        client.publish(f"{self.topic_prefix}/availability", "online", retain=True)
        for action in ("nozzle_check", "head_clean"):
            client.subscribe(f"{self.topic_prefix}/button/{action}")
        threading.Thread(target=client.loop_ping, daemon=True).start()
        return True

    def _device(self, state):
        return {
            "identifiers": [NODE_ID],
            "name": "Epson Printer",
            "manufacturer": "Epson",
            "model": state.get("model") or "Epson inkjet",
            "serial_number": state.get("serial") or None,
        }

    def _publish_discovery(self, state):
        device = self._device(state)
        availability = f"{self.topic_prefix}/availability"
        entities = [
            ("sensor", "status", {"name": "Printer status",
                                  "state_topic": f"{self.topic_prefix}/status",
                                  "icon": "mdi:printer-check"}),
            ("sensor", "pages", {"name": "Pages printed",
                                 "state_topic": f"{self.topic_prefix}/pages",
                                 "state_class": "total_increasing",
                                 "unit_of_measurement": "pages",
                                 "icon": "mdi:file-document-multiple"}),
            ("sensor", "last_print", {"name": "Last print",
                                      "state_topic": f"{self.topic_prefix}/last_print",
                                      "device_class": "timestamp", "icon": "mdi:clock-check"}),
            ("sensor", "last_clean", {"name": "Last head cleaning",
                                      "state_topic": f"{self.topic_prefix}/last_clean",
                                      "device_class": "timestamp", "icon": "mdi:water-sync"}),
            ("button", "nozzle_check", {"name": "Nozzle check",
                                        "icon": "mdi:format-color-fill",
                                        "command_topic": f"{self.topic_prefix}/button/nozzle_check",
                                        "payload_press": "PRESS"}),
            ("button", "head_clean", {"name": "Head cleaning",
                                      "icon": "mdi:water-sync",
                                      "command_topic": f"{self.topic_prefix}/button/head_clean",
                                      "payload_press": "PRESS"}),
        ]
        for component, object_id, payload in entities:
            payload["unique_id"] = f"{NODE_ID}_{object_id}"
            payload["device"] = device
            payload["availability_topic"] = availability
            topic = f"{DISCOVERY_PREFIX}/{component}/{NODE_ID}/{object_id}/config"
            self.client.publish(topic, json.dumps(payload), retain=True)

    def _on_message(self, topic, payload):
        action = topic.rsplit("/", 1)[-1]
        if action in ("nozzle_check", "head_clean"):
            threading.Thread(target=self.on_command, args=(action,), daemon=True).start()

    def publish_state(self, state):
        if not self.client or not self.ok:
            return
        client = self.client
        client.publish(f"{self.topic_prefix}/status", state.get("printer_state") or "unknown", retain=True)
        if state.get("pages_total") is not None:
            client.publish(f"{self.topic_prefix}/pages", str(state["pages_total"]), retain=True)
        if state.get("last_print"):
            client.publish(f"{self.topic_prefix}/last_print", state["last_print"], retain=True)
        if state.get("last_clean"):
            client.publish(f"{self.topic_prefix}/last_clean", state["last_clean"], retain=True)
        self._publish_discovery(state)

    def stop(self):
        if not self.client:
            return
        self.client.publish(f"{self.topic_prefix}/availability", "offline", retain=True)
        self.client.disconnect()
