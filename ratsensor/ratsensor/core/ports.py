# ratsensor/core/ports.py
import abc
from typing import List, Callable, Optional
from ratsensor.core.domain import SensorData, SystemInfo, AppConfig

# --- Driven Ports (Core uses these) ---

class SensorReader(abc.ABC):
    @abc.abstractmethod
    def read_sensors(self) -> SensorData:
        """Reads temperature, humidity, and light."""
        pass

    def initialize(self) -> bool:
        """Optional: Initialize sensor hardware."""
        return True

    def cleanup(self) -> None:
        """Optional: Cleanup sensor resources."""
        pass

class SystemInfoReader(abc.ABC):
    @abc.abstractmethod
    def read_system_info(self) -> SystemInfo:
        """Reads system metrics."""
        pass

class DataPublisher(abc.ABC):
    @abc.abstractmethod
    def connect(self) -> bool:
        """Establish connection to the publisher."""
        pass

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the publisher."""
        pass

    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Check if currently connected."""
        pass

    @abc.abstractmethod
    def publish_sensor_data(self, data: SensorData) -> bool:
        """Publish sensor data."""
        pass

    @abc.abstractmethod
    def publish_info_data(self, data: SystemInfo) -> bool:
        """Publish system info data."""
        pass

class DataStorage(abc.ABC):
    @abc.abstractmethod
    def initialize(self) -> bool:
        """Initialize the storage medium (e.g., create table)."""
        pass

    @abc.abstractmethod
    def save_sensor_readings(self, readings: List[SensorData]) -> bool:
        """Save a batch of sensor readings."""
        pass

class DeviceIdentityProvider(abc.ABC):
    @abc.abstractmethod
    def get_device_id(self) -> str:
        """Get or create a unique device ID."""
        pass

class ConfigurationProvider(abc.ABC):
    @abc.abstractmethod
    def get_config(self) -> AppConfig:
        """Load and return application configuration."""
        pass

class CommandExecutor(abc.ABC):
    @abc.abstractmethod
    def execute_reboot(self) -> None:
        """Executes the system reboot command."""
        pass

AdminCommandHandler = Callable[[str], None]

class AdminCommandListener(abc.ABC):
    @abc.abstractmethod
    def start_listening(self, handler: AdminCommandHandler) -> bool:
        """Start listening for admin commands and call handler when received."""
        pass

    @abc.abstractmethod
    def stop_listening(self) -> None:
        """Stop listening for admin commands."""
        pass
