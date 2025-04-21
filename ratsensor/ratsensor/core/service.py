import time
import logging
import json
from datetime import datetime, timezone
from typing import List, Optional

from ratsensor.core.domain import SensorData, SystemInfo, AppConfig
from ratsensor.core.ports import (
    SensorReader, SystemInfoReader, DataPublisher, DataStorage,
    DeviceIdentityProvider, CommandExecutor, AdminCommandListener,
    AdminCommandHandler
)

logger = logging.getLogger(__name__)

class SensorMonitoringService:
    def __init__(
        self,
        config: AppConfig,
        sensor_reader: SensorReader,
        sys_info_reader: SystemInfoReader,
        publisher: DataPublisher,
        storage: DataStorage,
        identity_provider: DeviceIdentityProvider,
        command_executor: CommandExecutor,
        admin_listener: Optional[AdminCommandListener] = None,
    ):
        self.config = config
        self.sensor_reader = sensor_reader
        self.sys_info_reader = sys_info_reader
        self.publisher = publisher
        self.storage = storage
        self.identity_provider = identity_provider
        self.command_executor = command_executor
        self.admin_listener = admin_listener

        self.device_id: str = "unknown"
        self._running = False
        self._sensor_data_buffer: List[SensorData] = []
        self._measurement_count = 0

    def _handle_admin_command(self, command: str):
        """Callback passed to the AdminCommandListener."""
        logger.warning(f"Received admin command: {command}")
        if command == "reboot":
            logger.warning("Executing reboot command...")
            time.sleep(1) # Give time for log message to flush
            try:
                self.publisher.disconnect() # Attempt graceful disconnect
                if self.admin_listener:
                    self.admin_listener.stop_listening()
            except Exception as e:
                logger.error(f"Error during pre-reboot cleanup: {e}")
            self.command_executor.execute_reboot()
        else:
            logger.warning(f"Unknown admin command received: {command}")

    def initialize(self) -> bool:
        """Initialize all components."""
        logger.info("Initializing Sensor Monitoring Service...")
        try:
            self.device_id = self.identity_provider.get_device_id()
            if not self.device_id or self.device_id.startswith("temp-"):
                logger.critical("Failed to get a persistent device ID.")
                return False
            logger.info(f"Using Device ID: {self.device_id}")

            if not self.sensor_reader.initialize():
                logger.warning("Sensor reader initialization failed.")
                # Decide if this is critical or if simulation fallback is ok
                # For now, we assume the adapter handles simulation internally

            if not self.storage.initialize():
                logger.warning("Data storage initialization failed. Data will not be saved locally.")
                # Allow continuing without local storage

            # Publisher connection is handled in the run loop with retries

            if self.config.listen_for_admin and self.admin_listener:
                logger.info("Admin command listening is enabled.")
                # Listener is started/managed by the publisher adapter usually
            else:
                logger.info("Admin command listening is disabled.")

            logger.info("Service initialization complete.")
            return True

        except Exception as e:
            logger.error(f"Critical error during service initialization: {e}", exc_info=True)
            return False

    def run(self):
        """Main execution loop."""
        if not self.initialize():
            logger.critical("Service initialization failed. Exiting.")
            return

        logger.info(f"Starting main loop. Read interval: {self.config.read_interval_seconds}s, DB save interval: {self.config.db_save_interval_reads} reads.")
        self._running = True

        while self._running:
            loop_start_time = time.monotonic()

            try:
                # 1. Ensure Publisher Connection (handled by publisher adapter)
                # The adapter should manage its connection state and retries.
                # We just check if it's ready before attempting to publish.

                # 2. Read Sensor Data
                timestamp_now = datetime.now(timezone.utc)
                timestamp_iso = timestamp_now.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

                sensor_data = self.sensor_reader.read_sensors()
                sensor_data.timestamp = timestamp_iso # Ensure consistent timestamp
                sensor_data.device_id = self.device_id

                # 3. Read System Info
                sys_info = self.sys_info_reader.read_system_info()
                sys_info.timestamp = timestamp_iso # Use same timestamp
                sys_info.device_id = self.device_id

                # 4. Buffer Data for Storage
                self._sensor_data_buffer.append(sensor_data)
                self._measurement_count += 1

                # 5. Save to Database (if interval reached)
                if self._measurement_count >= self.config.db_save_interval_reads:
                    if self.storage.save_sensor_readings(self._sensor_data_buffer):
                        logger.info(f"Saved {len(self._sensor_data_buffer)} readings to storage.")
                        self._sensor_data_buffer = []
                        self._measurement_count = 0
                    else:
                        logger.warning("Failed to save readings to storage. Buffer retained.")
                        # Keep buffer, maybe add size limit later

                # 6. Publish Data
                if self.publisher.is_connected():
                    pub_sensor_ok = self.publisher.publish_sensor_data(sensor_data)
                    pub_info_ok = self.publisher.publish_info_data(sys_info)
                    if pub_sensor_ok and pub_info_ok:
                         logger.info(f"Published: T={sensor_data.temperature} H={sensor_data.humidity} L={sensor_data.light}")
                    else:
                         logger.warning("Failed to publish one or more messages.")
                else:
                    logger.debug("Publisher not connected, skipping publish.")
                    # Attempt connection on next publisher interaction implicitly

                # 7. Calculate Sleep Time
                elapsed_time = time.monotonic() - loop_start_time
                sleep_time = max(0, self.config.read_interval_seconds - elapsed_time)

                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    logger.warning(f"Main loop took {elapsed_time:.2f}s, longer than interval {self.config.read_interval_seconds}s.")

            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received. Stopping...")
                self._running = False
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                logger.info("Waiting 10 seconds before retrying...")
                time.sleep(10) # Avoid rapid crash loops

        self.shutdown()

    def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down Sensor Monitoring Service...")
        self._running = False

        # Save any remaining data
        if self._sensor_data_buffer:
            logger.info(f"Saving remaining {len(self._sensor_data_buffer)} readings before exiting.")
            self.storage.save_sensor_readings(self._sensor_data_buffer)

        # Disconnect publisher
        try:
            self.publisher.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting publisher: {e}", exc_info=True)

        # Stop admin listener
        try:
            if self.admin_listener:
                self.admin_listener.stop_listening()
        except Exception as e:
            logger.error(f"Error stopping admin listener: {e}", exc_info=True)

        # Cleanup sensors
        try:
            self.sensor_reader.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up sensor reader: {e}", exc_info=True)

        logger.info("Shutdown complete.")

