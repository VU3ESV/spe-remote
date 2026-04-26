"""Async serial handler for SPE amplifier communication.

Uses plain pyserial (NOT serial_asyncio) on a background daemon thread for
reads. The thread pushes raw chunks into an asyncio queue via
``call_soon_threadsafe``; the asyncio event loop drains the queue and does
the framing. Writes go through a ``threading.Lock``-guarded wrapper so
coroutines never interleave packets on the wire.

Why not serial_asyncio: its internal ``_read_ready`` callback routinely
raises ``SerialException("readiness to read but returned no data")`` on
USB-serial adapters under moderate traffic, which bounces the port and
stalls RCU frame delivery. The blocking ``serial.Serial.read(...)`` call
used here never hits that code path, so the port stays up even under the
full RCU stream.

Parses two response types on the same byte stream:
  * CSV status frames (``AA AA AA`` + CNT=0x43 + 67 bytes + checksum + CRLF)
  * RCU LCD display frames (``AA AA AA`` + type=0x6A + variable payload,
    terminated by the next sync or a quiet period)

CSV frames feed ``on_state_update``; RCU frames feed ``on_rcu_frame``.
"""

import asyncio
import logging
import threading
import time
from typing import Callable, Optional

import serial
import serial.tools.list_ports

from spe.config import SerialConfig, PollingConfig
from spe.protocol import (
    CMD_REQUEST, CMD_RCU_ON, CMD_RCU_OFF, COMMANDS,
    RESP_STATUS_CNT, RESP_RCU_TYPE,
    AmplifierState, parse_status,
)

logger = logging.getLogger(__name__)

# RCU OFF->ON cycle cadence. Calmer values keep the USB-serial relaxed;
# the amp only emits one frame per display change so over-ticking just
# generates redundant traffic.
_RCU_TICK_INTERVAL = 1.5  # seconds — keeps the live cursor mirror
                          # responsive without flooding the amp's small
                          # serial input buffer.
_RCU_OFF_ON_GAP = 0.05    # seconds

# Force-flush an unterminated RCU frame if no new bytes arrive for this
# long. Covers static screens where the amp sends one frame and then goes
# silent until the next tick.
_RCU_QUIET_FLUSH = 0.3    # seconds

# Cap the receive buffer to prevent unbounded growth on a stuck parser.
_MAX_BUFFER = 4096

# Blocking serial read timeout. Balances responsiveness against CPU churn
# in the reader thread. 100 ms is plenty — chunks arrive as fast as the
# amp sends them.
_READ_TIMEOUT = 0.1


