"""Power on/off control for SPE amplifiers via DTR/RTS serial lines.

Based on the original power_spe_on.py script by OH2GEK.
The SPE amplifier is powered on/off by toggling DTR and RTS
lines on the serial port in a specific sequence.
"""

import asyncio
import logging

import serial

from spe.config import SerialConfig

logger = logging.getLogger(__name__)


class PowerController:
    """Controls SPE amplifier power via DTR/RTS serial line toggling."""

    def __init__(self, serial_config: SerialConfig):
        self.serial_config = serial_config
        self._lock = asyncio.Lock()

    async def power_on(self) -> bool:
        """Power on the SPE amplifier.

        Sequence (from OH2GEK):
          DTR=1 → DTR=0 → RTS=1 → wait 1s → DTR=1 → RTS=0
        """
        async with self._lock:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._power_on_sync
            )

    async def power_off(self) -> bool:
        """Power off the SPE amplifier.

        Sequence (reverse of power on):
          DTR=0 → RTS=1 → wait 1s → DTR=0 → RTS=0
        """
        async with self._lock:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._power_off_sync
            )

    def _power_on_sync(self) -> bool:
        try:
            logger.info(f"Power ON: toggling DTR/RTS on {self.serial_config.port}")
            ser = serial.Serial(self.serial_config.port)
            ser.dtr = 1
            ser.dtr = 0
            ser.rts = 1
            import time
            time.sleep(1)
            ser.dtr = 1
            ser.rts = 0
            ser.close()
            logger.info("Power ON: sequence complete")
            return True
        except (serial.SerialException, OSError) as e:
            logger.error(f"Power ON failed: {e}")
            return False

    def _power_off_sync(self) -> bool:
        try:
            logger.info(f"Power OFF: toggling DTR/RTS on {self.serial_config.port}")
            ser = serial.Serial(self.serial_config.port)
            ser.dtr = 0
            ser.rts = 1
            import time
            time.sleep(1)
            ser.dtr = 0
            ser.rts = 0
            ser.close()
            logger.info("Power OFF: sequence complete")
            return True
        except (serial.SerialException, OSError) as e:
            logger.error(f"Power OFF failed: {e}")
            return False
