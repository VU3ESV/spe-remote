"""SPE Expert amplifier serial protocol parser and command builder."""

from __future__ import annotations  # Allow PEP 604 unions (X | None) on Python 3.9

import json
import logging
import re
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

# Amp ID code pattern: 2 digits + K (e.g. 13K, 15K, 20K). The byte offsets
# in the CSV status frame have been observed to shift by ±1 between firmware
# revisions / framing variants, so we scan the first few fields rather than
# trusting a fixed index.
_MODEL_RE = re.compile(r"^\d{2}K$")
# Whether we've logged a sample of the parsed CSV fields yet. Helps debug
# field-offset drift on new firmwares without spamming the log.
_logged_first_parse = False


@dataclass
class AmplifierState:
    model: str = ""              # Amp ID code: "13K", "15K", "20K", or ""
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
    pa_temp: str = "0"           # Heatsink (upper on 2K-FA)
    pa_temp_lower: str = "0"     # Lower heatsink (2K-FA only; "000" on 1.3K-FA)
    pa_temp_combiner: str = "0"  # Combiner (2K-FA only)
    warnings: str = ""
    error: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @property
    def is_active(self) -> bool:
        # Only the actual TX state should accelerate polling. Treating
        # OPER (idle but armed) as "active" pushes the poll rate to
        # 5 Hz, which combined with the RCU heartbeat saturates the
        # amp's serial input buffer and causes user commands (OPER,
        # STBY, etc.) to be silently dropped.
        return self.tx_status == "TX"


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

        # Extra temps only meaningful on 2K-FA (1.3K-FA reports "000").
        # Indexed defensively in case a short / oddly-padded line slips through.
        pa_temp_lower = data[16].strip() if len(data) > 16 else "0"
        pa_temp_combiner = data[17].strip() if len(data) > 17 else "0"

        # Scan the first few fields for an amp ID code (e.g. 13K / 15K / 20K).
        # Different firmware revisions place the ID at slightly different
        # offsets — this avoids hardcoding a single index that breaks on yours.
        model = ""
        for i in range(min(3, len(data))):
            cand = data[i].strip()
            if _MODEL_RE.match(cand):
                model = cand
                break

        # Log the parsed field layout exactly once so we can diagnose any
        # offset issue on a new firmware without enabling DEBUG logging.
        global _logged_first_parse
        if not _logged_first_parse:
            _logged_first_parse = True
            preview = [f"[{i}]={data[i]!r}" for i in range(min(8, len(data)))]
            logger.info(
                f"First CSV parse: model={model!r}, "
                f"len={len(data)}, fields: {' '.join(preview)}"
            )

        return AmplifierState(
            model=model,
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
            pa_temp_lower=pa_temp_lower,
            pa_temp_combiner=pa_temp_combiner,
            warnings=WARNING_MAP.get(data[18], ""),
            error=ERROR_MAP.get(data[19], ""),
        )
    except (IndexError, KeyError) as e:
        logger.warning(f"Failed to parse status line: {e}")
        return None