class SerialHandler:
    """Manages serial communication with the SPE amplifier.

    Threading model:
      * Asyncio loop owns: command queue, frame parsing, callbacks.
      * Daemon thread owns: blocking reads from the serial port.
      * The thread posts byte chunks to asyncio via ``call_soon_threadsafe``.
      * Writes are synchronous from asyncio (pyserial's Serial.write is
        fast) but guarded by ``self._write_lock`` (threading.Lock) so the
        reader thread never sees a half-written packet.
    """

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
        self.on_rcu_frame = on_rcu_frame

        self._port: serial.Serial | None = None
        self._connected = False
        self._running = False
        self._state = AmplifierState()

        self._command_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._write_lock = threading.Lock()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()

        self._buffer = bytearray()
        self._last_byte_at: float = 0.0

    @property
    def state(self) -> AmplifierState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._loop = asyncio.get_running_loop()
        while self._running:
            try:
                await self._open_port()
                await self._run_loop()
            except (serial.SerialException, OSError) as e:
                logger.error(f"Serial error: {e}")
            finally:
                self._teardown_port()
            if self._running:
                logger.info("Reconnecting in 3 seconds...")
                await asyncio.sleep(3)

    async def stop(self) -> None:
        self._running = False
        self._stop_reader.set()
        if self._port and self._port.is_open:
            try:
                self._safe_write(CMD_RCU_OFF)
            except Exception:
                pass
        self._teardown_port()

    def send_command(self, command: str) -> None:
        cmd_bytes = COMMANDS.get(command)
        if cmd_bytes:
            self._command_queue.put_nowait(cmd_bytes)
            logger.info(f"Queued command: {command}")
        else:
            logger.warning(f"Unknown command: {command}")

    # ------------------------------------------------------------------
    # Port open / close
    # ------------------------------------------------------------------

    async def _open_port(self) -> None:
        logger.info(
            f"Connecting to {self.serial_config.port} "
            f"at {self.serial_config.baudrate} baud..."
        )
        port = serial.Serial(
            port=self.serial_config.port,
            baudrate=self.serial_config.baudrate,
            timeout=_READ_TIMEOUT,
            write_timeout=1.0,
        )
        self._port = port
        self._connected = True
        self._buffer.clear()
        self._last_byte_at = 0.0
        logger.info("Serial connected")

        # Fire up the reader thread.
        self._stop_reader.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="spe-serial-reader",
            daemon=True,
        )
        self._reader_thread.start()

        # Initial status request + enable RCU.
        self._safe_write(CMD_REQUEST)
        self._safe_write(CMD_RCU_ON)

    def _teardown_port(self) -> None:
        """Close the port and signal the reader thread to exit. Idempotent."""
        self._connected = False
        self._stop_reader.set()

        # Drop queued user commands so stale presses don't fire on a
        # different menu after the reconnect completes.
        try:
            while not self._command_queue.empty():
                self._command_queue.get_nowait()
        except Exception:
            pass

        port = self._port
        self._port = None
        if port is not None:
            try:
                if port.is_open:
                    port.close()
            except Exception:
                pass

        # Don't join the reader thread here — we're potentially on the
        # same thread or need to avoid blocking the event loop. The
        # thread exits naturally once its serial handle is closed.

    # ------------------------------------------------------------------
    # Write path (asyncio side, but synchronous)
    # ------------------------------------------------------------------

    def _safe_write(self, payload: bytes) -> None:
        port = self._port
        if port is None or not port.is_open:
            logger.warning(
                f"Serial write skipped: port {'None' if port is None else 'closed'} "
                f"(payload={payload.hex()})"
            )
            return
        # Back-pressure: if the OS-level write buffer is already piling
        # up (FTDI hasn't drained yet), drop low-priority RCU heartbeat
        # writes rather than queueing more. RCU_OFF/RCU_ON are 0x80/0x81
        # — losing one tick is harmless; the next tick will produce a
        # frame. Dropping a user command (any other code) would lose a
        # button press, so we always commit those.
        is_rcu_tick = payload in (CMD_RCU_OFF, CMD_RCU_ON, CMD_REQUEST)
        try:
            waiting = port.out_waiting
        except Exception:
            waiting = 0
        if is_rcu_tick and waiting > 64:
            logger.debug(
                f"Backpressure: skipping {payload.hex()} "
                f"(out_waiting={waiting})"
            )
            return
        with self._write_lock:
            try:
                logger.debug(f"Serial write: {payload.hex()}")
                port.write(payload)
                # flush() forces the kernel write buffer to drain. Without
                # it, FTDI writes accumulate in the kernel queue and the
                # driver eventually wedges (writes silently succeed at OS
                # level but never reach the device). With the heartbeat
                # throttled to 1.5 s and back-pressure above, flush()
                # completes in microseconds; only a hardware-stuck device
                # would block here, in which case we want the exception.
                port.flush()
            except (serial.SerialException, OSError) as e:
                logger.warning(f"Serial write failed: {e}")

    # ------------------------------------------------------------------
    # Reader thread
    # ------------------------------------------------------------------

    def _reader_loop(self) -> None:
        port = self._port
        loop = self._loop
        if port is None or loop is None:
            return
        spurious_count = 0
        while not self._stop_reader.is_set():
            try:
                data = port.read(256)
            except serial.SerialException as e:
                msg = str(e)
                if "readiness to read but returned no data" in msg:
                    # Linux USB-serial kernel-level spurious readable flag.
                    # The port is actually fine — just the poll() flag is
                    # lying. Retry rather than tear down the connection.
                    spurious_count += 1
                    if spurious_count % 100 == 1:
                        logger.debug(
                            f"Suppressed spurious USB-serial poll glitch "
                            f"(count={spurious_count})"
                        )
                    # Tiny sleep so we don't spin at 100% CPU if the glitch
                    # is rapid-fire.
                    time.sleep(0.005)
                    continue
                logger.error(f"Serial read failed: {e}")
                loop.call_soon_threadsafe(self._signal_disconnect)
                return
            except OSError as e:
                logger.error(f"Serial read OS error: {e}")
                loop.call_soon_threadsafe(self._signal_disconnect)
                return
            if not data:
                # Timeout with no data — not an error, just continue.
                continue
            spurious_count = 0  # Real data flushes the glitch state.
            loop.call_soon_threadsafe(self._ingest_chunk, bytes(data))

    def _signal_disconnect(self) -> None:
        """Called on the asyncio loop when the reader thread has bailed.
        Tearing down the port here causes ``_run_loop`` to exit which kicks
        off a reconnect from ``start``'s outer loop."""
        self._stop_reader.set()
        # Closing the port makes any pending write raise, and the run loop
        # tasks will finish naturally.
        port = self._port
        if port is not None:
            try:
                if port.is_open:
                    port.close()
            except Exception:
                pass

    def _ingest_chunk(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._buffer.extend(chunk)
        self._last_byte_at = time.monotonic()
        if len(self._buffer) > _MAX_BUFFER:
            logger.warning("Receive buffer overflowed, dropping stale bytes")
            self._buffer.clear()
            return
        self._drain_buffer()

    # ------------------------------------------------------------------
    # Asyncio background loops
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        poll_task = asyncio.create_task(self._poll_loop())
        cmd_task = asyncio.create_task(self._command_loop())
        rcu_task = asyncio.create_task(self._rcu_tick_loop())
        flush_task = asyncio.create_task(self._quiet_flush_loop())
        watchdog_task = asyncio.create_task(self._connection_watchdog())

        tasks = [poll_task, cmd_task, rcu_task, flush_task, watchdog_task]
        try:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, asyncio.CancelledError):
                    raise exc
        finally:
            for task in tasks:
                task.cancel()
            # Await cancellations so they don't log "was never retrieved".
            for task in tasks:
                try:
                    await task
                except BaseException:
                    pass

    async def _connection_watchdog(self) -> None:
        """Returns (exits the _run_loop) once the port has been torn down
        by a reader-thread error. Keeps the outer reconnect logic simple."""
        while self._running:
            if self._port is None or not self._port.is_open:
                return
            await asyncio.sleep(0.25)

    async def _poll_loop(self) -> None:
        while self._running:
            interval = (
                self.polling_config.tx_interval
                if self._state.is_active
                else self.polling_config.idle_interval
            )
            await asyncio.sleep(interval)
            if self._command_queue.empty():
                self._safe_write(CMD_REQUEST)

    async def _command_loop(self) -> None:
        while self._running:
            cmd = await self._command_queue.get()
            self._safe_write(cmd)

    async def _rcu_tick_loop(self) -> None:
        while self._running:
            await asyncio.sleep(_RCU_TICK_INTERVAL)
            self._safe_write(CMD_RCU_OFF)
            await asyncio.sleep(_RCU_OFF_ON_GAP)
            self._safe_write(CMD_RCU_ON)

    async def _quiet_flush_loop(self) -> None:
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
    # Frame extraction (same as the serial_asyncio version)
    # ------------------------------------------------------------------

    def _drain_buffer(self) -> None:
        while True:
            sync = self._find_sync(0)
            if sync is None:
                if len(self._buffer) > 3:
                    del self._buffer[:-3]
                return
            if sync > 0:
                del self._buffer[:sync]
            if len(self._buffer) < 4:
                return

            marker = self._buffer[3]
            if marker == RESP_STATUS_CNT:
                if not self._consume_csv_frame():
                    return
            elif marker == RESP_RCU_TYPE:
                if not self._consume_rcu_frame():
                    return
            else:
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
        """CSV: 3 sync + 1 CNT + 67 data + 2 checksum + 2 CRLF = 75 bytes."""
        length = self._buffer[3]
        total = 3 + 1 + length + 2 + 2
        if len(self._buffer) < total:
            return False
        payload = bytes(self._buffer[4:4 + length])
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
        """RCU: sync + 0x6A + payload; payload ends at next sync."""
        next_sync = self._find_sync(4)
        if next_sync is None:
            return False
        payload = bytes(self._buffer[4:next_sync])
        del self._buffer[:next_sync]
        self._emit_rcu_frame(payload)
        return True

    def _flush_open_rcu_frame(self) -> None:
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
