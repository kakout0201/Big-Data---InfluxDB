"""Configuration loader for InfluxDB 3 Time-Series Data Generator.

Reads configuration from environment variables / .env file securely without
hardcoding credentials or logging sensitive tokens.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Locate .env file relative to the project root
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"

# Load environment variables if .env exists
if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)
else:
    load_dotenv()


@dataclass(frozen=True)
class InfluxDBConfig:
    """InfluxDB 3 connection configuration parameters."""

    url: str
    token: str
    database: str

    @classmethod
    def load(cls) -> "InfluxDBConfig":
        """Load and validate configuration from environment.

        Raises:
            ValueError: If required configuration (like INFLUXDB_TOKEN) is
            missing.
        """
        url = os.getenv("INFLUXDB_URL", "https://localhost:8181").strip()
        token = os.getenv("INFLUXDB_TOKEN", "").strip()
        database = os.getenv("INFLUXDB_DATABASE", "server_monitoring").strip()

        if not token:
            raise ValueError(
                "INFLUXDB_TOKEN is not configured! "
                "Please specify INFLUXDB_TOKEN in your .env file or environment."
            )

        if not database:
            raise ValueError("INFLUXDB_DATABASE cannot be empty.")

        return cls(url=url, token=token, database=database)

    def sanitized_summary(self) -> str:
        """Return a string summary of the configuration with token masked."""
        return (
            f"InfluxDBConfig(url='{self.url}', database='{self.database}', "
            f"token='***[MASKED]***')"
        )
