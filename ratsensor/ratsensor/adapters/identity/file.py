import os
import uuid
import json
import logging
from ratsensor.core.ports import DeviceIdentityProvider

logger = logging.getLogger(__name__)

class FileDeviceIdentityProvider(DeviceIdentityProvider):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self._device_id: str | None = None

    def get_device_id(self) -> str:
        if self._device_id:
            return self._device_id

        config_dir = os.path.dirname(self.file_path)
        try:
            os.makedirs(config_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"Error creating config directory {config_dir}: {e}. Check permissions.")
            temp_id = f"temp-{uuid.uuid4()}"
            logger.warning(f"Falling back to temporary device ID: {temp_id}")
            self._device_id = temp_id
            return self._device_id

        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r') as f:
                    data = json.load(f)
                    device_id = data.get('device_id')
                    if device_id:
                        logger.info(f"Retrieved existing device ID: {device_id}")
                        self._device_id = device_id
                        return self._device_id
                    else:
                        logger.warning(f"device_id key missing in {self.file_path}. Generating new one.")

            device_id = str(uuid.uuid4())
            logger.info(f"Generated new device ID: {device_id}")
            with open(self.file_path, 'w') as f:
                json.dump({'device_id': device_id}, f)
                logger.info(f"Saved new device ID to {self.file_path}")
            self._device_id = device_id
            return device_id

        except (IOError, json.JSONDecodeError, OSError) as e:
            logger.error(f"Error managing device ID file {self.file_path}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error getting device ID: {e}", exc_info=True)

        temp_id = f"temp-{uuid.uuid4()}"
        logger.warning(f"Falling back to temporary device ID: {temp_id}")
        self._device_id = temp_id
        return self._device_id
