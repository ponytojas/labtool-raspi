import logging
import time
from datetime import timedelta
from ratsensor.core.domain import SystemInfo
from ratsensor.core.ports import SystemInfoReader

logger = logging.getLogger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    logger.warning("psutil library not found. Real system info reader unavailable.")
    PSUTIL_AVAILABLE = False

class PsutilSystemInfoReader(SystemInfoReader):
    def __init__(self, device_id: str):
        self._device_id = device_id
        if not PSUTIL_AVAILABLE:
            raise RuntimeError("psutil library not available. Cannot instantiate PsutilSystemInfoReader.")
        logger.info("Initialized Psutil System Info Reader")

    def read_system_info(self) -> SystemInfo:
        disk = None
        mem = None
        cpu = None
        uptime_sec = None
        uptime_hum = None
        try:
            disk = round(psutil.disk_usage('/').percent, 1)
            mem = round(psutil.virtual_memory().percent, 1)
            # Use a short interval for CPU, but be mindful of impact
            cpu = round(psutil.cpu_percent(interval=0.1), 1)
            boot_time = psutil.boot_time()
            current_time = time.time()
            uptime_sec = int(current_time - boot_time)
            delta = timedelta(seconds=uptime_sec)
            uptime_hum = str(delta).split('.')[0] # Remove microseconds

        except Exception as e:
            logger.error(f"Error getting system info via psutil: {e}", exc_info=True)

        # Timestamp and device_id will be set by the core service
        return SystemInfo(
            timestamp="", # Placeholder
            device_id=self._device_id, # Placeholder
            disk_percent=disk,
            memory_percent=mem,
            cpu_percent=cpu,
            uptime_seconds=uptime_sec,
            uptime_human=uptime_hum
        )
