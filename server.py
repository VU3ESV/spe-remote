#!/usr/bin/env python3
"""SPE Amplifier Remote Control Server.

Modernized Python 3 port of the OH2GEK SPE remote control.
Communicates with SPE Expert amplifiers via serial and serves
a web-based remote control interface over WebSocket.
"""

import asyncio
import json
import logging
import signal
import sys
import time
from pathlib import Path

import tornado.ioloop

from spe.config import load_config
from spe.app import make_app
from spe.serial_handler import SerialHandler
from spe.power_control import PowerController
from spe.websocket_handler import AmplifierWebSocket
from spe.flex import FlexConnection, discover as flex_discover
from spe.tune_orchestrator import TuneOrchestrator


async def presence_heartbeat_loop(
    serial_handler: SerialHandler,
    interval: float,
    amp_alive_threshold: float,
) -> None:
    """Periodically broadcast a presence heartbeat to all WebSocket clients.

    Distinct from :attr:`PollingConfig.heartbeat`, which forces a state
    re-broadcast on the existing channel. This loop emits a separate
    ``{"heartbeat": True, "serial": "up"|"down", ...}`` message at a
    short, fixed cadence regardless of whether amp serial frames are
    flowing.

    ``serial`` reports **amp liveness**, not USB-link state. The FTDI
    cable stays USB-connected to the Pi even when the amp's CPU is dead,
    so ``serial_handler.connected`` would lie. Instead, ``serial: "up"``
    iff a CSV state frame OR an RCU display frame has been parsed within
    ``amp_alive_threshold`` seconds. CSV alone is insufficient because
    the amp slows CSV emission in STANDBY below the heartbeat threshold,
    which would otherwise produce false serial:"down" → POWERED OFF
    banners on clients while the amp is fine.

    Two consequences clients depend on:

    1. They learn within ``interval + amp_alive_threshold`` seconds that
       the amp went off — the serial-down transition no longer requires
       a fresh WS connect + snapshot to see.
    2. They see *something* flowing every ``interval`` seconds, which
       prevents heartbeat-based client reconnect loops (e.g. MacExpert
       reconnecting every 5 s when no msgs arrive).
    """
    logger = logging.getLogger("spe.heartbeat")
    while True:
        try:
            await asyncio.sleep(interval)
            alive = min(
                serial_handler.last_state_age,
                serial_handler.last_rcu_age,
            ) < amp_alive_threshold
            msg = json.dumps({
                "heartbeat": True,
                "serial": "up" if alive else "down",
                "ts": time.time(),
                "clients": len(AmplifierWebSocket.clients),
            })
            AmplifierWebSocket.broadcast_raw(msg)
        except asyncio.CancelledError:
            logger.info("presence_heartbeat_loop cancelled")
            break
        except Exception:
            logger.exception("presence_heartbeat_loop error; continuing")


