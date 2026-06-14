#!/usr/bin/env python3

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


HOST = "0.0.0.0"
PORT = 8090
EVENTS_PATH = Path("/tmp/audit_events.jsonl")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def append_event(event: dict[str, Any]) -> None:
    with EVENTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def read_events(limit: int = 100) -> list[dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []

    lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
    events = []

    for line in lines[-limit:]:
        try:
            events.append(json.loads(line))
        except Exception:
            pass

    return events


class AuditHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: dict | list) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}

        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "service": "audit-collector",
                "events": len(read_events(limit=100000)),
            })
            return

        if self.path.startswith("/events"):
            self._send_json(200, read_events(limit=100))
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            if self.path != "/audit":
                self._send_json(404, {"error": "not found"})
                return

            event = self._read_json()
            event.setdefault("ts", now())
            event.setdefault("source", "unknown")

            append_event(event)

            self._send_json(200, {
                "ok": True,
                "stored": event,
            })

        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    print(f"[audit] listening on http://{HOST}:{PORT}")
    server = HTTPServer((HOST, PORT), AuditHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
