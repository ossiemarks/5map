"""REST API Lambda handler for 5map WiFi environment mapping tool."""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3

logger = logging.getLogger(__name__)
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
    """POST /api/positions - Tag a position with RSSI snapshot."""
    body = _parse_body(event)

    session_id = body.get("session_id")
    x = body.get("x")
    y = body.get("y")
    label = body.get("label")
    rssi_snapshot = body.get("rssi_snapshot", [])

    if not session_id:
        return _response(400, {"error": "session_id is required"})
    if x is None or y is None:
        return _response(400, {"error": "x and y coordinates are required"})

    position_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    rssi_values = [float(r.get("rssi_dbm", -100)) for r in rssi_snapshot if r.get("rssi_dbm")]

    item = {
        "session_id": session_id,
        "timestamp": timestamp,
        "position_id": position_id,
        "x": Decimal(str(x)),
        "y": Decimal(str(y)),
        "label": label or "",
        "rssi_snapshot": json.dumps(rssi_snapshot),
        "rssi_values": json.dumps(rssi_values),
        "device_count": len(rssi_snapshot),
    }

    table = dynamodb.Table(MAPS_TABLE)
    try:
        table.put_item(Item=item)

        result = table.query(KeyConditionExpression=Key("session_id").eq(session_id))
        positions = result.get("Items", [])
        position_count = len([p for p in positions if "x" in p and "rssi_values" in p])

        response_body = {"position_id": position_id, "position_count": position_count}

        if position_count >= 3:
            _generate_and_store_map(session_id, positions)
            response_body["map_generated"] = True

        return _response(201, response_body)
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


def _generate_and_store_map(session_id: str, positions: list[dict]) -> None:
    """Run EnvironmentMapper and store result + push via WebSocket."""
    try:
        from ml.models.env_mapper import EnvironmentMapper
    except ImportError:
        logger.warning("env_mapper not available, skipping map generation")
        return

    pos_data = []
    for p in positions:
        if "x" not in p or "rssi_values" not in p:
            continue
        try:
            rssi_vals = json.loads(p["rssi_values"]) if isinstance(p["rssi_values"], str) else p["rssi_values"]
            pos_data.append({
                "x": float(p["x"]),
                "y": float(p["y"]),
                "rssi_values": [float(v) for v in rssi_vals],
            })
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    if len(pos_data) < 3:
        return

    try:
        mapper = EnvironmentMapper(grid_size=30)
        mapper.fit(pos_data)
        result = mapper.predict_heatmap()
    except Exception as e:
        logger.error("EnvironmentMapper failed: %s", e)
        return

    table = dynamodb.Table(MAPS_TABLE)
    timestamp = datetime.now(timezone.utc).isoformat()
    map_item = {
        "session_id": session_id,
        "timestamp": f"map#{timestamp}",
        "type": "heatmap",
        "heatmap": json.dumps(result["heatmap"]),
        "walls": json.dumps(result["walls"]),
        "grid_bounds": json.dumps(result["grid_bounds"]),
        "confidence": Decimal(str(round(result["confidence"], 4))),
        "position_count": len(pos_data),
    }
    try:
        table.put_item(Item=map_item)
    except Exception as e:
        logger.error("Failed to store map: %s", e)
        return

    _push_ws_map_update(session_id, result, timestamp)


def _push_ws_map_update(session_id: str, result: dict, timestamp: str) -> None:
    """Push map update to all WebSocket connections subscribed to this session."""
    ws_endpoint = os.environ.get("WEBSOCKET_API_ENDPOINT", "")
    if not ws_endpoint:
        return

    connections_table = dynamodb.Table(
        os.environ.get("DYNAMODB_CONNECTIONS_TABLE", "connections")
    )

    try:
        resp = connections_table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("session_id").eq(session_id)
        )
    except Exception:
        return

    if not resp.get("Items"):
        return

    endpoint = ws_endpoint.replace("wss://", "https://").rstrip("/")
    client = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)

    payload = json.dumps({
        "type": "map_update",
        "session_id": session_id,
        "data": {
            "heatmap": result["heatmap"],
            "walls": result["walls"],
            "grid_bounds": result["grid_bounds"],
            "confidence": result["confidence"],
            "updated_at": timestamp,
        },
    })

    for conn in resp["Items"]:
        try:
            client.post_to_connection(
                ConnectionId=conn["connection_id"],
                Data=payload.encode("utf-8"),
            )
        except client.exceptions.GoneException:
            connections_table.delete_item(Key={"connection_id": conn["connection_id"]})
        except Exception:
            pass


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
