#!/usr/bin/env python3

import sys
import os
import logging
import signal
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

# --- Add project root to Python path ---
# This allows importing 'ratsensor' even when running main.py directly
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# ---

from ratsensor.core.service import SensorMonitoringService
from ratsensor.core.ports import SensorReader, SystemInfoReader # For type hinting
from ratsensor.adapters.config.environment import EnvironmentConfigProvider
from ratsensor.adapters.identity.file import FileDeviceIdentityProvider
from ratsensor.adapters.storage.sqlite import SQLiteStorageAdapter
from ratsensor.adapters.sensor.simulated import SimulatedSensorReader
from ratsensor.adapters.system_info.simulated import SimulatedSystemInfoReader
from ratsensor.adapters.command.os_command import OSCommandExecutor
from ratsensor.adapters.publisher.mqtt import MqttAdapter

# Import hardware adapters conditionally
try:
    from ratsensor.adapters.sensor.hardware import HardwareSensorReader, HARDWARE_AVAILABLE
except ImportError:
    HARDWARE_AVAILABLE = False # Ensure it's defined even if import fails
    HardwareSensorReader = None # Placeholder

try:
    from ratsensor.adapters.system_info.psutil_adapter import PsutilSystemInfoReader, PSUTIL_AVAILABLE
except ImportError:
    PSUTIL_AVAILABLE = False
    PsutilSystemInfoReader = None # Placeholder


# --- Global Logger Setup ---
# Configure logging early, before loading other modules that might log
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ratsensor") # Get root logger for the package
logger.setLevel(logging.INFO) # Set default level

# Console Handler
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)
logger.addHandler(stream_handler)

# File Handler (configured later once config is loaded)
file_handler = None

# --- Global Service Instance ---
# Allows signal handler to access the service for shutdown
monitoring_service: Optional[SensorMonitoringService] = None

def setup_logging(config):
    """Configure file logging based on loaded config."""
    global file_handler
    log_file = config.log_file
    log_dir = os.path.dirname(log_file)
    try:
        os.makedirs(log_dir, exist_ok=True)
        # Timed Rotating File Handler
        # when='D': Rotate daily
        # interval=7: Keep logs for 7 days (creates NAME, NAME.YYYY-MM-DD, etc.)
        # backupCount=2: Keep 2 older files (total 3 files: current + 2 backups)
        # This means logs are kept for 3 * 7 = 21 days (3 weeks)
        file_handler = TimedRotatingFileHandler(
            filename=log_file, when='D', interval=7, backupCount=2, encoding='utf-8'
        )
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)
        logger.info(f"File logging configured to {log_file} (rotate daily, keep 3 weeks)")
    except Exception as e:
        logger.error(f"Failed to configure file logging to {log_file}: {e}", exc_info=True)
        file_handler = None # Ensure it's None if setup fails

def shutdown_handler(signum, frame):
    """Handle termination signals gracefully."""
    logger.warning(f"Received signal {signum}. Initiating graceful shutdown...")
    if monitoring_service:
        # Stop the main loop (if running)
        monitoring_service._running = False
        # Shutdown sequence is called after the loop exits or if it wasn't started
    else:
        logger.warning("Monitoring service not initialized, exiting.")
    # No explicit sys.exit here; let the main thread finish cleanup

