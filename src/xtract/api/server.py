"""WSGI HTTP server runner for xTRACT."""

from __future__ import annotations

import logging
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from xtract.api.app import create_app
from xtract.config import PlatformConfig
from xtract.core import Platform

logger = logging.getLogger("xtract.server")


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - signature defined by the stdlib
        logger.info("%s %s", self.address_string(), format % args)


def serve(config: PlatformConfig | None = None) -> None:
    """Start the HTTP server and the background job worker."""
    platform = Platform(config)
    cfg = platform.config
    if cfg.worker_enabled:
        platform.start_worker()
    app = create_app(platform)
    with make_server(cfg.host, cfg.port, app, ThreadingWSGIServer, QuietHandler) as httpd:
        engines = ", ".join(
            f"{e['engine_id']}={'on' if e['available'] else 'off'}"
            for e in platform.ocr.engine_status()
        )
        print(f"xTRACT running at http://{cfg.host}:{cfg.port}  (data: {cfg.data_dir})")
        print(f"OCR engines: {engines}")
        if cfg.host not in ("127.0.0.1", "localhost") and not platform.auth.auth_required:
            print("WARNING: listening on a public interface without authentication.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            platform.stop_worker()