def main() -> None:
    # Distinguish "user passed a path" from "no arg, fall back to default":
    # if a path is given explicitly it must exist, so a typo or copy-pasted
    # placeholder fails loudly instead of silently running on defaults.
    # Bare invocation with no arg keeps the original tolerant behaviour
    # (load_config logs a warning and uses defaults if config.yaml is absent).
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        if not Path(config_path).exists():
            print(
                f"error: config file {config_path!r} not found",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        config_path = "config.yaml"
    config = load_config(config_path)

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("spe")

    serial_handler = SerialHandler(
        serial_config=config.serial,
        polling_config=config.polling,
        on_state_update=AmplifierWebSocket.broadcast_state,
        on_rcu_frame=AmplifierWebSocket.broadcast_rcu_frame,
        temperature_unit=config.amp.temperature_unit,
    )

    power_controller = PowerController(
        serial_config=config.serial,
        serial_handler=serial_handler,
    )

    # Optional Flex 6000 control — Phase 2 of the band-sweep work.
    # When flex.enabled is true, connect to SmartSDR's TCP API and
    # create a tune orchestrator that can drive an ATU tune cycle via
    # the (SPE TUNE keycode + Flex carrier) combination. flex.host
    # picks the radio: set explicitly to an IP, or leave empty to
    # auto-discover via the SmartSDR UDP broadcast on port 4992.
    # Disabled by default; spe-remote behaves exactly as before when
    # the section is omitted from config.yaml.
    flex_connection = None
    tune_orchestrator = None
    if config.flex.enabled:
        flex_host = config.flex.host
        if not flex_host:
            logger.info(
                "Flex: flex.host empty — listening for SmartSDR discovery "
                "broadcast on UDP 4992 (up to 5s)…"
            )
            # Run discovery synchronously here; spe-remote startup blocks
            # on it for a few seconds at most. Doing this on the main
            # loop is fine because nothing else is running yet — the
            # serial reader / tornado IOLoop haven't started.
            try:
                discovery = asyncio.get_event_loop().run_until_complete(
                    flex_discover()
                )
            except Exception:
                logger.exception("Flex discovery raised; skipping")
                discovery = None
            if discovery and discovery.get("ip"):
                flex_host = discovery["ip"]
                logger.info(
                    f"Flex: discovered {discovery.get('model','?')} "
                    f"\"{discovery.get('nickname','?')}\" "
                    f"({discovery.get('callsign','?')}) at {flex_host}"
                )
            else:
                logger.warning(
                    "Flex: discovery timed out and flex.host is empty — "
                    "Flex disabled for this session"
                )
        if flex_host:
            flex_connection = FlexConnection(flex_host, config.flex.port)
            tune_orchestrator = TuneOrchestrator(
                serial_handler=serial_handler,
                flex=flex_connection,
                config=config.flex,
                on_status=AmplifierWebSocket.broadcast_tune_event,
            )
            logger.info(
                f"Flex control enabled: host={flex_host}:{config.flex.port} "
                f"slice={config.flex.slice_rx} "
                f"tune_power={config.flex.tune_power_watts}W"
            )

    AmplifierWebSocket.configure(
        serial_handler=serial_handler,
        power_controller=power_controller,
        tune_orchestrator=tune_orchestrator,
        heartbeat=config.polling.heartbeat,
    )

    app = make_app()
    app.listen(config.server.port, address=config.server.host)

    logger.info(
        f"Server listening on http://{config.server.host}:{config.server.port}/"
    )
    logger.info(f"Serial port: {config.serial.port} @ {config.serial.baudrate} baud")

    loop = asyncio.get_event_loop()

    # Graceful shutdown
    def shutdown(sig, frame):
        logger.info("Shutting down...")
        # Schedule serial handler stop on the asyncio loop
        try:
            loop.call_soon_threadsafe(loop.create_task, serial_handler.stop())
        except Exception:
            # Fallback: ensure a stop task is scheduled
            loop.call_soon_threadsafe(lambda: loop.create_task(serial_handler.stop()))

        # Stop Tornado IOLoop in a signal-safe way
        tornado.ioloop.IOLoop.current().add_callback_from_signal(
            tornado.ioloop.IOLoop.current().stop
        )

        # Also stop the asyncio loop after pending tasks complete
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start serial handler + presence-heartbeat as async tasks
    serial_task = loop.create_task(serial_handler.start())
    heartbeat_task = loop.create_task(
        presence_heartbeat_loop(
            serial_handler,
            config.polling.presence_heartbeat,
            config.polling.amp_alive_threshold,
        )
    )
    logger.info(
        f"Presence heartbeat every {config.polling.presence_heartbeat:.1f}s "
        f"(amp_alive_threshold={config.polling.amp_alive_threshold:.1f}s)"
    )

    # If a Flex is configured, kick off a connect task. Failure here
    # shouldn't take down the whole server — clients can still talk to
    # the amp; the tune commands will surface a clear error message
    # back through the WS instead.
    flex_task = None
    if flex_connection is not None:
        async def _flex_connect():
            try:
                await flex_connection.connect()
                logger.info(
                    f"Flex: connected (version={flex_connection.radio_version!r}, "
                    f"handle={flex_connection.client_handle!r})"
                )
            except Exception:
                logger.exception(
                    "Flex: initial connect failed; tune_single will retry "
                    "on each command"
                )
        flex_task = loop.create_task(_flex_connect())

    try:
        tornado.ioloop.IOLoop.current().start()
    finally:
        # Ensure background tasks are cancelled if still running
        cleanup_tasks = [serial_task, heartbeat_task]
        if flex_task is not None:
            cleanup_tasks.append(flex_task)
        for task in cleanup_tasks:
            try:
                if not task.done():
                    task.cancel()
            except Exception:
                pass

        # Close the Flex socket so we don't leak a half-open TCP session.
        if flex_connection is not None:
            try:
                loop.run_until_complete(flex_connection.close())
            except Exception:
                logger.exception("Error while closing Flex connection")

        # Make a best-effort to stop serial handler and close resources
        try:
            loop.run_until_complete(serial_handler.stop())
        except Exception:
            logger.exception("Error while stopping serial handler")

        logger.info("Server stopped")


if __name__ == "__main__":
    main()