def main():
    global monitoring_service
    global file_handler

    # --- 1. Configuration ---
    config_provider = EnvironmentConfigProvider() # Default .env path
    config = config_provider.get_config()

    # --- 2. Setup Logging (with file path from config) ---
    setup_logging(config)
    logger.info(f"Starting RatSensor Service...")
    logger.info(f"Simulation Mode: {config.simulation_mode}")
    if not HARDWARE_AVAILABLE:
        logger.warning("Hardware-specific libraries (Adafruit_DHT, smbus2) not found.")
    if not PSUTIL_AVAILABLE:
        logger.warning("psutil library not found, system info will be simulated or unavailable.")

    # --- 3. Instantiate Adapters ---
    identity_provider = FileDeviceIdentityProvider(config.device_id_file)
    # Get device ID early - needed by some adapters
    device_id = identity_provider.get_device_id()
    if not device_id or device_id.startswith("temp-"):
         logger.critical("Failed to obtain a persistent Device ID. Cannot continue.")
         sys.exit(1)
    logger.info(f"Device ID: {device_id}")


    storage_adapter = SQLiteStorageAdapter(config.database_file)
    command_executor = OSCommandExecutor()

    # Choose Sensor Reader based on simulation mode and availability
    sensor_reader: SensorReader
    if config.simulation_mode:
        logger.info("Using Simulated Sensor Reader.")
        sensor_reader = SimulatedSensorReader(device_id=device_id)
    elif HARDWARE_AVAILABLE and HardwareSensorReader:
        logger.info("Using Hardware Sensor Reader.")
        try:
            sensor_reader = HardwareSensorReader(
                device_id=device_id,
                dht_pin=config.dht_pin,
            )
        except Exception as e:
             logger.error(f"Failed to instantiate HardwareSensorReader: {e}. Falling back to simulation.", exc_info=True)
             sensor_reader = SimulatedSensorReader(device_id=device_id)
             config.simulation_mode = True # Ensure rest of system knows
    else:
        logger.warning("Hardware reader requested but unavailable/failed. Falling back to simulation.")
        sensor_reader = SimulatedSensorReader(device_id=device_id)
        config.simulation_mode = True

    # Choose System Info Reader
    sys_info_reader: SystemInfoReader
    if config.simulation_mode: # Use simulation if sensors are simulated too
        logger.info("Using Simulated System Info Reader.")
        sys_info_reader = SimulatedSystemInfoReader(device_id=device_id)
    elif PSUTIL_AVAILABLE and PsutilSystemInfoReader:
        logger.info("Using Psutil System Info Reader.")
        try:
             sys_info_reader = PsutilSystemInfoReader(device_id=device_id)
        except Exception as e:
             logger.error(f"Failed to instantiate PsutilSystemInfoReader: {e}. Falling back to simulation.", exc_info=True)
             sys_info_reader = SimulatedSystemInfoReader(device_id=device_id)
    else:
        logger.warning("Psutil reader requested but unavailable/failed. Falling back to simulation.")
        sys_info_reader = SimulatedSystemInfoReader(device_id=device_id)


    # MQTT Adapter (handles both publishing and admin listening)
    mqtt_adapter = MqttAdapter(config, device_id)

    # --- 4. Instantiate Core Service ---
    monitoring_service = SensorMonitoringService(
        config=config,
        sensor_reader=sensor_reader,
        sys_info_reader=sys_info_reader,
        publisher=mqtt_adapter, # MQTT adapter acts as publisher
        storage=storage_adapter,
        identity_provider=identity_provider,
        command_executor=command_executor,
        admin_listener=mqtt_adapter if config.listen_for_admin else None # Pass adapter if listening
    )

    # --- 5. Setup Signal Handling for Graceful Shutdown ---
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler) # Handle Ctrl+C

    # --- 6. Start the Service ---
    try:
        # Start MQTT connection management (non-blocking)
        mqtt_adapter.connect()

        # Start admin command listening if enabled (non-blocking)
        if config.listen_for_admin:
            # Pass the service's handler method to the listener adapter
            mqtt_adapter.start_listening(monitoring_service._handle_admin_command)

        # Run the main blocking loop
        monitoring_service.run()

    except Exception as e:
        logger.critical(f"Unhandled exception in main execution: {e}", exc_info=True)
    finally:
        logger.info("Main execution finished or interrupted.")
        # Ensure shutdown sequence runs even if run() exits unexpectedly
        if monitoring_service and not monitoring_service._running: # Check if already shut down
             monitoring_service.shutdown()
        elif not monitoring_service:
             logger.warning("Service was not fully initialized, attempting minimal cleanup.")
             # Manually disconnect MQTT if possible
             try: mqtt_adapter.disconnect()
             except: pass

        # Clean up logging file handler
        if file_handler:
            logger.removeHandler(file_handler)
            file_handler.close()
        logger.info("Application exit.")
        sys.exit(0) # Explicitly exit


if __name__ == "__main__":
    main()
