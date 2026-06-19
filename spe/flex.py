"""FlexRadio 6000-series control via SmartSDR TCP/IP API.

Phase 1 of the spe-remote band-sweep work: a minimal async TCP client
that can drive a Flex 6000 hard enough to run the SM5TOG-style ATU
tune flow (set freq, set mode, key the built-in tune carrier). No
discovery — the radio's IP is configured statically in spe.config.

Protocol summary (from
https://github.com/flexradio/smartsdr-api-docs/wiki/SmartSDR-TCPIP-API):

  * TCP port 4992, line-oriented text protocol.
  * Outbound command:  C<seq>|<command>\\n
  * Inbound reply:     R<seq>|<hex_status>|<message>   (status 0 == ok)
  * Inbound async:     S<handle>|<message>            (subscribed events)
  * On connect the radio sends a banner — V<version> and H<handle>
    lines — before any reply traffic.

This module deliberately does NOT touch the existing serial-side
machinery in spe-remote. spe.server can stay oblivious to Flex until
Phase 2 wires the two together.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

FLEX_TCP_PORT = 4992

# How long to wait for a command reply before giving up and surfacing
# an error. SmartSDR replies are typically tens of milliseconds, so 5 s
# is generous. Tune state changes are NOT bounded by this — they arrive
# as async S<handle> messages on the subscription channel.
_REPLY_TIMEOUT = 5.0

# How long the radio has to send the V/H banner after the TCP socket
# opens. Real radios reply within a few hundred ms; the timeout exists
# to fail loudly if you point spe-remote at something that ISN'T a Flex.
_BANNER_TIMEOUT = 3.0


class FlexProtocolError(Exception):
    """Raised when the radio rejects a command (non-zero status code)."""


class FlexConnection:
    """Async client for one Flex 6000-series radio.

    Lifecycle:

        flex = FlexConnection("192.168.1.148")
        await flex.connect()                  # banner read, reader task started
        await flex.set_slice_mode(0, "CWU")
        await flex.set_slice_freq(0, 14.020)
        await flex.set_tune_power(10)
        await flex.tune_carrier(on=True)      # ATU on the amp can now sweep
        ...
        await flex.tune_carrier(on=False)
        await flex.close()

    The connection auto-reconnects nothing — Phase 2 will add a
    supervising loop. For now, a dropped socket raises on the next
    send.
    """

    def __init__(self, host: str, port: int = FLEX_TCP_PORT):
        self.host = host
        self.port = port

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._reader_task: Optional[asyncio.Task] = None

        # Monotonic sequence number for command framing. SmartSDR allows
        # up to 32-bit; we never recycle (a session lives minutes).
        self._seq = 0
        # Pending command futures keyed by sequence number.
        self._pending: dict[int, asyncio.Future] = {}

        # Banner data the radio volunteers right after connect.
        self.radio_version: str = ""
        self.client_handle: str = ""

        # Subscription callback: invoked for every S<handle>|<msg>.
        # Set after connect() if you want streamed updates.
        self.on_status: Optional[Callable[[str, str], None]] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the TCP socket, read the banner, start the reader loop."""
        logger.info(f"Flex: connecting to {self.host}:{self.port}")
        self._reader, self._writer = await asyncio.open_connection(
            self.host, self.port
        )

        # Banner: a few lines starting with V (version) and H (handle).
        # The radio sometimes batches them, sometimes doesn't — read
        # until either both are seen or the timeout fires.
        try:
            await asyncio.wait_for(self._read_banner(), timeout=_BANNER_TIMEOUT)
        except asyncio.TimeoutError:
            # Don't fail here — some firmware revisions skip one of the
            # banner lines. We can still issue commands; just leave the
            # field empty and warn.
            logger.warning(
                "Flex: banner incomplete after %.1fs "
                "(version=%r handle=%r). Continuing.",
                _BANNER_TIMEOUT, self.radio_version, self.client_handle,
            )

        self._reader_task = asyncio.create_task(self._read_loop())
        logger.info(
            f"Flex: connected (version={self.radio_version!r}, "
            f"handle={self.client_handle!r})"
        )

    async def close(self) -> None:
        """Shut down the connection. Idempotent."""
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        # Cancel any in-flight commands so callers don't hang forever.
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Flex connection closed"))
        self._pending.clear()

    # ------------------------------------------------------------------
    # Low-level send/receive
    # ------------------------------------------------------------------

    async def send(self, command: str) -> str:
        """Send a command, return the reply's message field.

        Raises ``FlexProtocolError`` if the radio reports a non-zero
        status. Raises ``ConnectionError`` if the socket is closed.
        Raises ``asyncio.TimeoutError`` if no reply arrives within
        ``_REPLY_TIMEOUT``.
        """
        if self._writer is None:
            raise ConnectionError("Flex not connected")
        self._seq += 1
        seq = self._seq
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[seq] = fut

        line = f"C{seq}|{command}\n"
        self._writer.write(line.encode("ascii", errors="replace"))
        try:
            await self._writer.drain()
        except Exception as e:
            self._pending.pop(seq, None)
            raise ConnectionError(f"Flex write failed: {e}") from e

        try:
            status, message = await asyncio.wait_for(fut, timeout=_REPLY_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending.pop(seq, None)
            raise
        if status != 0:
            raise FlexProtocolError(
                f"Flex rejected {command!r}: status=0x{status:08X} msg={message!r}"
            )
        return message

    async def _read_banner(self) -> None:
        """Read the radio's V/H banner. Stops when both seen, or on
        first line that doesn't look like banner content."""
        assert self._reader is not None
        seen_v = seen_h = False
        while not (seen_v and seen_h):
            line = await self._reader.readline()
            if not line:
                return
            stripped = line.decode("ascii", errors="replace").rstrip()
            if stripped.startswith("V"):
                self.radio_version = stripped[1:]
                seen_v = True
            elif stripped.startswith("H"):
                self.client_handle = stripped[1:]
                seen_h = True
            else:
                # Unexpected — push back via a small queue isn't worth
                # it; just dispatch it as if from the read loop. In
                # practice the banner is V then H, nothing else.
                self._dispatch_line(stripped)
                return

    async def _read_loop(self) -> None:
        """Consume lines from the radio, dispatch R replies and S events."""
        assert self._reader is not None
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    logger.info("Flex: socket closed by radio")
                    break
                self._dispatch_line(line.decode("ascii", errors="replace").rstrip())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Flex: read loop crashed")
        finally:
            # Wake up any callers stuck on send().
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("Flex read loop ended"))
            self._pending.clear()

    def _dispatch_line(self, line: str) -> None:
        if not line:
            return
        # R<seq>|<hex_status>|<message>
        if line.startswith("R"):
            parts = line[1:].split("|", 2)
            try:
                seq = int(parts[0])
                status = int(parts[1], 16)
            except (ValueError, IndexError):
                logger.warning(f"Flex: malformed reply line: {line!r}")
                return
            message = parts[2] if len(parts) > 2 else ""
            fut = self._pending.pop(seq, None)
            if fut is not None and not fut.done():
                fut.set_result((status, message))
            return
        # S<handle>|<message>
        if line.startswith("S"):
            parts = line[1:].split("|", 1)
            handle = parts[0]
            message = parts[1] if len(parts) > 1 else ""
            if self.on_status is not None:
                try:
                    self.on_status(handle, message)
                except Exception:
                    logger.exception("Flex: on_status callback raised")
            return
        # V / H banner lines after the initial banner are unusual but
        # not destructive — log at debug.
        logger.debug(f"Flex: unhandled line: {line!r}")

    # ------------------------------------------------------------------
    # High-level convenience methods
    # ------------------------------------------------------------------
    #
    # All values match the SmartSDR API formats verbatim. Frequencies
    # in MHz (e.g. 14.020000), powers in 0-100 watts, modes as the
    # string the radio expects ("CWU", "CWL", "USB", "LSB", ...).

    async def set_slice_freq(self, slice_rx: int, freq_mhz: float) -> None:
        """Tune slice <slice_rx> to <freq_mhz>. Up to 15 significant
        digits; 6 dp covers Hz resolution to 5 MHz, fine for us."""
        await self.send(f"slice t {slice_rx} {freq_mhz:.6f}")

    async def set_slice_mode(self, slice_rx: int, mode: str) -> None:
        """Set slice <slice_rx> to mode (e.g. CWU, USB, LSB)."""
        await self.send(f"slice s {slice_rx} mode={mode}")

    async def set_tune_power(self, watts: int) -> None:
        """Set the tune-carrier output power in watts (0-100)."""
        if not 0 <= watts <= 100:
            raise ValueError(f"tune power must be 0-100 W, got {watts}")
        await self.send(f"transmit set tunepower={watts}")

    async def tune_carrier(self, on: bool) -> None:
        """Start (on=True) or stop (on=False) the built-in tune
        carrier. While on, the radio emits a CW carrier at the
        configured tune power on the active TX slice — exactly the
        clean steady drive the SPE's ATU wants."""
        await self.send(f"transmit tune {'on' if on else 'off'}")

    async def mox(self, on: bool) -> None:
        """Raw PTT (xmit 1/0). Not normally needed for the tune flow
        — `tune_carrier` is preferred because it handles mode +
        keying together — but provided for completeness."""
        await self.send(f"xmit {1 if on else 0}")

    async def subscribe(self, topic: str) -> None:
        """Subscribe to async updates. Common topics: ``slice 0``,
        ``transmit``, ``radio``. Updates arrive via ``on_status``."""
        await self.send(f"sub {topic} all")

    async def slice_list(self) -> str:
        """Read-only: return the slice list as the radio reports it.
        Useful for confirming connectivity without keying anything."""
        return await self.send("slice list")
