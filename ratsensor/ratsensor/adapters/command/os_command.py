# ratsensor/adapters/command/os_command.py
import os
import logging
import time
from ratsensor.core.ports import CommandExecutor

logger = logging.getLogger(__name__)

class OSCommandExecutor(CommandExecutor):
    def execute_reboot(self) -> None:
        logger.warning("Executing system reboot command via os.system...")
        # Add a small delay to allow logs/messages to potentially flush
        time.sleep(2)
        try:
            # IMPORTANT: Ensure the user running this script has passwordless
            # sudo privileges for the 'reboot' command, or run the script as root.
            # This is a security risk if the MQTT topic is not secured.
            os.system('sudo reboot')
            # If os.system returns, it likely failed.
            logger.error("Reboot command execution may have failed (os.system returned).")
        except Exception as e:
            logger.error(f"Exception during reboot command execution: {e}", exc_info=True)
