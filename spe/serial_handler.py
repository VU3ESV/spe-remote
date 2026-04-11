"""Async serial handler for SPE amplifier communication."""

import asyncio
import logging
from typing import Callable

import serial
import serial.tools.list_ports
import serial_asyncio

from spe.config import SerialConfig, PollingConfig
from spe.protocol import (
    CMD_REQUEST, COMMANDS, AmplifierState, parse_status,
)

logger = logging.getLogger(__name__)


class SerialHandler:
    """Manages serial communication with the SPE amplifier."""

    def __init__(
        self,
        serial_config: SerialConfig,
        polling_config: PollingConfig,
        on_state_update: Callable[[AmplifierState], None],
    ):
        self.serial_config = serial_config
        self.polling_config = polling_config
        self.on_state_update = on_state_update

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._command_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._state = AmplifierState()
        self._running = False

    @property
    def state(self) -> AmplifierState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._connect()
                await self._run_loop()
            except (serial.SerialException, OSError) as e:
                logger.error(f"Serial error: {e}")
                self._connected = False
                if self._running:
                    logger.info("Reconnecting in 3 seconds...")
                    await asyncio.sleep(3)

    async def stop(self) -> None:
        self._running = False
        if self._writer:
            self._writer.close()
            self._connected = False

    def send_command(self, command: str) -> None:
        cmd_bytes = COMMANDS.get(command)
        if cmd_bytes:
            self._command_queue.put_nowait(cmd_bytes)
            logger.info(f"Queued command: {command}")
        else:
            logger.warning(f"Unknown command: {command}")

    async def _connect(self) -> None:
        logger.info(
            f"Connecting to {self.serial_config.port} "
            f"at {self.serial_config.baudrate} baud..."
        )
        self._reader, self._writer = await serial_asyncio.open_serial_connection(
            url=self.serial_config.port,
            baudrate=self.serial_config.baudrate,
        )
        self._connected = True
        logger.info("Serial connected")

        # Initial status request
        self._writer.write(CMD_REQUEST)
        await self._writer.drain()

    async def _run_loop(self) -> None:
        read_task = asyncio.create_task(self._read_serial())
        poll_task = asyncio.create_task(self._poll_loop())
        cmd_task = asyncio.create_task(self._command_loop())

        try:
            done, pending = await asyncio.wait(
                [read_task, poll_task, cmd_task],
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in done:
                task.result()  # Raise any exceptions
        finally:
            for task in [read_task, poll_task, cmd_task]:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _read_serial(self) -> None:
        while self._running and self._reader:
            line = await self._reader.readline()
            if not line:
                raise serial.SerialException("Serial connection lost")

            decoded = line.decode("ascii", errors="replace")
            state = parse_status(decoded)
            if state:
                self._state = state
                self.on_state_update(state)

    async def _poll_loop(self) -> None:
        while self._running and self._writer:
            interval = (
                self.polling_config.tx_interval
                if self._state.is_active
                else self.polling_config.idle_interval
            )
            await asyncio.sleep(interval)

            if self._command_queue.empty():
                self._writer.write(CMD_REQUEST)
                await self._writer.drain()

    async def _command_loop(self) -> None:
        while self._running and self._writer:
            cmd = await self._command_queue.get()
            self._writer.write(cmd)
            await self._writer.drain()

            # Follow up with status request
            await asyncio.sleep(0.05)
            self._writer.write(CMD_REQUEST)
            await self._writer.drain()
