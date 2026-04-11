import yaml
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SerialConfig:
    port: str = "/dev/ttyUSB0"
    baudrate: int = 115200
    timeout: float = 1.0


@dataclass
class ServerConfig:
    port: int = 8888
    host: str = "0.0.0.0"


@dataclass
class PollingConfig:
    tx_interval: float = 0.2
    idle_interval: float = 1.0
    heartbeat: float = 15.0


@dataclass
class AppConfig:
    serial: SerialConfig = field(default_factory=SerialConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    polling: PollingConfig = field(default_factory=PollingConfig)
    log_level: str = "INFO"


def load_config(path: str = "config.yaml") -> AppConfig:
    config = AppConfig()
    config_path = Path(path)

    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

        if "serial" in raw:
            for k, v in raw["serial"].items():
                if hasattr(config.serial, k):
                    setattr(config.serial, k, v)

        if "server" in raw:
            for k, v in raw["server"].items():
                if hasattr(config.server, k):
                    setattr(config.server, k, v)

        if "polling" in raw:
            for k, v in raw["polling"].items():
                if hasattr(config.polling, k):
                    setattr(config.polling, k, v)

        if "logging" in raw:
            config.log_level = raw["logging"].get("level", "INFO")

        logger.info(f"Loaded config from {config_path}")
    else:
        logger.warning(f"Config file {config_path} not found, using defaults")

    return config
