"""Async serial handler for SPE amplifier communication.

Parses two response types on the same byte stream:
  * CSV status frames (sync ``AA AA AA`` + CNT=0x43 + 67 bytes ASCII + checksum + CRLF)
  * RCU LCD display frames (sync ``AA AA AA`` + type=0x6A + variable-length payload,
    terminated by the next ``AA AA AA`` sync or a quiet period)

CSV frames feed ``on_state_update``; RCU frames feed ``on_rcu_frame`` which the
WebSocket handler forwards as binary messages so MacExpert (and any future
client) can render the amp's LCD in real time.
"""

import asyncio
import logging
import time
from typing import Callable, Optional

import serial
import serial.tools.list_ports
import serial_asyncio

from spe.config import SerialConfig, PollingConfig
from spe.protocol import (
    CMD_REQUEST, CMD_RCU_ON, CMD_RCU_OFF, COMMANDS,
    RESP_STATUS_CNT, RESP_RCU_TYPE,
    AmplifierState, parse_status,
)

logger = logging.getLogger(__name__)

# How often to re-issue the RCU_OFF -> RCU_ON cycle while RCU is enabled.
# Matches MacExpert's serial behaviour so the amp keeps emitting fresh frames.
_RCU_TICK_INTERVAL = 0.4  # seconds
_RCU_OFF_ON_GAP = 0.06    # seconds

# Flush an unterminated RCU frame if no new bytes arrive for this long. The
# 1.5K-FA only emits a frame when the LCD changes, so we can't always rely on a
# closing sync to delimit one.
_RCU_QUIET_FLUSH = 0.25   # seconds

# Cap how big we let the receive buffer grow before dropping. Observed RCU
# frame is ~371 bytes; 2048 is plenty for several queued frames.
_MAX_BUFFER = 4096


