"""Tornado application setup with static file serving."""

import os
import logging

import tornado.web

from spe.websocket_handler import AmplifierWebSocket

logger = logging.getLogger(__name__)

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


def make_app() -> tornado.web.Application:
    return tornado.web.Application([
        (r"/ws", AmplifierWebSocket),
        (r"/(.*)", tornado.web.StaticFileHandler, {
            "path": WEB_DIR,
            "default_filename": "index.html",
        }),
    ])
