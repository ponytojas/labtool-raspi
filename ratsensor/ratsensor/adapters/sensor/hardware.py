# ratsensor/adapters/sensor/hardware.py
import logging
import time
from typing import Optional # Keep Optional for type hinting

# Import the new required libraries
try:
    import board # Adafruit Blinka board definition
    import busio # Adafruit Blinka I2C
    import adafruit_ltr390
    import adafruit_dht
    # Use libgpiod if available for adafruit_dht for stability
    # This is often installed with Blinka setup
    USE_LIBGPIOD = True
    HARDWARE_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Hardware libraries (board, busio, adafruit_ltr390, adafruit_dht) not found: {e}. Hardware sensor reader unavailable.")
    HARDWARE_AVAILABLE = False
    # Define dummy classes/constants if import fails
    board = None
    busio = None
    adafruit_ltr390 = None
    adafruit_dht = None
    USE_LIBGPIOD = False
except NotImplementedError as e:
    # This can happen if Blinka is installed but platform is not supported
     logging.warning(f"Hardware platform not supported by Blinka: {e}. Hardware sensor reader unavailable.")
     HARDWARE_AVAILABLE = False
     board = None
     busio = None
     adafruit_ltr390 = None
     adafruit_dht = None
     USE_LIBGPIOD = False


from ratsensor.core.domain import SensorData
from ratsensor.core.ports import SensorReader

logger = logging.getLogger(__name__)


