"""REST API Lambda handler for 5map WiFi environment mapping tool."""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")

MAPS_TABLE = os.environ.get("DYNAMODB_MAPS_TABLE", "environment_maps")
DEVICE_TABLE = os.environ.get("DYNAMODB_DEVICE_TABLE", "device_tracks")
PRESENCE_TABLE = os.environ.get("DYNAMODB_PRESENCE_TABLE", "presence_events")
SESSIONS_TABLE = os.environ.get("DYNAMODB_SESSIONS_TABLE", "sessions")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles DynamoDB Decimal types."""

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            if o % 1 == 0:
                return int(o)
            return float(o)
        return super().default(o)


def _response(status_code: int, body: Any) -> dict[str, Any]:
    """Build an API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def _get_path_param(event: dict[str, Any], param: str) -> str | None:
    """Extract a path parameter from the event."""
    params = event.get("pathParameters") or {}
    return params.get(param)


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    """Parse the JSON body from the event."""
    body = event.get("body")
    if not body:
        return {}
    if isinstance(body, str):
        return json.loads(body)
    return body


def get_map(event: dict[str, Any]) -> dict[str, Any]:
    """GET /api/map/{session_id} - Return map data for a session."""
    session_id = _get_path_param(event, "session_id")
    if not session_id:
        return _response(400, {"error": "session_id is required"})

    table = dynamodb.Table(MAPS_TABLE)
    try:
        result = table.query(KeyConditionExpression=Key("session_id").eq(session_id))
        return _response(200, {"session_id": session_id, "items": result.get("Items", [])})
    except Exception as e:
        return _response(500, {"error": f"Failed to query map data: {str(e)}"})


def get_devices(event: dict[str, Any]) -> dict[str, Any]:
    """GET /api/devices/{session_id} - Return device list for a session."""
    session_id = _get_path_param(event, "session_id")
    if not session_id:
        return _response(400, {"error": "session_id is required"})

    table = dynamodb.Table(DEVICE_TABLE)
    try:
        result = table.query(KeyConditionExpression=Key("session_id").eq(session_id))
        return _response(200, {"session_id": session_id, "devices": result.get("Items", [])})
    except Exception as e:
        return _response(500, {"error": f"Failed to query devices: {str(e)}"})


def get_presence(event: dict[str, Any]) -> dict[str, Any]:
    """GET /api/presence/{session_id} - Return presence events for a session."""
    session_id = _get_path_param(event, "session_id")
    if not session_id:
        return _response(400, {"error": "session_id is required"})

    table = dynamodb.Table(PRESENCE_TABLE)
    try:
        result = table.query(KeyConditionExpression=Key("session_id").eq(session_id))
        return _response(200, {"session_id": session_id, "events": result.get("Items", [])})
    except Exception as e:
        return _response(500, {"error": f"Failed to query presence events: {str(e)}"})


def list_sessions(event: dict[str, Any]) -> dict[str, Any]:
    """GET /api/sessions - List all audit sessions."""
    table = dynamodb.Table(SESSIONS_TABLE)
    try:
        result = table.scan()
        sessions = result.get("Items", [])
        sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        return _response(200, {"sessions": sessions})
    except Exception as e:
        return _response(500, {"error": f"Failed to list sessions: {str(e)}"})


