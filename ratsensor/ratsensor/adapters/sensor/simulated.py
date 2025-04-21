import random
import math
import logging
from datetime import datetime
from ratsensor.core.domain import SensorData
from ratsensor.core.ports import SensorReader

logger = logging.getLogger(__name__)

class SimulatedSensorReader(SensorReader):
    def __init__(self, device_id: str = "simulated-device"):
        # Base values for simulation
        self.temp_base = 23.5
        self.humid_base = 55.0
        self.light_base = 8500
        self._device_id = device_id # Needed for SensorData creation
        logger.info("Initialized Simulated Sensor Reader")

    def initialize(self) -> bool:
        logger.debug("Simulated sensor initialization successful (no-op).")
        return True

    def read_sensors(self) -> SensorData:
        # --- Temperature & Humidity Simulation ---
        temperature = self.temp_base + random.uniform(-1.5, 1.5)
        temp_effect = 0.2 * (temperature - self.temp_base)
        humidity = self.humid_base + random.uniform(-5.0, 5.0) + temp_effect

        # Add time-based variation
        hour = datetime.now().hour
        time_temp_effect = 1.5 * math.sin((hour - 9) * math.pi / 12)
        time_humid_effect = 5.0 * math.sin((hour - 3) * math.pi / 12)

        temperature = max(min(temperature + time_temp_effect, 32.0), 18.0)
        humidity = max(min(humidity + time_humid_effect, 95.0), 35.0)

        # --- Light Simulation ---
        time_factor = math.sin((hour - 7) * math.pi / 12) # Peaks around 1 PM
        normalized_factor = (time_factor + 1) / 2 # Scale 0-1
        light_level = max(0, int(self.light_base * normalized_factor) + random.randint(-500, 500))

        # Timestamp and device_id will be set by the core service
        return SensorData(
            timestamp="", # Placeholder
            device_id=self._device_id, # Placeholder
            temperature=round(temperature, 1),
            humidity=round(humidity, 1),
            light=light_level
        )

    def cleanup(self) -> None:
        logger.debug("Simulated sensor cleanup (no-op).")
