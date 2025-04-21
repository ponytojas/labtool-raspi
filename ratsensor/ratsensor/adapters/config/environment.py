import os
import logging
from dotenv import load_dotenv
from ratsensor.core.domain import AppConfig
from ratsensor.core.ports import ConfigurationProvider

logger = logging.getLogger(__name__)

class EnvironmentConfigProvider(ConfigurationProvider):
    def __init__(self, env_file_path: str = "/etc/ratsensor/mqtt_config.env"):
        self.env_file_path = env_file_path
        self._config = None

    def _load_env(self):
        try:
            if os.path.exists(self.env_file_path):
                load_dotenv(self.env_file_path, override=True)
                logger.info(f"Loaded environment variables from {self.env_file_path}")
            else:
                logger.warning(f"Environment file not found at {self.env_file_path}, using system environment.")
        except Exception as e:
            logger.error(f"Error loading environment file {self.env_file_path}: {e}")

    def get_config(self) -> AppConfig:
        if self._config is None:
            self._load_env()
            try:
                # Helper to get env var with type casting and default
                def get_env(key, default, cast_type=str):
                    value = os.environ.get(key)
                    if value is None:
                        return default
                    try:
                        return cast_type(value)
                    except ValueError:
                        logger.warning(f"Invalid value for {key}: '{value}'. Using default: {default}")
                        return default

                def get_bool_env(key, default):
                    value = os.environ.get(key, str(default)).lower()
                    return value in ('true', '1', 't', 'yes', 'y')

                # Determine simulation mode early
                hw_available = True
                try:
                    import Adafruit_DHT
                    import smbus2
                    import psutil
                except ImportError as e:
                    hw_available = False
                    logger.error(f"Failed to import hardware libraries: {e}")

                sim_mode_env = get_bool_env('SIMULATION_MODE', False)
                simulation_mode = sim_mode_env or not hw_available
                if simulation_mode and not sim_mode_env:
                     logger.warning("Hardware libraries missing or failed import, forcing SIMULATION MODE.")
                elif simulation_mode:
                     logger.info("SIMULATION MODE enabled via environment variable.")


                self._config = AppConfig(
                    read_interval_seconds=get_env('READ_INTERVAL_SECONDS', 30, int),
                    db_save_interval_reads=get_env('DB_SAVE_INTERVAL_READS', 5, int),
                    mqtt_broker=get_env('MQTT_BROKER', 'localhost'),
                    mqtt_port=get_env('MQTT_PORT', 1883, int),
                    mqtt_user=get_env('MQTT_USER', None),
                    mqtt_pass=get_env('MQTT_PASS', None),
                    mqtt_sensor_topic_template=get_env('MQTT_SENSOR_TOPIC_TEMPLATE', 'sensor/{}'),
                    mqtt_info_topic_template=get_env('MQTT_INFO_TOPIC_TEMPLATE', 'info/{}'),
                    mqtt_admin_topic_template=get_env('ADMIN_TOPIC', None), # e.g., "admin/{}"
                    listen_for_admin=get_bool_env('LISTEN_FOR_ADMIN_COMMANDS', False),
                    mqtt_initial_retry_delay=get_env('MQTT_INITIAL_RETRY_DELAY', 15, int),
                    mqtt_max_retry_delay=get_env('MQTT_MAX_RETRY_DELAY', 300, int),
                    mqtt_retry_backoff_factor=get_env('MQTT_RETRY_BACKOFF_FACTOR', 2.0, float),
                    device_id_file=get_env('DEVICE_ID_FILE', '/etc/ratsensor/device_id.json'),
                    database_file=get_env('DATABASE_FILE', '/var/lib/ratsensor/sensor_data.db'),
                    log_file=get_env('LOG_FILE', '/var/log/ratsensor/ratsensor.log'),
                    simulation_mode=simulation_mode,
                    dht_pin=get_env('DHT_PIN', 14, int),
                    i2c_bus_number=get_env('I2C_BUS_NUMBER', 1, int),
                )
            except Exception as e:
                 logger.error(f"Error parsing configuration: {e}", exc_info=True)
                 # Return default config on error to allow potential startup
                 self._config = AppConfig(simulation_mode=True) # Force sim mode if config fails
        return self._config

