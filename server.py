#!/usr/bin/env python3
"""SPE Amplifier Remote Control Server.

Modernized Python 3 port of the OH2GEK SPE remote control.
Communicates with SPE Expert amplifiers via serial and serves
a web-based remote control interface over WebSocket.
"""

import asyncio
import logging
import signal
import sys

import tornado.ioloop

from spe.config import load_config
from spe.app import make_app
from spe.serial_handler import SerialHandler
from spe.websocket_handler import AmplifierWebSocket


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
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
    )

    AmplifierWebSocket.configure(
        serial_handler=serial_handler,
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
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start serial handler as async task
    serial_task = loop.create_task(serial_handler.start())

    try:
        tornado.ioloop.IOLoop.current().start()
    finally:
        loop.run_until_complete(serial_handler.stop())
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
