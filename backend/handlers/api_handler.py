"""REST API Lambda handler for 5map WiFi environment mapping tool."""

import json
import os
import uuid
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


def create_session(event: dict[str, Any]) -> dict[str, Any]:
    """POST /api/sessions - Create a new audit session."""
    body = _parse_body(event)
    session_id = str(uuid.uuid4())

    item = {
        "session_id": session_id,
        "status": "active",
        "name": body.get("name", f"Session {session_id[:8]}"),
        "created_at": str(uuid.uuid1().time),
    }

    if body.get("description"):
        item["description"] = body["description"]

    table = dynamodb.Table(SESSIONS_TABLE)
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
        "position_id": position_id,
        "x": Decimal(str(x)),
        "y": Decimal(str(y)),
        "label": label or "",
    }

    table = dynamodb.Table(SESSIONS_TABLE)
    try:
        table.put_item(Item=item)
        return _response(201, {"position_id": position_id, "position": item})
    except Exception as e:
        return _response(500, {"error": f"Failed to create position: {str(e)}"})


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

    if http_method == "POST" and path == "/api/sessions":
        return create_session(event)

    if http_method == "POST" and path == "/api/positions":
        return create_position(event)

    return _response(404, {"error": "Not found", "path": path, "method": http_method})