class HardwareSensorReader(SensorReader):
    # Removed i2c_bus_num as busio typically handles the default bus
    def __init__(self, device_id: str, dht_pin: int = 14):
        self._device_id = device_id
        # Store the pin number provided by config
        self.dht_pin_number = dht_pin
        # These will hold the initialized sensor objects
        self.i2c: Optional[busio.I2C] = None
        self.ltr: Optional[adafruit_ltr390.LTR390] = None
        self.dht: Optional[adafruit_dht.DHTBase] = None # Use base class for typing

        if not HARDWARE_AVAILABLE:
            raise RuntimeError("Hardware libraries not available or platform not supported. Cannot instantiate HardwareSensorReader.")
        logger.info("Initialized Hardware Sensor Reader (using Adafruit Blinka/CircuitPython libraries)")

    def initialize(self) -> bool:
        logger.info("Initializing hardware sensors via Blinka/CircuitPython...")
        initialized_ok = True

        # --- Initialize I2C and LTR390 ---
        try:
            # Use Blinka's default SCL and SDA pins
            self.i2c = busio.I2C(board.SCL, board.SDA)
            logger.info("I2C bus initialized successfully.")
            try:
                self.ltr = adafruit_ltr390.LTR390(self.i2c)
                logger.info("LTR390 sensor initialized successfully.")
            except (ValueError, OSError) as e_ltr:
                # ValueError can occur if device not found at address
                logger.error(f"Failed to initialize LTR390 sensor: {e_ltr}")
                self.ltr = None # Ensure it's None if init fails
                initialized_ok = False # Mark initialization as failed
            except Exception as e_ltr_unexpected:
                 logger.error(f"Unexpected error initializing LTR390: {e_ltr_unexpected}", exc_info=True)
                 self.ltr = None
                 initialized_ok = False

        except (RuntimeError, ValueError, OSError) as e_i2c:
             # RuntimeError can happen if I2C is not enabled/available
             logger.error(f"Failed to initialize I2C bus: {e_i2c}. Is I2C enabled?")
             self.i2c = None
             initialized_ok = False # Cannot proceed without I2C for LTR390
        except Exception as e_i2c_unexpected:
             logger.error(f"Unexpected error initializing I2C: {e_i2c_unexpected}", exc_info=True)
             self.i2c = None
             initialized_ok = False

        # --- Initialize DHT22 ---
        try:
            # Get the board pin object using the pin number from config
            # Example: If dht_pin_number is 4, this gets board.D4
            pin_object = getattr(board, f'D{self.dht_pin_number}')
            logger.info(f"Attempting to initialize DHT22 on pin: {pin_object} (GPIO{self.dht_pin_number})")
            # Pass use_pulseio=False for Raspberry Pi (often more reliable)
            # This prevents the OverflowError: unsigned short is greater than maximum
            self.dht = adafruit_dht.DHT22(pin_object, use_pulseio=False)
            logger.info(f"DHT22 sensor initialized successfully on pin D{self.dht_pin_number} (use_pulseio=False).")
        except AttributeError:
            logger.error(f"Invalid DHT pin specified: D{self.dht_pin_number} not found in 'board' module.")
            self.dht = None
            initialized_ok = False
        except RuntimeError as e_dht_rt:
             # Can happen if pin is already in use or other low-level issues
             logger.error(f"Runtime error initializing DHT22: {e_dht_rt}")
             self.dht = None
             initialized_ok = False
        except Exception as e_dht_unexpected:
            logger.error(f"Unexpected error initializing DHT22: {e_dht_unexpected}", exc_info=True)
            self.dht = None
            initialized_ok = False

        if initialized_ok:
             logger.info("Hardware sensor initialization complete.")
        else:
             logger.warning("Hardware sensor initialization failed for one or more sensors.")

        return initialized_ok

    def _read_dht22(self) -> dict:
        if not self.dht:
            # logger.debug("DHT22 read skipped: sensor not initialized.")
            return {"temperature": None, "humidity": None}
        
        # Retry mechanism for DHT22 - these sensors are finicky
        max_retries = 3
        retry_delay = 0.5  # seconds
        
        for attempt in range(max_retries):
            try:
                # Use properties of the adafruit_dht object
                temperature_c = self.dht.temperature
                humidity = self.dht.humidity
                # adafruit_dht automatically retries internally to some extent
                # It will raise RuntimeError if it fails after retries
                if temperature_c is not None and humidity is not None:
                     if attempt > 0:
                         logger.debug(f"DHT22: Successful read on attempt {attempt + 1}")
                     return {"temperature": round(temperature_c, 1), "humidity": round(humidity, 1)}
                else:
                     # This case might be less common with adafruit_dht compared to Adafruit_DHT
                     logger.warning("DHT22: Read returned None values (unexpected for adafruit_dht).")
                     if attempt < max_retries - 1:
                         time.sleep(retry_delay)
                         continue
                     return {"temperature": None, "humidity": None}
            except RuntimeError as e:
                # This is the expected error for read failures with adafruit_dht (checksum errors, etc.)
                if attempt < max_retries - 1:
                    logger.debug(f"DHT22: Attempt {attempt + 1} failed: {e}. Retrying...")
                    time.sleep(retry_delay)
                    continue
                else:
                    # Final attempt failed
                    logger.warning(f"DHT22: Failed to get reading after {max_retries} attempts: {e}")
                    return {"temperature": None, "humidity": None}
            except Exception as e:
                logger.error(f"DHT22: Unexpected sensor error during read", exc_info=True)
                return {"temperature": None, "humidity": None}
        
        # Should not reach here, but just in case
        return {"temperature": None, "humidity": None}

    def _read_ltr390(self) -> dict:
        if not self.ltr:
            # logger.debug("LTR390 read skipped: sensor not initialized.")
            return {"light": None}
        try:
            # Use the .lux property for ambient light reading
            lux_value = self.ltr.lux
            # Note: The working script used ltr.light for ambient_light and ltr.lux for uv_index.
            # ltr.lux is typically the ambient light in Lux.
            # ltr.uvs reads the UV value, and ltr.uvi calculates the UV Index.
            # We'll return Lux here as 'light'. Add UV reading if needed later.
            return {"light": lux_value}
        except (OSError, ValueError) as e:
            # Catch potential I2C communication errors during read
            logger.error(f"LTR390: I2C communication error during read: {e}")
            # Consider if re-initialization is needed or just skip reading
            return {"light": None}
        except Exception as e:
            logger.error(f"LTR390: Unexpected error during read", exc_info=True)
            return {"light": None}

    def read_sensors(self) -> SensorData:
        # This part remains the same, calling the updated internal methods
        dht_data = self._read_dht22()
        light_data = self._read_ltr390()

        # Timestamp and device_id will be set by the core service
        return SensorData(
            timestamp="", # Placeholder
            device_id=self._device_id, # Placeholder
            temperature=dht_data.get("temperature"),
            humidity=dht_data.get("humidity"),
            light=light_data.get("light")
        )

    def cleanup(self) -> None:
        logger.info("Cleaning up hardware sensor resources...")
        # --- Cleanup DHT ---
        if self.dht and hasattr(self.dht, 'exit'):
             try:
                 self.dht.exit() # Call exit() method if available
                 logger.info("DHT sensor resources released.")
             except Exception as e:
                 logger.error(f"Error during DHT cleanup: {e}", exc_info=True)

        # --- Cleanup I2C ---
        # busio.I2C doesn't have an explicit close, but deinit can release the pins
        if self.i2c and hasattr(self.i2c, 'deinit'):
            try:
                self.i2c.deinit()
                logger.info("I2C bus deinitialized.")
            except Exception as e:
                logger.error(f"Error during I2C deinitialization: {e}", exc_info=True)

        self.dht = None
        self.ltr = None
        self.i2c = None
        logger.info("Hardware sensor cleanup finished.")

