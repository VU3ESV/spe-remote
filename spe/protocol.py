"""SPE Expert amplifier serial protocol parser and command builder."""

import json
import logging
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Command bytes for SPE Expert 1.3K-FA / 1.5K-FA / 2K-FA
# Packet format: 0x55 0x55 0x55 [CNT] [DATA...] [CHK]
# For single-byte commands: CNT=0x01, CHK=DATA
# Reference: SPE Application Programmer's Guide Rev 1.1

CMD_INPUT = b"\x55\x55\x55\x01\x01\x01"       # Toggle input port
CMD_BAND_DN = b"\x55\x55\x55\x01\x02\x02"     # Band down
CMD_BAND_UP = b"\x55\x55\x55\x01\x03\x03"     # Band up
CMD_ANTENNA = b"\x55\x55\x55\x01\x04\x04"     # Cycle TX antenna
CMD_L_MINUS = b"\x55\x55\x55\x01\x05\x05"     # ATU L minus
CMD_L_PLUS = b"\x55\x55\x55\x01\x06\x06"      # ATU L plus
CMD_C_MINUS = b"\x55\x55\x55\x01\x07\x07"     # ATU C minus
CMD_C_PLUS = b"\x55\x55\x55\x01\x08\x08"      # ATU C plus
CMD_TUNE = b"\x55\x55\x55\x01\x09\x09"        # Start ATU tuning
CMD_SWITCH_OFF = b"\x55\x55\x55\x01\x0A\x0A"  # Power OFF amplifier
CMD_POWER = b"\x55\x55\x55\x01\x0B\x0B"       # Toggle power level (L/M/H)
CMD_DISPLAY = b"\x55\x55\x55\x01\x0C\x0C"     # Display toggle
CMD_OPERATE = b"\x55\x55\x55\x01\x0D\x0D"     # Toggle operate/standby
CMD_CAT = b"\x55\x55\x55\x01\x0E\x0E"         # CAT mode
CMD_LEFT = b"\x55\x55\x55\x01\x0F\x0F"        # Left arrow / menu nav
CMD_RIGHT = b"\x55\x55\x55\x01\x10\x10"       # Right arrow / menu nav
CMD_SET = b"\x55\x55\x55\x01\x11\x11"         # Set / menu enter
CMD_BL_ON = b"\x55\x55\x55\x01\x82\x82"       # Backlight on
CMD_BL_OFF = b"\x55\x55\x55\x01\x83\x83"      # Backlight off
CMD_REQUEST = b"\x55\x55\x55\x01\x90\x90"     # Request status string
CMD_RCU_ON = b"\x55\x55\x55\x01\x80\x80"      # RCU (live LCD mirror) on
CMD_RCU_OFF = b"\x55\x55\x55\x01\x81\x81"     # RCU off

# Response packet type markers (byte immediately after AA AA AA sync)
RESP_STATUS_CNT = 0x43     # CSV status frame (67 bytes of data)
RESP_RCU_TYPE = 0x6A       # Proprietary LCD display frame in RCU mode

# Commands accessible via WebSocket. Names here MUST match the
# `wsCommandName` values in MacExpert's SPEProtocol.swift so both clients
# can drive the amp identically.
COMMANDS = {
    "input": CMD_INPUT,
    "band_dn": CMD_BAND_DN,
    "band_up": CMD_BAND_UP,
    "antenna": CMD_ANTENNA,
    "l_minus": CMD_L_MINUS,
    "l_plus": CMD_L_PLUS,
    "c_minus": CMD_C_MINUS,
    "c_plus": CMD_C_PLUS,
    "tune": CMD_TUNE,
    "power_off": CMD_SWITCH_OFF,
    "power_level": CMD_POWER,
    "display": CMD_DISPLAY,
    "oper": CMD_OPERATE,
    "cat": CMD_CAT,
    "left": CMD_LEFT,
    "right": CMD_RIGHT,
    "set": CMD_SET,
    "rcu_on": CMD_RCU_ON,
    "rcu_off": CMD_RCU_OFF,
    "backlight_on": CMD_BL_ON,
    "backlight_off": CMD_BL_OFF,
    "gain": CMD_POWER,           # Alias kept for backward compatibility
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
