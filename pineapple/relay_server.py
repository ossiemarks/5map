#!/usr/bin/env python3
"""Simple HTTP relay - runs on laptop, forwards Pineapple requests to AWS API Gateway."""

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen

API_URL = "https://dqbhaw5wki.execute-api.eu-west-2.amazonaws.com/api/ingest"
AUTH_TOKEN = "mvp-token"


class RelayHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        req = Request(API_URL, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {AUTH_TOKEN}")

        try:
            with urlopen(req, timeout=10) as resp:
                result = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(result)
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, fmt, *args):
        print(f"[RELAY] {fmt % args}", flush=True)


def main():
    port = 8888
    server = HTTPServer(("0.0.0.0", port), RelayHandler)
    print(f"Relay listening on 0.0.0.0:{port} -> {API_URL}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