class SerialHandler:
    """Manages serial communication with the SPE amplifier."""

    def __init__(
        self,
        serial_config: SerialConfig,
        polling_config: PollingConfig,
        on_state_update: Callable[[AmplifierState], None],
        on_rcu_frame: Optional[Callable[[bytes], None]] = None,
    ):
        self.serial_config = serial_config
        self.polling_config = polling_config
        self.on_state_update = on_state_update
        # Optional — only wired when a WebSocket client might want RCU. Server
        # always runs the RCU ticker so the first subscriber gets data without
        # a cold-start delay.
        self.on_rcu_frame = on_rcu_frame

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._command_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._state = AmplifierState()
        self._running = False

        # Rolling receive buffer for byte-stream framing.
        self._buffer = bytearray()
        # Timestamp of last incoming byte; used to force-flush a stalled RCU
        # frame when the amp goes quiet.
        self._last_byte_at: float = 0.0
        # Serialises all writes to the serial transport. Without this, three
        # concurrent coroutines (command loop, CSV polling, RCU ticker) can
        # each call writer.write/drain and their frames interleave on the
        # wire — the amp then sees mangled command packets and ignores them.
        self._write_lock: asyncio.Lock | None = None

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
        # Close the writer/transport cleanly and clear references.
        if self._writer:
            # Best-effort: ask amp to stop emitting RCU frames before tearing
            # down the port so a subsequent reconnect isn't chasing stale
            # frames.
            try:
                await self._write(CMD_RCU_OFF)
            except Exception:
                pass
            try:
                self._writer.close()
                wait_closed = getattr(self._writer, "wait_closed", None)
                if callable(wait_closed):
                    try:
                        await wait_closed()
                    except Exception:
                        # Some transports may raise on wait; fall back to short sleep
                        await asyncio.sleep(0.05)
                else:
                    # Best-effort flush if wait_closed not available
                    await asyncio.sleep(0.05)
            except Exception:
                logger.exception("Error closing serial writer")

        self._writer = None
        self._reader = None
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
        self._write_lock = asyncio.Lock()
        logger.info("Serial connected")

        # Reset framing buffer for the new connection.
        self._buffer.clear()
        self._last_byte_at = 0.0

        # Initial status request + enable RCU so the amp starts pushing LCD
        # frames as soon as the display state changes.
        await self._write(CMD_REQUEST)
        await self._write(CMD_RCU_ON)

    async def _run_loop(self) -> None:
        read_task = asyncio.create_task(self._read_serial())
        poll_task = asyncio.create_task(self._poll_loop())
        cmd_task = asyncio.create_task(self._command_loop())
        rcu_task = asyncio.create_task(self._rcu_tick_loop())
        flush_task = asyncio.create_task(self._quiet_flush_loop())

        tasks = [read_task, poll_task, cmd_task, rcu_task, flush_task]
        try:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _read_serial(self) -> None:
        """Byte-stream read loop. Accumulates into self._buffer, then calls
        _drain_buffer to emit any complete CSV or RCU frames."""
        while self._running and self._reader:
            chunk = await self._reader.read(256)
            if not chunk:
                raise serial.SerialException("Serial connection lost")
            self._buffer.extend(chunk)
            self._last_byte_at = time.monotonic()
            if len(self._buffer) > _MAX_BUFFER:
                logger.warning(
                    "Receive buffer overflowed, dropping stale bytes"
                )
                self._buffer.clear()
            self._drain_buffer()

    async def _write(self, payload: bytes) -> None:
        """Write to the serial transport under the write lock so no two
        coroutines can interleave packets on the wire."""
        writer = self._writer
        lock = self._write_lock
        if writer is None or lock is None:
            return
        async with lock:
            writer.write(payload)
            await writer.drain()

    async def _poll_loop(self) -> None:
        while self._running and self._writer:
            interval = (
                self.polling_config.tx_interval
                if self._state.is_active
                else self.polling_config.idle_interval
            )
            await asyncio.sleep(interval)

            if self._command_queue.empty():
                await self._write(CMD_REQUEST)

    async def _command_loop(self) -> None:
        while self._running and self._writer:
            cmd = await self._command_queue.get()
            logger.debug(f"Writing command: {cmd.hex()}")
            await self._write(cmd)
            # Follow up with status request
            await asyncio.sleep(0.05)
            await self._write(CMD_REQUEST)

    async def _rcu_tick_loop(self) -> None:
        """Periodic RCU OFF -> ON cycle so the amp emits a fresh LCD frame
        every ~400ms. Matches MacExpert's direct-serial behaviour. The OFF
        resets the amp's "last reported state" marker; the subsequent ON
        therefore always triggers a frame, even when the display is static."""
        while self._running and self._writer:
            await asyncio.sleep(_RCU_TICK_INTERVAL)
            if not self._writer:
                return
            try:
                await self._write(CMD_RCU_OFF)
                await asyncio.sleep(_RCU_OFF_ON_GAP)
                if not self._writer:
                    return
                await self._write(CMD_RCU_ON)
            except Exception as e:
                logger.warning(f"RCU tick failed: {e}")
                return

    async def _quiet_flush_loop(self) -> None:
        """Flush an unterminated RCU frame from the buffer if no new bytes
        have arrived recently. Covers the case where the amp emits a frame
        and then goes silent (common on static screens between RCU ticks)."""
        while self._running:
            await asyncio.sleep(_RCU_QUIET_FLUSH / 2)
            if not self._buffer:
                continue
            if self._last_byte_at == 0.0:
                continue
            if time.monotonic() - self._last_byte_at < _RCU_QUIET_FLUSH:
                continue
            self._flush_open_rcu_frame()

    # ------------------------------------------------------------------
    # Frame extraction
    # ------------------------------------------------------------------

    def _drain_buffer(self) -> None:
        """Repeatedly pull complete frames out of self._buffer. Stops when no
        more complete frames can be extracted."""
        while True:
            sync = self._find_sync(0)
            if sync is None:
                # No sync found — discard leading garbage to keep buffer small.
                if len(self._buffer) > 3:
                    del self._buffer[:-3]
                return
            if sync > 0:
                # Drop bytes before the first sync.
                del self._buffer[:sync]
            if len(self._buffer) < 4:
                return

            marker = self._buffer[3]
            if marker == RESP_STATUS_CNT:
                if not self._consume_csv_frame():
                    return  # Need more bytes
            elif marker == RESP_RCU_TYPE:
                if not self._consume_rcu_frame():
                    return  # Need more bytes
            else:
                # Unknown packet type. Skip this sync and keep scanning.
                del self._buffer[:1]

    def _find_sync(self, start: int) -> int | None:
        buf = self._buffer
        end = len(buf) - 2
        i = start
        while i < end:
            if buf[i] == 0xAA and buf[i + 1] == 0xAA and buf[i + 2] == 0xAA:
                return i
            i += 1
        return None

    def _consume_csv_frame(self) -> bool:
        """CSV status: 3 sync + 1 CNT + 67 data + 2 checksum + 2 CRLF = 75 bytes."""
        length = self._buffer[3]
        total = 3 + 1 + length + 2 + 2
        if len(self._buffer) < total:
            return False

        data_start = 4
        data_end = data_start + length
        payload = bytes(self._buffer[data_start:data_end])
        del self._buffer[:total]

        try:
            line = payload.decode("ascii", errors="replace")
            state = parse_status(line)
            if state:
                self._state = state
                self.on_state_update(state)
        except Exception as e:
            logger.warning(f"CSV parse failed: {e}")
        return True

    def _consume_rcu_frame(self) -> bool:
        """RCU display frame: sync + 0x6A + payload, terminated by next sync.
        Returns True if a frame was consumed, False if we need more bytes to
        locate the terminating sync."""
        next_sync = self._find_sync(4)
        if next_sync is None:
            # Can't delimit yet. Let the quiet-flush loop handle it if the
            # amp goes silent.
            return False

        payload = bytes(self._buffer[4:next_sync])
        del self._buffer[:next_sync]
        self._emit_rcu_frame(payload)
        return True

    def _flush_open_rcu_frame(self) -> None:
        """Force-emit any unterminated 0x6A frame in the buffer. Called when
        the amp has gone quiet and no follow-on sync is coming."""
        if len(self._buffer) < 4:
            return
        if not (
            self._buffer[0] == 0xAA
            and self._buffer[1] == 0xAA
            and self._buffer[2] == 0xAA
            and self._buffer[3] == RESP_RCU_TYPE
        ):
            return
        payload = bytes(self._buffer[4:])
        self._buffer.clear()
        self._emit_rcu_frame(payload)

    def _emit_rcu_frame(self, payload: bytes) -> None:
        if not self.on_rcu_frame:
            return
        try:
            self.on_rcu_frame(payload)
        except Exception as e:
            logger.warning(f"RCU frame emit failed: {e}")
