import re
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
class AmpConfig:
    """Amp-side characteristics that the protocol doesn't report.

    The SPE returns temperatures as unit-less integers — the user picks
    Celsius or Fahrenheit in the front-panel setup menu. This setting must
    match that choice so the web client can render the right unit symbol
    and scale gauges/thresholds correctly.
    """
    temperature_unit: str = "C"  # "C" or "F"


@dataclass
class AppConfig:
    serial: SerialConfig = field(default_factory=SerialConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    polling: PollingConfig = field(default_factory=PollingConfig)
    amp: AmpConfig = field(default_factory=AmpConfig)
    log_level: str = "INFO"


def persist_temperature_unit(unit: str, path: str = "config.yaml") -> bool:
    """Rewrite ``amp.temperature_unit`` in ``config.yaml`` in place.

    Uses a line-based regex substitution so comments and unrelated keys
    survive untouched (PyYAML's dump would drop all of those). If the
    ``amp:`` section doesn't exist yet, append a minimal one. Returns
    True on success.
    """
    unit = "F" if str(unit).upper().startswith("F") else "C"
    p = Path(path)
    if not p.exists():
        logger.warning(f"Cannot persist unit: {path} does not exist")
        return False

    text = p.read_text()
    pattern = re.compile(
        r"^(\s*temperature_unit\s*:\s*)([A-Za-z]+)(\s*(?:#.*)?)$",
        re.MULTILINE,
    )
    if pattern.search(text):
        new_text = pattern.sub(lambda m: f"{m.group(1)}{unit}{m.group(3)}", text)
    else:
        # Section not present — append it. Preserves the rest of the file.
        suffix = "\n\namp:\n  temperature_unit: " + unit + "\n"
        new_text = text.rstrip() + suffix

    if new_text == text:
        return True  # Already at the requested value.

    try:
        p.write_text(new_text)
        logger.info(f"Persisted temperature_unit={unit} to {path}")
        return True
    except OSError as e:
        logger.warning(f"Failed to persist temperature_unit: {e}")
        return False


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

        if "amp" in raw:
            for k, v in raw["amp"].items():
                if hasattr(config.amp, k):
                    setattr(config.amp, k, v)
            # Normalise the unit to a single uppercase letter so downstream
            # comparisons don't have to handle "c" / "celsius" / "F" / etc.
            unit = str(config.amp.temperature_unit).strip().upper()[:1]
            config.amp.temperature_unit = "F" if unit == "F" else "C"

        if "logging" in raw:
            config.log_level = raw["logging"].get("level", "INFO")

        logger.info(f"Loaded config from {config_path}")
    else:
        logger.warning(f"Config file {config_path} not found, using defaults")

    return config
