#!/usr/bin/env python3
import os
import sys
import time
import uuid
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import random
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
import sqlite3

try:
    import Adafruit_DHT
    import smbus2
    import psutil
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False
    print("Running in simulation mode - generating fake data")

log_file = "/var/log/ratsensor.log"
logger = logging.getLogger("RatSensor")
logger.setLevel(logging.INFO)

file_handler = TimedRotatingFileHandler(
    filename=log_file, when='D', interval=7, backupCount=2
)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(stream_handler)

ENV_FILE = "/etc/ratsensor/mqtt_config.env"
try:
    if os.path.exists(ENV_FILE):
        load_dotenv(ENV_FILE)
        logger.info(f"Loaded environment variables from {ENV_FILE}")
    else:
        logger.warning(f"Environment file not found at {ENV_FILE}, using defaults/system environment.")
except Exception as e:
    logger.error(f"Error loading environment file {ENV_FILE}: {e}")


CONFIG_FILE = "/etc/ratsensor/device_id.json"
DATABASE_FILE = "/var/lib/ratsensor/sensor_data.db"
DATABASE_SAVE_INTERVAL = 5
SENSOR_TOPIC = "sensor/{}"
INFO_TOPIC = "info/{}"
INTERVAL = 30
SIMULATION_MODE = os.environ.get('SIMULATION_MODE', 'False').lower() in ('true', '1', 't') or not HARDWARE_AVAILABLE

INITIAL_MQTT_RETRY_DELAY = 15
MAX_MQTT_RETRY_DELAY = 300
MQTT_RETRY_BACKOFF_FACTOR = 2

TEMP_BASE = 23.5
HUMID_BASE = 55.0
LIGHT_BASE = 8500

mqtt_connected_flag = False

