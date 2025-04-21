import paho.mqtt.client as mqtt
import logging
import json
import time
import random
import threading
from typing import Optional, Union
from dataclasses import asdict

from ratsensor.core.domain import SensorData, SystemInfo, AppConfig
from ratsensor.core.ports import DataPublisher, AdminCommandListener, AdminCommandHandler

logger = logging.getLogger(__name__)

class MqttAdapter(DataPublisher, AdminCommandListener):
    def __init__(self, config: AppConfig, device_id: str):
        self.config = config
        self.device_id = device_id
        self.client: Optional[mqtt.Client] = None
        self._is_connected = False
        self._lock = threading.Lock()
        self._admin_handler: Optional[AdminCommandHandler] = None
        self._mqtt_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_connection_attempt_time = 0
        self._current_retry_delay = config.mqtt_initial_retry_delay

        self.sensor_topic = config.mqtt_sensor_topic_template.format(self.device_id)
        self.info_topic = config.mqtt_info_topic_template.format(self.device_id)
        self.admin_topic = None
        if config.listen_for_admin and config.mqtt_admin_topic_template:
             # Handle cases like "admin/{}" or just "admin/commands"
             if "{}" in config.mqtt_admin_topic_template:
                 self.admin_topic = config.mqtt_admin_topic_template.format(self.device_id)
             else:
                 self.admin_topic = config.mqtt_admin_topic_template # Use as is
             logger.info(f"MQTT Admin topic configured: {self.admin_topic}")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        with self._lock:
            if rc == 0:
                logger.info(f"MQTT: Successfully connected to broker {self.config.mqtt_broker}:{self.config.mqtt_port} (rc={rc})")
                self._is_connected = True
                self._current_retry_delay = self.config.mqtt_initial_retry_delay # Reset backoff
                # Subscribe to admin topic if configured and connected
                if self.admin_topic and self._admin_handler:
                    try:
                        result, mid = client.subscribe(self.admin_topic, qos=1) # Use QoS 1 for commands
                        if result == mqtt.MQTT_ERR_SUCCESS:
                            logger.info(f"MQTT: Subscribed to admin topic: {self.admin_topic}")
                        else:
                            logger.warning(f"MQTT: Failed to subscribe to admin topic {self.admin_topic} (Error code: {result})")
                    except Exception as e:
                        logger.error(f"MQTT: Error during subscription to {self.admin_topic}", exc_info=True)
            else:
                logger.error(f"MQTT: Connection failed with result code: {rc}. Check broker/credentials/network.")
                self._is_connected = False
                # Connection failed, backoff handled in connect loop

    def _on_disconnect(self, client, userdata, rc, properties=None):
        with self._lock:
            # Only log unexpected disconnects
            if rc != 0:
                logger.warning(f"MQTT: Unexpectedly disconnected from broker (rc={rc}). Will attempt reconnect.")
            else:
                logger.info("MQTT: Disconnected gracefully.")
            self._is_connected = False
        # Reconnect logic is handled by the background thread/connect method

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload_str = ""
        try:
            payload_str = msg.payload.decode().strip()
            logger.info(f"MQTT: Received message on topic '{topic}': {payload_str}")

            if topic == self.admin_topic and self._admin_handler:
                command = payload_str.lower()
                # Run handler in a separate thread to avoid blocking MQTT loop
                handler_thread = threading.Thread(target=self._admin_handler, args=(command,))
                handler_thread.daemon = True
                handler_thread.start()
            else:
                logger.debug(f"MQTT: Message ignored on topic {topic}.")

        except Exception as e:
            logger.error(f"MQTT: Error processing message on topic {topic}, payload '{payload_str}'", exc_info=True)

    def _create_client(self) -> mqtt.Client:
        client_id = f"ratsensor-{self.device_id}-{random.randint(100, 999)}"
        logger.debug(f"MQTT: Creating client with ID: {client_id}")
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        if self.admin_topic:
            client.on_message = self._on_message

        if self.config.mqtt_user and self.config.mqtt_pass:
            client.username_pw_set(self.config.mqtt_user, self.config.mqtt_pass)
            logger.info("MQTT: Using authentication.")

        # Configure LWT (Last Will and Testament) - Optional but good practice
        lwt_topic = f"status/{self.device_id}"
        lwt_payload = json.dumps({"status": "offline", "reason": "unexpected_disconnect"})
        client.will_set(lwt_topic, payload=lwt_payload, qos=1, retain=True)
        logger.info(f"MQTT: LWT configured on topic {lwt_topic}")

        return client

    def _connection_loop(self):
        """Background thread to manage connection and process messages."""
        while not self._stop_event.is_set():
            with self._lock:
                is_connected_state = self._is_connected

            if not is_connected_state:
                now = time.monotonic()
                if now - self._last_connection_attempt_time >= self._current_retry_delay:
                    self._last_connection_attempt_time = now
                    logger.info(f"MQTT: Attempting connection (Retry delay: {self._current_retry_delay:.1f}s)...")
                    try:
                        if self.client:
                            # Clean up old client resources if reconnecting
                            try:
                                self.client.loop_stop()
                            except: pass # Ignore errors stopping non-running loop
                            try:
                                self.client.disconnect()
                            except: pass # Ignore errors disconnecting non-connected client

                        self.client = self._create_client()
                        self.client.connect(self.config.mqtt_broker, self.config.mqtt_port, 60)
                        self.client.loop_start()

                        # Wait a short moment to see if on_connect gets called
                        connect_start_time = time.monotonic()
                        while time.monotonic() - connect_start_time < 5 and not self.is_connected():
                            time.sleep(0.1)

                        if not self.is_connected():
                            logger.warning("MQTT: Connection attempt failed or timed out.")
                            # Increase backoff delay
                            self._current_retry_delay = min(
                                self._current_retry_delay * self.config.mqtt_retry_backoff_factor,
                                self.config.mqtt_max_retry_delay
                            )
                            # Add jitter
                            self._current_retry_delay += random.uniform(0, 5)
                            # Stop the loop in case connect failed but loop_start was called
                            try:
                                self.client.loop_stop()
                            except: pass


                    except (ConnectionRefusedError, OSError) as e:
                        logger.error(f"MQTT: Connection error: {e}")
                        self._is_connected = False
                        # Increase backoff delay
                        self._current_retry_delay = min(
                            self._current_retry_delay * self.config.mqtt_retry_backoff_factor,
                            self.config.mqtt_max_retry_delay
                        )
                        self._current_retry_delay += random.uniform(0, 5) # Jitter
                        if self.client:
                            try: self.client.loop_stop()
                            except: pass
                    except Exception as e:
                        logger.error(f"MQTT: Unexpected error during connection attempt: {e}", exc_info=True)
                        self._is_connected = False
                        # Increase backoff delay (as above)
                        self._current_retry_delay = min(
                            self._current_retry_delay * self.config.mqtt_retry_backoff_factor,
                            self.config.mqtt_max_retry_delay
                        )
                        self._current_retry_delay += random.uniform(0, 5) # Jitter
                        if self.client:
                            try: self.client.loop_stop()
                            except: pass
            else:
                # Connected, sleep for a bit before checking again
                time.sleep(1)

        # Loop exited (stop_event set)
        logger.info("MQTT connection loop stopped.")
        if self.client:
            try:
                # Publish online status false on graceful shutdown
                lwt_topic = f"status/{self.device_id}"
                lwt_payload = json.dumps({"status": "offline", "reason": "shutdown"})
                self.client.publish(lwt_topic, payload=lwt_payload, qos=1, retain=True)
                time.sleep(0.5) # Allow time for publish
                self.client.loop_stop()
                self.client.disconnect()
                logger.info("MQTT client disconnected and loop stopped.")
            except Exception as e:
                logger.error(f"MQTT: Error during final disconnect: {e}", exc_info=True)
        with self._lock:
            self._is_connected = False


    # --- DataPublisher Interface ---

    def connect(self) -> bool:
        """Starts the background connection management thread."""
        if self._mqtt_thread and self._mqtt_thread.is_alive():
            logger.warning("MQTT connect called, but connection thread is already running.")
            return True

        logger.info("Starting MQTT connection management thread...")
        self._stop_event.clear()
        self._mqtt_thread = threading.Thread(target=self._connection_loop, daemon=True)
        self._mqtt_thread.start()

        # Give it a moment to try the first connection
        time.sleep(2)
        return self.is_connected() # Return initial connection status

    def disconnect(self) -> None:
        """Stops the background connection management thread."""
        logger.info("Stopping MQTT connection management thread...")
        self._stop_event.set()
        if self._mqtt_thread and self._mqtt_thread.is_alive():
            self._mqtt_thread.join(timeout=10) # Wait for thread to finish
            if self._mqtt_thread.is_alive():
                logger.warning("MQTT connection thread did not stop gracefully.")
        self._mqtt_thread = None
        # Final disconnect happens within the loop when stop_event is set

    def is_connected(self) -> bool:
        with self._lock:
            return self._is_connected

    def publish_sensor_data(self, data: SensorData) -> bool:
        return self._publish(self.sensor_topic, data)

    def publish_info_data(self, data: SystemInfo) -> bool:
        return self._publish(self.info_topic, data)

    def _publish(self, topic: str, data: Union[SensorData, SystemInfo]) -> bool:
        if not self.is_connected() or not self.client:
            logger.debug(f"MQTT: Cannot publish to {topic}, not connected.")
            return False

        try:
            # Use dataclasses.asdict for clean JSON conversion
            payload = json.dumps(asdict(data), ensure_ascii=False)
            msg_info = self.client.publish(topic, payload, qos=0) # Use QoS 0 for sensor data
            # msg_info.wait_for_publish(timeout=5) # Optional: wait for ack for QoS > 0
            if msg_info.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"MQTT: Published to {topic}: {payload}")
                return True
            else:
                logger.warning(f"MQTT: Failed to publish to {topic} (rc={msg_info.rc})")
                # If publish fails, could indicate connection issue
                if msg_info.rc in [mqtt.MQTT_ERR_NO_CONN, mqtt.MQTT_ERR_CONN_LOST]:
                     with self._lock:
                         self._is_connected = False # Mark as disconnected
                return False
        except Exception as e:
            logger.error(f"MQTT: Error publishing to {topic}: {e}", exc_info=True)
            # Assume connection lost on publish error
            with self._lock:
                self._is_connected = False
            return False

    # --- AdminCommandListener Interface ---

    def start_listening(self, handler: AdminCommandHandler) -> bool:
        """Registers the handler. Subscription happens on connect."""
        if not self.config.listen_for_admin or not self.admin_topic:
            logger.warning("Admin listening requested, but not enabled in config.")
            return False

        logger.info(f"Registering admin command handler for topic {self.admin_topic}.")
        self._admin_handler = handler

        # If already connected, subscribe now. Otherwise, it happens in _on_connect.
        if self.is_connected() and self.client:
             try:
                 result, mid = self.client.subscribe(self.admin_topic, qos=1)
                 if result == mqtt.MQTT_ERR_SUCCESS:
                     logger.info(f"MQTT: Subscribed to admin topic: {self.admin_topic}")
                     return True
                 else:
                     logger.warning(f"MQTT: Failed to subscribe to admin topic {self.admin_topic} (Error code: {result})")
                     return False
             except Exception as e:
                 logger.error(f"MQTT: Error during immediate subscription to {self.admin_topic}", exc_info=True)
                 return False
        return True # Handler registered, subscription will happen on connect

    def stop_listening(self) -> None:
        """Unregisters handler and unsubscribes."""
        if self.admin_topic and self.client and self.is_connected():
            logger.info(f"Unsubscribing from admin topic: {self.admin_topic}")
            try:
                self.client.unsubscribe(self.admin_topic)
            except Exception as e:
                logger.error(f"MQTT: Error unsubscribing from {self.admin_topic}", exc_info=True)
        self._admin_handler = None
        logger.info("Admin command handler unregistered.")

