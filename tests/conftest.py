import importlib.util
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cli(tmp_path):
    """cli.py loaded as a module with a minimal CONFIG pointing into tmp_path."""
    spec = importlib.util.spec_from_file_location("cli_under_test", ROOT / "cli.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cookie = tmp_path / "cookie.txt"
    cookie.write_text("sid=abc", encoding="utf-8")
    module.CONFIG = {
        "account_name": "acc",
        "base_url": "",
        "data_dir": str(tmp_path / "data"),
        "cache_dir": str(tmp_path / "cache"),
        "cache_auto_age_minutes": 10,
        "cookie_file": str(cookie),
        "user_id_file": str(tmp_path / "user_id.txt"),
        "timeout": 5,
        "headers": {},
    }
    return module


class FakeServer:
    """Local HTTP server; `handler(req) -> (status, json_payload, extra_headers)`."""

    def __init__(self):
        self.requests = []
        self.handler = lambda req: (200, [], {})
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                parsed = urllib.parse.urlparse(self.path)
                req = {
                    "method": self.command,
                    "path": parsed.path,
                    "query": urllib.parse.parse_qs(parsed.query),
                    "body": json.loads(self.rfile.read(length)) if length else None,
                    "headers": dict(self.headers),
                }
                outer.requests.append(req)
                status, payload, headers = outer.handler(req)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _handle

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    srv = FakeServer()
    yield srv
    srv.close()
