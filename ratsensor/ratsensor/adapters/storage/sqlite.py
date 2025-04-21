import os
import sqlite3
import logging
from typing import List
from ratsensor.core.domain import SensorData
from ratsensor.core.ports import DataStorage

logger = logging.getLogger(__name__)

class SQLiteStorageAdapter(DataStorage):
    def __init__(self, db_file_path: str, timeout: float = 10.0):
        self.db_file_path = db_file_path
        self.timeout = timeout
        self._initialized = False

    def initialize(self) -> bool:
        if self._initialized:
            return True

        db_dir = os.path.dirname(self.db_file_path)
        try:
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"Ensured database directory exists: {db_dir}")
        except OSError as e:
            logger.error(f"Error creating database directory {db_dir}: {e}. Check permissions.")
            return False

        try:
            conn = sqlite3.connect(self.db_file_path, timeout=self.timeout)
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
            # Optional: Add index for faster lookups if needed
            cursor.execute('''
               CREATE INDEX IF NOT EXISTS idx_timestamp ON sensor_readings (timestamp);
            ''')
            conn.commit()
            conn.close()
            logger.info(f"Database initialized successfully at {self.db_file_path}")
            self._initialized = True
            return True
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            return False

    def save_sensor_readings(self, readings: List[SensorData]) -> bool:
        if not self._initialized:
            logger.error("Database not initialized, cannot save readings.")
            return False
        if not readings:
            return True # Nothing to save

        insert_data = [
            (rec.timestamp, rec.device_id, rec.temperature, rec.humidity, rec.light)
            for rec in readings
        ]

        try:
            conn = sqlite3.connect(self.db_file_path, timeout=self.timeout)
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT OR IGNORE INTO sensor_readings
                (timestamp, device_id, temperature, humidity, light)
                VALUES (?, ?, ?, ?, ?)
            ''', insert_data)
            conn.commit()
            conn.close()
            logger.debug(f"Successfully saved {len(readings)} records to database.")
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                logger.warning(f"Database is locked, could not save data this cycle: {e}")
            else:
                logger.error(f"Database operational error during save: {e}")
            return False
        except sqlite3.Error as e:
            logger.error(f"Failed to save data to database: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during database save: {e}", exc_info=True)
            return False
