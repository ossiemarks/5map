#!/usr/bin/env python3
"""5map Dashboard Server - Local proxy to DynamoDB with live Pineapple capture."""

import json
import os
import time
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import boto3

REGION = "eu-west-2"
SESSION = os.environ.get("SESSION_ID", "e8076d73-ce66-4ed8-85fb-ef715f8844cf")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
device_table = dynamodb.Table("fivemap-prod-device-tracks")
presence_table = dynamodb.Table("fivemap-prod-presence-events")
maps_table = dynamodb.Table("fivemap-prod-environment-maps")
sessions_table = dynamodb.Table("fivemap-prod-sessions")


def query_devices(session_id):
    resp = device_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("session_id").eq(session_id)
    )
    return resp.get("Items", [])


def query_presence(session_id):
    resp = presence_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("session_id").eq(session_id)
    )
    return resp.get("Items", [])


def query_map(session_id):
    resp = maps_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("session_id").eq(session_id)
    )
    return resp.get("Items", [])


def decimal_default(obj):
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self._handle_api(path)
        else:
            super().do_GET()

    def _handle_api(self, path):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        if "/api/devices" in path:
            devices = query_devices(SESSION)
            for d in devices:
                d["risk_score"] = float(d.get("risk_score", 0))
                d["rssi_dbm"] = int(d.get("rssi_dbm", -100))
            data = {"session_id": SESSION, "devices": devices}

        elif "/api/presence" in path:
            events = query_presence(SESSION)
            for e in events:
                e["confidence"] = float(e.get("confidence", 0))
                e["device_count"] = int(e.get("device_count", 0))
            data = {"session_id": SESSION, "events": events}

        elif "/api/map" in path:
            items = query_map(SESSION)
            for item in items:
                for field in ("heatmap", "walls", "grid_bounds"):
                    val = item.get(field)
                    if isinstance(val, str):
                        try:
                            item[field] = json.loads(val)
                        except json.JSONDecodeError:
                            pass
                item["confidence"] = float(item.get("confidence", 0))
            data = {"session_id": SESSION, "items": items}

        elif "/api/sessions" in path:
            data = {"sessions": [{"session_id": SESSION, "name": "Live Audit"}]}

        else:
            data = {"error": "not found"}

        self.wfile.write(json.dumps(data, default=decimal_default).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def log_message(self, format, *args):
        print(format % args)


def main():
    port = 8080
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print(f"5map Dashboard: http://localhost:{port}")
    print(f"Session: {SESSION}")
    print(f"DynamoDB region: {REGION}")
    print("Press Ctrl+C to stop")

    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
