import logging
from ratsensor.core.domain import SystemInfo
from ratsensor.core.ports import SystemInfoReader

logger = logging.getLogger(__name__)

class SimulatedSystemInfoReader(SystemInfoReader):
    def __init__(self, device_id: str = "simulated-device"):
        self._device_id = device_id
        logger.info("Initialized Simulated System Info Reader")

    def read_system_info(self) -> SystemInfo:
        logger.debug("Reading simulated system info.")
        # Timestamp and device_id will be set by the core service
        return SystemInfo(
            timestamp="", # Placeholder
            device_id=self._device_id, # Placeholder
            disk_percent=50.0,
            memory_percent=60.0,
            cpu_percent=25.0,
            uptime_seconds=3600,
            uptime_human="1:00:00"
        )
