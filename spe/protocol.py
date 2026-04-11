"""SPE Expert amplifier serial protocol parser and command builder."""

import json
import logging
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Command bytes for SPE amplifiers
CMD_REQUEST = b"\x55\x55\x55\x01\x90\x90"
CMD_OPERATE = b"\x55\x55\x55\x01\x0D\x0D"
CMD_ANTENNA = b"\x55\x55\x55\x01\x04\x04"
CMD_INPUT = b"\x55\x55\x55\x01\x01\x01"
CMD_TUNE = b"\x55\x55\x55\x01\x09\x09"
CMD_GAIN = b"\x55\x55\x55\x01\x0b\x0b"

COMMANDS = {
    "oper": CMD_OPERATE,
    "antenna": CMD_ANTENNA,
    "input": CMD_INPUT,
    "tune": CMD_TUNE,
    "gain": CMD_GAIN,
}

BAND_MAP = {
    "00": "160m", "01": "80m", "02": "60m", "03": "40m",
    "04": "30m", "05": "20m", "06": "17m", "07": "15m",
    "08": "12m", "09": "10m", "10": "6m", "11": "4m",
}

WARNING_MAP = {
    "M": "ALARM AMPLIFIER",
    "A": "NO SELECTED ANTENNA",
    "S": "SWR ANTENNA",
    "B": "NO VALID BAND",
    "P": "POWER LIMIT EXCEEDED",
    "O": "OVERHEATING",
    "Y": "ATU NOT AVAILABLE",
    "W": "TUNING WITH NO POWER",
    "K": "ATU BYPASSED",
    "R": "POWER SWITCH HELD BY REMOTE",
    "T": "COMBINER OVERHEATING",
    "C": "COMBINER FAULT",
    "N": "",
}

ERROR_MAP = {
    "S": "SWR EXCEEDING LIMITS",
    "A": "AMPLIFIER PROTECTION",
    "D": "INPUT OVERDRIVING",
    "H": "EXCESS OVERHEATING",
    "C": "COMBINER FAULT",
    "N": "",
}


@dataclass
class AmplifierState:
    op_status: str = "Stby"
    tx_status: str = "RX"
    input: str = "0"
    band: str = "---"
    tx_antenna: str = "0"
    p_level: str = "0"
    p_out: str = "0"
    swr: str = "0"
    aswr: str = "0"
    voltage: str = "0"
    drain: str = "0"
    pa_temp: str = "0"
    warnings: str = ""
    error: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @property
    def is_active(self) -> bool:
        return self.tx_status == "TX" or self.op_status == "Oper"


def parse_status(line: str) -> AmplifierState | None:
    """Parse a comma-separated status line from the SPE amplifier.

    Expected format: 22 comma-separated fields, last field is \\r\\n.
    """
    data = line.strip().split(",")

    if len(data) < 21:
        logger.debug(f"Short status line ({len(data)} fields), skipping")
        return None

    try:
        op_status = "Oper" if data[2] == "O" else "Stby"
        tx_status = "TX" if data[3] == "T" else "RX"

        return AmplifierState(
            op_status=op_status,
            tx_status=tx_status,
            input=data[5],
            band=BAND_MAP.get(data[6], "???"),
            tx_antenna=data[7],
            p_level=data[9],
            p_out=data[10],
            swr=data[11],
            aswr=data[12],
            voltage=data[13],
            drain=data[14],
            pa_temp=data[15],
            warnings=WARNING_MAP.get(data[18], ""),
            error=ERROR_MAP.get(data[19], ""),
        )
    except (IndexError, KeyError) as e:
        logger.warning(f"Failed to parse status line: {e}")
        return None
