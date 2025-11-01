"""Configuration management module"""

import yaml
from pathlib import Path
from typing import Any, Dict


class Config:
    """Configuration management class"""

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize configuration

        Args:
            config_path: Configuration file path
        """
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration file"""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_path}\n"
                f"Please copy config.example.yaml to config.yaml and fill in the configuration"
            )

        with open(self.config_path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration item (supports dot-separated nested keys)

        Args:
            key: Configuration key, e.g. 'telegram.token'
            default: Default value

        Returns:
            Configuration value
        """
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    @property
    def ehdb_database(self) -> Dict[str, Any]:
        """Get EHDB database configuration"""
        return self._config.get("ehdb_database", {})

    @property
    def local_database(self) -> str:
        """Get local database path"""
        return self._config.get("local_database", "./data/recommender.db")

    @property
    def crawler(self) -> Dict[str, Any]:
        """Get crawler configuration"""
        return self._config.get("crawler", {})

    @property
    def telegram(self) -> Dict[str, Any]:
        """Get Telegram configuration"""
        return self._config.get("telegram", {})

    @property
    def recommender(self) -> Dict[str, Any]:
        """Get recommender configuration"""
        return self._config.get("recommender", {})

    @property
    def scheduler(self) -> Dict[str, Any]:
        """Get scheduler configuration"""
        return self._config.get("scheduler", {})

    @property
    def log_level(self) -> str:
        """Get log level"""
        return self._config.get("log_level", "INFO")
