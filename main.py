#!/usr/bin/env python3
import os
import time
import uuid
import json
import logging
import random
from datetime import datetime
import paho.mqtt.client as mqtt
from dotenv import load_dotenv  # Added dotenv import

# Import these libraries but don't require them for testing
try:
    import Adafruit_DHT
    import smbus2
    import psutil
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False
    print("Running in simulation mode - generating fake data")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/var/log/ratsensor.log", mode='a'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("RatSensor")

# Load environment variables from the specified path
ENV_FILE = "/etc/ratsensor/mqtt_config.env"
load_dotenv(ENV_FILE)
logger.info(f"Loaded environment variables from {ENV_FILE}")

# Constants
CONFIG_FILE = "/etc/ratsensor/device_id.json"
SENSOR_TOPIC = "sensor/{}"
INFO_TOPIC = "info/{}"
INTERVAL = 30  # seconds
SIMULATION_MODE = os.environ.get('SIMULATION_MODE', 'False').lower() in ('true', '1', 't') or not HARDWARE_AVAILABLE

# Set simulation parameters
TEMP_BASE = 23.5    # Base temperature in °C
HUMID_BASE = 55.0   # Base humidity %
LIGHT_BASE = 8500   # Base light level

def get_device_id():
    """Generate a unique device ID or retrieve existing one."""
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
                return data.get('device_id')
        
        # Generate new ID if file doesn't exist
        device_id = str(uuid.uuid4())
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'device_id': device_id}, f)
        
        return device_id
    except Exception as e:
        logger.error(f"Error managing device ID: {e}")
        # Fallback to a temporary ID if there's an error
        return f"temp-{uuid.uuid4()}"


def read_dht22_fake():
    """Generate fake temperature and humidity data with small variations."""
    # Add some random variation to the base values
    temperature = TEMP_BASE + random.uniform(-1.5, 1.5)
    # Higher temperature slightly increases humidity
    temp_effect = 0.2 * (temperature - TEMP_BASE)
    humidity = HUMID_BASE + random.uniform(-5.0, 5.0) + temp_effect
    
    # Add time-of-day effect (warmer in afternoon, higher humidity in morning)
    hour = datetime.now().hour
    time_temp_effect = 2 * math.sin((hour - 6) * math.pi / 12)
    time_humid_effect = -1 * math.sin((hour - 9) * math.pi / 12)
    
    temperature += time_temp_effect
    humidity += time_humid_effect
    
    # Ensure values are within realistic ranges
    temperature = max(min(temperature, 32.0), 18.0)
    humidity = max(min(humidity, 95.0), 35.0)
    
    return {
        "temperature": round(temperature, 1),
        "humidity": round(humidity, 1)
    }


def read_dht22(pin=4):
    """Read temperature and humidity from DHT22 sensor."""
    if SIMULATION_MODE:
        return read_dht22_fake()
        
    try:
        humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, pin)
        if humidity is not None and temperature is not None:
            return {
                "temperature": round(temperature, 1),
                "humidity": round(humidity, 1)
            }
        else:
            logger.warning("Failed to get reading from DHT22 sensor")
            return {"temperature": None, "humidity": None}
    except Exception as e:
        logger.error(f"DHT22 sensor error: {e}")
        return {"temperature": None, "humidity": None}


def read_ltr390_fake():
    """Generate fake light sensor data."""
    hour = datetime.now().hour
    
    # Generate a realistic day/night cycle
    # Peak at noon (hour 12), lowest at midnight (hour 0)
    time_factor = math.sin(hour * math.pi / 12) if hour <= 12 else math.sin((24 - hour) * math.pi / 12)
    
    # Scale the light level based on time of day
    light_level = int(LIGHT_BASE * time_factor) + random.randint(-500, 500)
    
    # Add some random noise
    light_level = max(0, light_level)  # Can't go below 0
    
    return {"light": light_level}


def init_ltr390(bus):
    """Initialize the LTR390 light sensor."""
    if SIMULATION_MODE:
        return True
        
    try:
        # Set to ALS mode (Ambient Light Sensing) with gain=3
        bus.write_byte_data(LTR390_ADDR, LTR390_MAIN_CTRL, 0x02)
        time.sleep(0.1)
        return True
    except Exception as e:
        logger.error(f"Error initializing LTR390: {e}")
        return False


def read_ltr390(bus):
    """Read light levels from LTR390 sensor."""
    if SIMULATION_MODE:
        return read_ltr390_fake()
        
    try:
        # Read 3 bytes of ALS data
        data_0 = bus.read_byte_data(LTR390_ADDR, LTR390_ALS_DATA_0)
        data_1 = bus.read_byte_data(LTR390_ADDR, LTR390_ALS_DATA_1)
        data_2 = bus.read_byte_data(LTR390_ADDR, LTR390_ALS_DATA_2)
        
        # Combine bytes into a light value (20 bits used)
        light = ((data_2 & 0x0F) << 16) | (data_1 << 8) | data_0
        
        return {"light": light}
    except Exception as e:
        logger.error(f"Error reading LTR390: {e}")
        return {"light": None}


