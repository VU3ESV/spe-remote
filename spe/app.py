"""Tornado application setup with static file serving."""

import os
import logging

import tornado.web

from spe.websocket_handler import AmplifierWebSocket

logger = logging.getLogger(__name__)

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


class NoCacheStaticFileHandler(tornado.web.StaticFileHandler):
    """StaticFileHandler that always asks the browser to revalidate.

    We don't have a build pipeline that fingerprints filenames, so without
    this the browser happily serves stale index.html / app.js / style.css
    after a ``git pull``. ``no-cache`` does NOT mean "do not cache" — it
    means "cache, but always revalidate before using". Combined with
    Tornado's automatic ETag / Last-Modified handling, unchanged assets
    come back as cheap 304 Not Modified responses; changed ones are
    re-fetched. Net effect: users always get the latest UI without a
    manual hard-reload, with negligible bandwidth overhead on a LAN.
    """

    def set_extra_headers(self, path: str) -> None:
        self.set_header("Cache-Control", "no-cache, must-revalidate")


def make_app() -> tornado.web.Application:
    return tornado.web.Application([
        (r"/ws", AmplifierWebSocket),
        (r"/(.*)", NoCacheStaticFileHandler, {
            "path": WEB_DIR,
            "default_filename": "index.html",
        }),
    ])
