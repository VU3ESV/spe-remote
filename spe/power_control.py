"""Power on/off control for SPE Expert amplifiers.

Power ON:  DTR hardware line toggle (no serial command exists for power on).
           Sequence from OH2GEK power_spe_on.py script.
Power OFF: Serial command 0x0A (SWITCH OFF) per SPE Application Programmer's
           Guide Rev 1.1 for Expert 1.3K-FA / 1.5K-FA / 2K-FA.

Note: When DTR is held high the amplifier's front-panel power switch is
overridden ("POWER SWITCH HELD BY REMOTE" warning). The startup takes
3-4.5 seconds after DTR is raised.
"""

import asyncio
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

        Sequence (from OH2GEK power_spe_on.py):
          DTR=1 -> DTR=0 -> RTS=1 -> wait 1s -> DTR=1 -> RTS=0
        Startup takes 3-4.5 seconds after this sequence.
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

    def _power_on_sync(self) -> bool:
        try:
            logger.info(f"Power ON: DTR/RTS sequence on {self.serial_config.port}")
            ser = serial.Serial(self.serial_config.port)
            ser.dtr = 1
            ser.dtr = 0
            ser.rts = 1
            time.sleep(1)
            ser.dtr = 1
            ser.rts = 0
            ser.close()
            logger.info("Power ON: DTR sequence complete (amp starting in 3-4s)")
            return True
        except (serial.SerialException, OSError) as e:
            logger.error(f"Power ON failed: {e}")
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