def get_system_info():
    """Gather system information metrics."""
    try:
        # Get uptime in seconds
        uptime = time.time() - psutil.boot_time()
        
        return {
            "disk_percent": round(psutil.disk_usage('/').percent, 1),
            "memory_percent": round(psutil.virtual_memory().percent, 1),
            "cpu_percent": round(psutil.cpu_percent(interval=1), 1),
            "uptime_seconds": int(uptime),
            "uptime_human": str(datetime.utcfromtimestamp(uptime).strftime('%d days %H:%M:%S')).replace('00 days ', '')
        }
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return {
            "disk_percent": None,
            "memory_percent": None,
            "cpu_percent": None,
            "uptime_seconds": None,
            "uptime_human": None
        }


def setup_mqtt():
    """Configure and connect to MQTT broker using environment variables."""
    try:
        # Get MQTT configuration from environment variables loaded via dotenv
        mqtt_broker_url = os.environ.get('MQTT_BROKER', 'localhost')
        mqtt_port = int(os.environ.get('MQTT_PORT', '1883'))
        mqtt_user = os.environ.get('MQTT_USER')
        mqtt_pass = os.environ.get('MQTT_PASS')
        
        # Handle URL format (tcp://hostname:port)
        if mqtt_broker_url.startswith('tcp://'):
            # Extract just the hostname part
            mqtt_broker = mqtt_broker_url.replace('tcp://', '').split(':')[0]
            # If port is included in the URL, use that instead
            if ':' in mqtt_broker_url.replace('tcp://', ''):
                mqtt_port = int(mqtt_broker_url.split(':')[-1])
        else:
            mqtt_broker = mqtt_broker_url
        
        logger.info(f"Attempting to connect to MQTT broker at {mqtt_broker}:{mqtt_port}")
        
        # Setup MQTT client with new API version
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        
        # Set username and password if provided
        if mqtt_user and mqtt_pass:
            client.username_pw_set(mqtt_user, mqtt_pass)
            logger.info("Using MQTT authentication")
        
        # Connect to the broker
        client.connect(mqtt_broker, mqtt_port, 60)
        client.loop_start()
        
        logger.info(f"Successfully connected to MQTT broker at {mqtt_broker}:{mqtt_port}")
        return client
    except ConnectionRefusedError:
        logger.error(f"Connection refused to MQTT broker at {mqtt_broker}:{mqtt_port}. Is the broker running?")
        return None
    except Exception as e:
        logger.error(f"MQTT connection error: {e}")
        return None
def main():
    """Main function to read sensors and publish data."""
    # Import math here to avoid dependency issues in simulation mode
    global math
    import math
    
    # Get unique device ID
    device_id = get_device_id()
    logger.info(f"Starting sensor monitoring with device ID: {device_id}")
    
    if SIMULATION_MODE:
        logger.info("Running in SIMULATION MODE - generating fake sensor data")
    
    # Set up MQTT client
    mqtt_client = setup_mqtt()
    if not mqtt_client:
        logger.error("Failed to set up MQTT. Exiting.")
        return
    
    # Configure sensor topics
    sensor_topic = SENSOR_TOPIC.format(device_id)
    info_topic = INFO_TOPIC.format(device_id)
    
    # Initialize I2C bus for LTR390 (if not in simulation mode)
    i2c_bus = None
    if not SIMULATION_MODE:
        try:
            i2c_bus = smbus2.SMBus(1)  # Use bus 1 for Raspberry Pi
            ltr390_initialized = init_ltr390(i2c_bus)
            if not ltr390_initialized:
                logger.warning("LTR390 initialization failed")
        except Exception as e:
            logger.error(f"I2C bus initialization failed: {e}")
    
    # Main loop
    while True:
        try:
            # Get current timestamp
            timestamp = datetime.now().isoformat() + 'Z'
            
            # Read sensor data
            dht_data = read_dht22()
            
            # Get light data
            light_data = read_ltr390(i2c_bus) if i2c_bus else read_ltr390_fake()
            
            # Combine sensor data
            sensor_data = {
                "timestamp": timestamp,
                "device_id": device_id,
                **dht_data,
                **light_data
            }
            
            # Get system information
            sys_info = {
                "timestamp": timestamp,
                "device_id": device_id,
                **get_system_info()
            }
            
            # Publish data if MQTT is available
            if mqtt_client:
                mqtt_client.publish(sensor_topic, json.dumps(sensor_data))
                mqtt_client.publish(info_topic, json.dumps(sys_info))
                logger.info(f"Published data: Temp: {dht_data.get('temperature')}°C, "
                           f"Humidity: {dht_data.get('humidity')}%, "
                           f"Light: {light_data.get('light')}")
            else:
                logger.warning("MQTT client unavailable, data not published")
                # Try to reconnect
                mqtt_client = setup_mqtt()
            
            # Wait for next interval
            time.sleep(INTERVAL)
            
        except KeyboardInterrupt:
            logger.info("Stopping sensor monitoring")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            time.sleep(5)  # Wait before retrying if there's an error


if __name__ == "__main__":
    main()