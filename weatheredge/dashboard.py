#!/usr/bin/env python3
"""WeatherEdge live weather-trading cockpit."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import sensor_api

PORT = 8420
PAGE = r''''''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/"):
            api = sensor_api.handle(self.path)
            if api:
                status, payload = api
                data = json.dumps(payload, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
        if self.path == "/" or self.path.startswith("/?"):
            data = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_):
        pass

if __name__ == "__main__":
    print(f"WeatherEdge Live Cockpit: http://localhost:{PORT}")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
