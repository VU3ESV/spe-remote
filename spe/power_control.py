"""Power on/off control for SPE Expert amplifiers.

Power ON:  DTR hardware line toggle (no serial command exists for power on).
           Sequence from OH2GEK power_spe_on.py script with the 100 ms
           initial settle borrowed from the WB2WGH/community Node-RED
           flow — the FTDI line state takes a few ms to settle after
           opening the port, and trusting it instantly can leave DTR in
           an indeterminate state on the first transition.
Power OFF: Serial command 0x0A (SWITCH OFF) per SPE Application Programmer's
           Guide Rev 1.1 for Expert 1.3K-FA / 1.5K-FA / 2K-FA.

Note: When DTR is held high the amplifier's front-panel power switch is
overridden ("POWER SWITCH HELD BY REMOTE" warning). The startup takes
3-4.5 seconds after DTR is raised.
"""

import asyncio
import glob
import logging
import time

import serial

from spe.config import SerialConfig

logger = logging.getLogger(__name__)


class PowerController:
    """Controls SPE amplifier power via DTR (on) and serial command (off)."""

    def __init__(self, serial_config: SerialConfig):
        self.serial_config = serial_config
        self._lock = asyncio.Lock()

    async def power_on(self) -> bool:
        """Power on the SPE amplifier via DTR line toggle.

        Sequence (from OH2GEK + WB2WGH Node-RED flow):
          open(57600) -> DTR=1 -> wait 100ms -> DTR=0 + RTS=1 -> wait 1s
          -> DTR=1 + RTS=0 -> close
        Startup takes 3-4.5 seconds after this sequence.

        Tries the configured port first, then falls back to any available
        FTDI by-id path, then any /dev/ttyUSB*. Solves the case where the
        FTDI cable was swapped and the by-id symlink changed without the
        user having to edit config.yaml.
        """
        async with self._lock:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._power_on_sync
            )

    async def power_off(self) -> bool:
        """Power off the SPE amplifier via SWITCH OFF command (0x0A).

        Per SPE Application Programmer's Guide, command 0x0A is the
        equivalent of pressing the front-panel OFF switch.
        """
        async with self._lock:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._power_off_sync
            )

    def _candidate_ports(self) -> list[str]:
        """Build the priority-ordered list of ports to try for power-on.
        Configured port first, then FTDI by-id, then ttyUSB."""
        seen = set()
        out: list[str] = []
        configured = self.serial_config.port
        if configured:
            out.append(configured)
            seen.add(configured)
        for path in sorted(glob.glob("/dev/serial/by-id/usb-FTDI_*")):
            if path not in seen:
                out.append(path)
                seen.add(path)
        for path in sorted(glob.glob("/dev/ttyUSB*")):
            if path not in seen:
                out.append(path)
                seen.add(path)
        return out

    def _power_on_sync(self) -> bool:
        candidates = self._candidate_ports()
        if not candidates:
            logger.error("Power ON failed: no candidate serial ports found")
            return False
        logger.info(f"Power ON: will try {candidates}")
        for port in candidates:
            try:
                # Explicit baud (57600) matches the community Node-RED
                # flow. Doesn't matter for line-state toggling per se,
                # but explicit is safer than pyserial's 9600 default
                # which some FTDI variants reject right after a
                # disconnect.
                ser = serial.Serial(port, 57600, timeout=1)
                logger.info(f"Power ON: opened {port}")
                ser.dtr = True
                time.sleep(0.1)              # FTDI settle
                ser.dtr = False
                ser.rts = True
                time.sleep(1.0)              # the actual power-on pulse
                ser.dtr = True
                ser.rts = False
                ser.close()
                logger.info(f"Power ON: DTR sequence complete on {port} "
                            f"(amp starting in 3-4s)")
                return True
            except (serial.SerialException, OSError) as e:
                logger.warning(f"Power ON: {port} failed: {e}")
                continue
        logger.error("Power ON failed: no candidate port could be opened")
        return False

    def _power_off_sync(self) -> bool:
        try:
            logger.info(f"Power OFF: sending SWITCH OFF (0x0A) on {self.serial_config.port}")
            ser = serial.Serial(
                self.serial_config.port,
                baudrate=self.serial_config.baudrate,
            )
            # SWITCH OFF command: 0x55 0x55 0x55 0x01 0x0A 0x0A
            ser.write(b"\x55\x55\x55\x01\x0A\x0A")
            ser.flush()
            time.sleep(0.5)
            ser.close()
            logger.info("Power OFF: SWITCH OFF command sent")
            return True
        except (serial.SerialException, OSError) as e:
            logger.error(f"Power OFF failed: {e}")
            return False
