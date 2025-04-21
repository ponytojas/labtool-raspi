from dataclasses import dataclass
from typing import Optional

@dataclass
class SensorData:
    timestamp: str 
    device_id: str
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    light: Optional[int] = None

@dataclass
class SystemInfo:
    timestamp: str 
    device_id: str
    disk_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    cpu_percent: Optional[float] = None
    uptime_seconds: Optional[int] = None
    uptime_human: Optional[str] = None

@dataclass
class AppConfig:
    # Intervals
    read_interval_seconds: int = 30 
    db_save_interval_reads: int = 5 

    # MQTT
    mqtt_broker: Optional[str] = None
    mqtt_port: int = 1883
    mqtt_user: Optional[str] = None
    mqtt_pass: Optional[str] = None
    mqtt_sensor_topic_template: str = "sensor/{}"
    mqtt_info_topic_template: str = "info/{}"
    mqtt_admin_topic_template: Optional[str] = None 
    listen_for_admin: bool = False
    mqtt_initial_retry_delay: int = 15
    mqtt_max_retry_delay: int = 300
    mqtt_retry_backoff_factor: float = 2.0

    # Paths
    device_id_file: str = "/etc/ratsensor/device_id.json"
    database_file: str = "/var/lib/ratsensor/sensor_data.db"
    log_file: str = "/var/log/ratsensor/ratsensor.log"

    # Simulation
    simulation_mode: bool = False

    # Hardware specific
    dht_pin: int = 14
    i2c_bus_number: int = 1