def create_session(event: dict[str, Any]) -> dict[str, Any]:
    """POST /api/sessions - Create or join an audit session.

    Accepts optional session_id in body for idempotent creation.
    If session_id is provided and already exists, returns the existing session.
    """
    body = _parse_body(event)
    raw_sid = body.get("session_id")

    # Validate caller-supplied session_id format
    _VALID_SESSION_RE = re.compile(r'^[a-zA-Z0-9_#. -]{1,128}$')
    if raw_sid:
        if not _VALID_SESSION_RE.match(raw_sid):
            return _response(400, {"error": "Invalid session_id format"})

    session_id = raw_sid or str(uuid.uuid4())
    table = dynamodb.Table(SESSIONS_TABLE)

    # If caller provided a session_id, check if it already exists
    if raw_sid:
        try:
            existing = table.get_item(Key={"session_id": session_id})
            if "Item" in existing:
                return _response(200, {"session_id": session_id, "session": existing["Item"]})
        except Exception:
            pass

    item = {
        "session_id": session_id,
        "status": "active",
        "name": body.get("name", f"Session {session_id[:8]}"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if body.get("description"):
        item["description"] = body["description"]

    try:
        table.put_item(Item=item)
        return _response(201, {"session_id": session_id, "session": item})
    except Exception as e:
        return _response(500, {"error": f"Failed to create session: {str(e)}"})


def create_position(event: dict[str, Any]) -> dict[str, Any]:
    """POST /api/positions - Tag a position within a session."""
    body = _parse_body(event)

    session_id = body.get("session_id")
    x = body.get("x")
    y = body.get("y")
    label = body.get("label")

    if not session_id:
        return _response(400, {"error": "session_id is required"})
    if x is None or y is None:
        return _response(400, {"error": "x and y coordinates are required"})

    position_id = str(uuid.uuid4())
    item = {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "position_id": position_id,
        "x": Decimal(str(x)),
        "y": Decimal(str(y)),
        "label": label or "",
    }

    table = dynamodb.Table(MAPS_TABLE)
    try:
        table.put_item(Item=item)
        return _response(201, {"position_id": position_id, "position": item})
    except Exception as e:
        return _response(500, {"error": f"Failed to create position: {str(e)}"})


def ingest_scan(event: dict[str, Any]) -> dict[str, Any]:
    """POST /api/ingest - Ingest WiFi scan data from edge sensors.

    Accepts ESP32 scan results and writes directly to DynamoDB device tracks.
    Designed for lightweight edge devices (e.g. Pineapple) that can't use
    the full IoT Core -> Kinesis pipeline.
    """
    body = _parse_body(event)
    session_id = body.get("session_id")
    if not session_id:
        return _response(400, {"error": "session_id is required"})

    sensor_id = body.get("sensor_id", "pineapple-esp32")
    networks = body.get("networks", [])
    timestamp = body.get("timestamp", datetime.now(timezone.utc).isoformat())

    if not networks:
        return _response(400, {"error": "networks array is required"})

    device_table = dynamodb.Table(DEVICE_TABLE)
    presence_table = dynamodb.Table(PRESENCE_TABLE)
    written = 0

    for net in networks:
        mac = net.get("bssid", "")
        if not mac:
            continue

        ssid = net.get("ssid", "")
        rssi = net.get("rssi", -100)
        channel = net.get("channel", 0)
        auth = net.get("auth", "")
        randomized = net.get("randomized", False)

        # Classify device type
        device_type = "unknown"
        if auth == "OPEN" and rssi > -40:
            device_type = "ap"
        elif ssid and not randomized:
            device_type = "ap"
        elif randomized:
            device_type = "phone"

        # Determine band
        bandwidth = "5GHz" if channel > 14 else "2.4GHz"

        item = {
            "session_id": session_id,
            "mac_address": mac,
            "ssid": ssid or "-",
            "rssi_dbm": Decimal(str(rssi)),
            "channel": Decimal(str(channel)),
            "bandwidth": bandwidth,
            "device_type": device_type,
            "is_randomized_mac": randomized,
            "vendor": _lookup_vendor(mac),
            "source": sensor_id,
            "first_seen": timestamp,
            "last_seen": timestamp,
            "risk_score": Decimal("0"),
        }

        # Risk scoring
        if auth == "OPEN" and ssid:
            item["risk_score"] = Decimal("0.7")
        elif "WEP" in auth:
            item["risk_score"] = Decimal("0.5")

        try:
            # Use update to preserve first_seen
            device_table.update_item(
                Key={"session_id": session_id, "mac_address": mac},
                UpdateExpression=(
                    "SET rssi_dbm = :rssi, channel = :ch, ssid = :ssid, "
                    "bandwidth = :bw, device_type = :dt, is_randomized_mac = :rm, "
                    "vendor = :v, #src = :src, last_seen = :ls, risk_score = :rs, "
                    "first_seen = if_not_exists(first_seen, :fs) "
                    "ADD scan_count :one"
                ),
                ExpressionAttributeNames={"#src": "source"},
                ExpressionAttributeValues={
                    ":rssi": Decimal(str(rssi)),
                    ":ch": Decimal(str(channel)),
                    ":ssid": ssid or "-",
                    ":bw": bandwidth,
                    ":dt": device_type,
                    ":rm": randomized,
                    ":v": item["vendor"],
                    ":src": sensor_id,
                    ":ls": timestamp,
                    ":rs": item["risk_score"],
                    ":fs": timestamp,
                    ":one": 1,
                },
            )
            written += 1
        except Exception as e:
            logger.error("Failed to upsert device %s: %s", mac, e)

    # Write a presence event
    event_id = str(uuid.uuid4())
    try:
        presence_table.put_item(Item={
            "session_id": session_id,
            "event_key": f"{timestamp}#{event_id}",
            "timestamp": timestamp,
            "event_type": "scan",
            "sensor_id": sensor_id,
            "device_count": Decimal(str(len(networks))),
            "confidence": Decimal("0.9"),
            "zone": "scan-zone",
        })
    except Exception as e:
        logger.error("Failed to write presence event: %s", e)

    return _response(200, {"ingested": written, "total": len(networks)})


def _lookup_vendor(mac: str) -> str:
    """Simple OUI vendor lookup."""
    oui = mac[:8].upper()
    vendors = {
        "00:13:37": "Hak5 (Pineapple)",
        "24:5A:4C": "Huawei",
        "AC:B6:87": "BT",
        "D0:21:F9": "TP-Link",
        "FC:EC:DA": "TP-Link",
        "74:83:C2": "TP-Link",
        "9C:05:D6": "Ubiquiti",
        "D6:79:64": "Samsung",
        "3C:EF:42": "Apple",
        "54:22:E0": "Xiaomi",
    }
    return vendors.get(oui, "Unknown")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Main Lambda handler - routes requests to appropriate function."""
    # Support both API Gateway v1 (httpMethod/path) and v2 (requestContext.http)
    rc_http = event.get("requestContext", {}).get("http", {})
    http_method = rc_http.get("method", "") or event.get("httpMethod", "")
    path = event.get("rawPath", "") or event.get("path", "")

    if http_method == "OPTIONS":
        return _response(200, {})

    if http_method == "GET" and "/api/map/" in path:
        return get_map(event)

    if http_method == "GET" and "/api/devices/" in path:
        return get_devices(event)

    if http_method == "GET" and "/api/presence/" in path:
        return get_presence(event)

    if http_method == "GET" and path == "/api/sessions":
        return list_sessions(event)

    if http_method == "POST" and path == "/api/sessions":
        return create_session(event)

    if http_method == "POST" and path == "/api/positions":
        return create_position(event)

    if http_method == "POST" and path == "/api/ingest":
        return ingest_scan(event)

    return _response(404, {"error": "Not found", "path": path, "method": http_method})