def init_database():
    db_dir = os.path.dirname(DATABASE_FILE)
    try:
        os.makedirs(db_dir, exist_ok=True)
        logger.info(f"Ensured database directory exists: {db_dir}")
    except OSError as e:
        logger.error(f"Error creating database directory {db_dir}: {e}. Check permissions.")
        return False

    try:
        conn = sqlite3.connect(DATABASE_FILE, timeout=10)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sensor_readings (
                timestamp TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                temperature REAL,
                humidity REAL,
                light INTEGER
            )
        ''')
        conn.commit()
        conn.close()
        logger.info(f"Database initialized successfully at {DATABASE_FILE}")
        return True
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        return False

def save_data_to_db(data_buffer):
    if not data_buffer:
        return
    try:
        conn = sqlite3.connect(DATABASE_FILE, timeout=10)
        cursor = conn.cursor()
        insert_data = [
            (rec.get("timestamp"), rec.get("device_id"), rec.get("temperature"),
             rec.get("humidity"), rec.get("light"))
            for rec in data_buffer
        ]
        cursor.executemany('''
            INSERT OR IGNORE INTO sensor_readings
            (timestamp, device_id, temperature, humidity, light)
            VALUES (?, ?, ?, ?, ?)
        ''', insert_data)
        conn.commit()
        conn.close()
        logger.info(f"Successfully saved {len(data_buffer)} records to database.")
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            logger.warning(f"Database is locked, could not save data this cycle: {e}")
        else:
            logger.error(f"Database operational error during save: {e}")
    except sqlite3.Error as e:
        logger.error(f"Failed to save data to database: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during database save: {e}", exc_info=True)

def get_device_id():
    config_dir = os.path.dirname(CONFIG_FILE)
    try:
        os.makedirs(config_dir, exist_ok=True)
    except OSError as e:
         logger.error(f"Error creating config directory {config_dir}: {e}. Check permissions.")
         temp_id = f"temp-{uuid.uuid4()}"
         logger.warning(f"Falling back to temporary device ID: {temp_id}")
         return temp_id

    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
                device_id = data.get('device_id')
                if device_id:
                    logger.info(f"Retrieved existing device ID: {device_id}")
                    return device_id
                else:
                    logger.warning(f"device_id key missing in {CONFIG_FILE}. Generating new one.")

        device_id = str(uuid.uuid4())
        logger.info(f"Generated new device ID: {device_id}")
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'device_id': device_id}, f)
            logger.info(f"Saved new device ID to {CONFIG_FILE}")
        return device_id

    except (IOError, json.JSONDecodeError, OSError) as e:
        logger.error(f"Error managing device ID file {CONFIG_FILE}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error getting device ID: {e}", exc_info=True)

    temp_id = f"temp-{uuid.uuid4()}"
    logger.warning(f"Falling back to temporary device ID: {temp_id}")
    return temp_id

def read_dht22_fake():
    import math
    temperature = TEMP_BASE + random.uniform(-1.5, 1.5)
    temp_effect = 0.2 * (temperature - TEMP_BASE)
    humidity = HUMID_BASE + random.uniform(-5.0, 5.0) + temp_effect
    hour = datetime.now().hour
    time_temp_effect = 1.5 * math.sin((hour - 9) * math.pi / 12)
    time_humid_effect = 5.0 * math.sin((hour - 3) * math.pi / 12)
    temperature = max(min(temperature + time_temp_effect, 32.0), 18.0)
    humidity = max(min(humidity + time_humid_effect, 95.0), 35.0)
    return {"temperature": round(temperature, 1), "humidity": round(humidity, 1)}

def read_dht22(pin=4):
    if SIMULATION_MODE or not HARDWARE_AVAILABLE:
        return read_dht22_fake()
    try:
        humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, pin)
        if humidity is not None and temperature is not None:
            return {"temperature": round(temperature, 1), "humidity": round(humidity, 1)}
        else:
            logger.warning("DHT22: Failed to get reading (read_retry returned None)")
            return {"temperature": None, "humidity": None}
    except RuntimeError as e:
        logger.warning(f"DHT22: Sensor runtime error: {e}")
        return {"temperature": None, "humidity": None}
    except Exception as e:
        logger.error(f"DHT22: Unexpected sensor error", exc_info=True)
        return {"temperature": None, "humidity": None}

def read_ltr390_fake():
    import math
    hour = datetime.now().hour
    time_factor = math.sin((hour - 7) * math.pi / 12)
    normalized_factor = (time_factor + 1) / 2
    light_level = max(0, int(LIGHT_BASE * normalized_factor) + random.randint(-500, 500))
    return {"light": light_level}

if HARDWARE_AVAILABLE:
    try:
        import smbus2
        LTR390_ADDR = 0x53
        LTR390_MAIN_CTRL = 0x00
        LTR390_ALS_CONF = 0x05
        LTR390_ALS_DATA_0 = 0x0D
    except ImportError:
        logger.warning("smbus2 library not found, LTR390 hardware unavailable.")
        HARDWARE_AVAILABLE = False

def init_ltr390(bus):
    if SIMULATION_MODE or not HARDWARE_AVAILABLE:
        logger.debug("LTR390 init skipped (Sim/No HW)")
        return True
    if not bus:
        logger.error("LTR390 init failed: I2C bus not provided.")
        return False
    try:
        bus.write_byte_data(LTR390_ADDR, LTR390_ALS_CONF, 0x22)
        bus.write_byte_data(LTR390_ADDR, LTR390_MAIN_CTRL, 0x02)
        time.sleep(0.1)
        logger.info("LTR390 initialized successfully.")
        return True
    except OSError as e:
        logger.error(f"LTR390: I2C communication error during init: {e}")
        return False
    except Exception as e:
        logger.error(f"LTR390: Unexpected error during init", exc_info=True)
        return False

def read_ltr390(bus):
    if SIMULATION_MODE or not HARDWARE_AVAILABLE:
        return read_ltr390_fake()
    if not bus:
       logger.warning("LTR390 read failed: I2C bus not available.")
       return {"light": None}
    try:
        data = bus.read_i2c_block_data(LTR390_ADDR, LTR390_ALS_DATA_0, 3)
        light = data[0] | (data[1] << 8) | ((data[2] & 0x0F) << 16)
        return {"light": light}
    except OSError as e:
        logger.error(f"LTR390: I2C communication error during read: {e}")
        return {"light": None}
    except Exception as e:
        logger.error(f"LTR390: Unexpected error during read", exc_info=True)
        return {"light": None}

def get_system_info():
    if not HARDWARE_AVAILABLE or 'psutil' not in sys.modules:
         logger.debug("psutil not available, cannot get system info.")
         return {"disk_percent": None, "memory_percent": None, "cpu_percent": None,
                 "uptime_seconds": None, "uptime_human": None}
    try:
        boot_time = psutil.boot_time()
        current_time = time.time()
        uptime_seconds = current_time - boot_time
        delta = timedelta(seconds=uptime_seconds)
        uptime_human = str(delta).split('.')[0]

        return {
            "disk_percent": round(psutil.disk_usage('/').percent, 1),
            "memory_percent": round(psutil.virtual_memory().percent, 1),
            "cpu_percent": round(psutil.cpu_percent(interval=0.5), 1),
            "uptime_seconds": int(uptime_seconds),
            "uptime_human": uptime_human
        }
    except Exception as e:
        logger.error(f"Error getting system info", exc_info=True)
        return {"disk_percent": None, "memory_percent": None, "cpu_percent": None,
                "uptime_seconds": None, "uptime_human": None}


def on_connect(client, userdata, flags, rc, properties=None):
    global mqtt_connected_flag
    if rc == 0:
        logger.info(f"MQTT: Successfully connected to broker (rc={rc})")
        mqtt_connected_flag = True
        admin_topic = userdata.get('admin_topic')
        if admin_topic:
            try:
                result, mid = client.subscribe(admin_topic)
                if result == mqtt.MQTT_ERR_SUCCESS:
                    logger.info(f"MQTT: Subscribed to admin topic: {admin_topic}")
                else:
                    logger.warning(f"MQTT: Failed to subscribe to admin topic {admin_topic} (Error code: {result})")
            except Exception as e:
                logger.error(f"MQTT: Error during subscription to {admin_topic}", exc_info=True)
    else:
        logger.error(f"MQTT: Connection failed with result code: {rc}. Check broker/credentials/network.")
        mqtt_connected_flag = False

def on_disconnect(client, userdata, rc, properties=None):
    global mqtt_connected_flag
    logger.warning(f"MQTT: Disconnected from broker (rc={rc}). Paho client will attempt auto-reconnect.")
    mqtt_connected_flag = False

def on_message(client, userdata, msg):
    admin_topic = userdata.get('admin_topic')
    if msg.topic == admin_topic:
        try:
            payload = msg.payload.decode().strip().lower()
            logger.warning(f"MQTT: Received command on admin topic '{msg.topic}': {payload}")
            if payload == "reboot":
                logger.warning("Executing reboot command...")
                time.sleep(1)
                os.system('sudo reboot')
            else:
                logger.warning(f"MQTT: Unknown admin command received: {payload}")
        except Exception as e:
            logger.error(f"MQTT: Error processing admin command", exc_info=True)

def setup_mqtt(device_id):
    global mqtt_connected_flag
    mqtt_broker = None
    mqtt_port = 1883
    client = None

    try:
        mqtt_broker_url = os.environ.get('MQTT_BROKER', 'localhost')
        mqtt_port_str = os.environ.get('MQTT_PORT', '1883')
        mqtt_user = os.environ.get('MQTT_USER')
        mqtt_pass = os.environ.get('MQTT_PASS')
        listen_for_admin = os.environ.get('LISTEN_FOR_ADMIN_COMMANDS', 'False').lower() in ('true', '1', 't')
        admin_topic_base = os.environ.get('ADMIN_TOPIC')

        admin_topic = None
        if listen_for_admin and admin_topic_base:
             if "{}" in admin_topic_base:
                 admin_topic = admin_topic_base.format(device_id)
             else:
                 admin_topic = admin_topic_base
             logger.info(f"MQTT: Admin command listening enabled on topic: {admin_topic}")
        else:
            logger.info("MQTT: Admin command listening disabled.")

        if mqtt_broker_url.startswith('tcp://'):
            parts = mqtt_broker_url.replace('tcp://', '').split(':')
            mqtt_broker = parts[0]
            if len(parts) > 1:
                try: mqtt_port = int(parts[1])
                except ValueError: logger.error(f"Invalid port in MQTT_BROKER URL: {parts[1]}. Using default {mqtt_port}.")
            else:
                try: mqtt_port = int(mqtt_port_str)
                except ValueError: logger.error(f"Invalid MQTT_PORT value: {mqtt_port_str}. Using default {mqtt_port}.")
        else:
            mqtt_broker = mqtt_broker_url
            try: mqtt_port = int(mqtt_port_str)
            except ValueError: logger.error(f"Invalid MQTT_PORT value: {mqtt_port_str}. Using default {mqtt_port}.")

        if not mqtt_broker:
            logger.error("MQTT Broker address is not configured. Cannot connect.")
            return None

        logger.info(f"MQTT: Attempting to connect to {mqtt_broker}:{mqtt_port}")

        client_id = f"ratsensor-{device_id}-{random.randint(100, 999)}"
        logger.debug(f"MQTT: Using Client ID: {client_id}")

        userdata = {'admin_topic': admin_topic}

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, userdata=userdata)
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        if admin_topic:
            client.on_message = on_message

        if mqtt_user and mqtt_pass:
            client.username_pw_set(mqtt_user, mqtt_pass)
            logger.info("MQTT: Using authentication.")

        mqtt_connected_flag = False
        client.connect(mqtt_broker, mqtt_port, 60)
        client.loop_start()

        time.sleep(2)

        if mqtt_connected_flag:
             return client
        else:
            logger.warning("MQTT: Initial connection attempt failed or timed out.")
            client.loop_stop()
            return None

    except ConnectionRefusedError:
        logger.error(f"MQTT: Connection refused by broker at {mqtt_broker}:{mqtt_port}. Check broker status and firewall.")
        mqtt_connected_flag = False
        if client and client.is_connected(): client.loop_stop()
        return None
    except OSError as e:
        logger.error(f"MQTT: Network error connecting to {mqtt_broker}:{mqtt_port}: {e}")
        mqtt_connected_flag = False
        if client and client.is_connected(): client.loop_stop()
        return None
    except Exception as e:
        logger.error(f"MQTT: Unexpected setup error", exc_info=True)
        mqtt_connected_flag = False
        if client and client.is_connected(): client.loop_stop()
        return None

def main():
    global mqtt_connected_flag
    device_id = get_device_id()
    if not device_id or device_id.startswith("temp-"):
        logger.critical("Failed to get a persistent device ID. Exiting.")
        return

    logger.info(f"Starting RatSensor monitoring with device ID: {device_id}")

    global SIMULATION_MODE
    if SIMULATION_MODE:
        logger.info("Running in SIMULATION MODE (Env var or missing libraries)")
    elif not HARDWARE_AVAILABLE:
        logger.warning("Hardware libraries missing, forcing SIMULATION MODE.")
        SIMULATION_MODE = True

    if not init_database():
        logger.warning("Database initialization failed. Data will not be saved locally.")

    sensor_topic = SENSOR_TOPIC.format(device_id)
    info_topic = INFO_TOPIC.format(device_id)

    i2c_bus = None
    if not SIMULATION_MODE and HARDWARE_AVAILABLE:
        try:
            import smbus2
            i2c_bus = smbus2.SMBus(1)
            logger.info("I2C bus 1 opened successfully.")
            if not init_ltr390(i2c_bus):
                 logger.warning("LTR390 initialization failed, light readings may be affected.")
        except FileNotFoundError:
            logger.error("I2C bus 1 not found. Is I2C enabled (raspi-config)? Forcing SIMULATION MODE.")
            SIMULATION_MODE = True
            HARDWARE_AVAILABLE = False
        except ImportError:
             logger.error("smbus2 library not found, cannot use I2C. Forcing SIMULATION MODE.")
             SIMULATION_MODE = True
             HARDWARE_AVAILABLE = False
        except Exception as e:
            logger.error(f"I2C bus initialization failed", exc_info=True)
            i2c_bus = None

    mqtt_client = None
    current_mqtt_retry_delay = INITIAL_MQTT_RETRY_DELAY
    last_mqtt_attempt_time = time.monotonic() - current_mqtt_retry_delay

    measurement_count = 0
    sensor_data_buffer = []

    logger.info(f"Starting main loop. Reading sensors every {INTERVAL} seconds.")
    while True:
        main_loop_start_time = time.monotonic()

        try:
            if not mqtt_client or not mqtt_connected_flag:
                if time.monotonic() - last_mqtt_attempt_time >= current_mqtt_retry_delay:
                    logger.info(f"Attempting to establish MQTT connection (Retry delay: {current_mqtt_retry_delay}s)...")
                    last_mqtt_attempt_time = time.monotonic()

                    if mqtt_client:
                        try:
                            mqtt_client.loop_stop()
                        except: pass

                    mqtt_client = setup_mqtt(device_id)

                    if not mqtt_client or not mqtt_connected_flag:
                        logger.warning("MQTT connection attempt failed.")
                        current_mqtt_retry_delay = min(
                            current_mqtt_retry_delay * MQTT_RETRY_BACKOFF_FACTOR,
                            MAX_MQTT_RETRY_DELAY
                        )
                        current_mqtt_retry_delay += random.uniform(0, 5)
                    else:
                        logger.info("MQTT connection established successfully.")
                        current_mqtt_retry_delay = INITIAL_MQTT_RETRY_DELAY

            timestamp_now = datetime.utcnow()
            timestamp_iso = timestamp_now.isoformat() + 'Z'
            dht_data = read_dht22()
            light_data = read_ltr390(i2c_bus)

            current_sensor_data = {
                "timestamp": timestamp_iso, "device_id": device_id,
                "temperature": dht_data.get("temperature"),
                "humidity": dht_data.get("humidity"),
                "light": light_data.get("light")
            }

            sensor_data_buffer.append(current_sensor_data)
            measurement_count += 1
            if measurement_count >= DATABASE_SAVE_INTERVAL:
                save_data_to_db(sensor_data_buffer)
                sensor_data_buffer = []
                measurement_count = 0

            sys_info_data = get_system_info()
            sys_info_payload = {
                "timestamp": timestamp_iso, "device_id": device_id, **sys_info_data
            }

            if mqtt_client and mqtt_connected_flag:
                try:
                    sensor_result = mqtt_client.publish(sensor_topic, json.dumps(current_sensor_data), qos=0)
                    info_result = mqtt_client.publish(info_topic, json.dumps(sys_info_payload), qos=0)
                    logger.info(f"Published: T={current_sensor_data['temperature']} H={current_sensor_data['humidity']} L={current_sensor_data['light']}")
                except Exception as pub_e:
                    logger.error(f"MQTT Error during publish: {pub_e}")
                    mqtt_connected_flag = False
            else:
                logger.debug("MQTT client not connected, skipping publish.")

            elapsed_time = time.monotonic() - main_loop_start_time
            sleep_time = max(0, INTERVAL - elapsed_time)
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                 logger.warning(f"Main loop took {elapsed_time:.2f}s, longer than interval {INTERVAL}s.")


        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Stopping sensor monitoring...")
            if sensor_data_buffer:
                logger.info(f"Saving remaining {len(sensor_data_buffer)} records before exiting.")
                save_data_to_db(sensor_data_buffer)
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop", exc_info=True)
            logger.info("Waiting 10 seconds before retrying...")
            time.sleep(10)

    logger.info("Exiting RatSensor script.")
    if mqtt_client:
        logger.info("Stopping MQTT client loop.")
        mqtt_client.loop_stop()
        logger.info("Disconnecting MQTT client.")
        mqtt_client.disconnect()
    if i2c_bus:
        try:
            logger.info("Closing I2C bus.")
            i2c_bus.close()
        except Exception as e:
            logger.error(f"Error closing I2C bus: {e}")
    logger.info("Cleanup complete.")


if __name__ == "__main__":
    if 'psutil' not in sys.modules and HARDWARE_AVAILABLE:
        try:
            import psutil
        except ImportError:
            logger.warning("psutil library not found, system info unavailable.")

    main()