"""WebSocket Lambda handler for 5map WiFi environment mapping tool."""

import json
import os
import time
from typing import Any

import boto3

dynamodb = boto3.resource("dynamodb")

CONNECTIONS_TABLE = os.environ.get("DYNAMODB_CONNECTIONS_TABLE", "connections")


def _get_connections_table():
    """Get the DynamoDB connections table resource."""
    return dynamodb.Table(CONNECTIONS_TABLE)


def handle_connect(event: dict[str, Any]) -> dict[str, Any]:
    """Handle $connect - store connection in DynamoDB."""
    connection_id = event["requestContext"]["connectionId"]
    query_params = event.get("queryStringParameters") or {}
    token = query_params.get("token", "")

    if not token:
        return {"statusCode": 401, "body": "Unauthorized: token required"}

    table = _get_connections_table()
    try:
        item = {
            "connection_id": connection_id,
            "connected_at": int(time.time()),
            "token": token,
        }

        session_id = query_params.get("session_id")
        if session_id:
            item["session_id"] = session_id

        table.put_item(Item=item)
        return {"statusCode": 200, "body": "Connected"}
    except Exception as e:
        return {"statusCode": 500, "body": f"Connection failed: {str(e)}"}


def handle_disconnect(event: dict[str, Any]) -> dict[str, Any]:
    """Handle $disconnect - remove connection from DynamoDB."""
    connection_id = event["requestContext"]["connectionId"]

    table = _get_connections_table()
    try:
        table.delete_item(Key={"connection_id": connection_id})
        return {"statusCode": 200, "body": "Disconnected"}
    except Exception as e:
        return {"statusCode": 500, "body": f"Disconnect failed: {str(e)}"}


def handle_default(event: dict[str, Any]) -> dict[str, Any]:
    """Handle $default - process incoming WebSocket messages."""
    connection_id = event["requestContext"]["connectionId"]
    body = event.get("body", "{}")

    try:
        message = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "Invalid JSON"}

    action = message.get("action", "")

    if action == "subscribe":
        return _handle_subscribe(connection_id, message)

    if action == "unsubscribe":
        return _handle_unsubscribe(connection_id, message)

    if action == "ping":
        return {"statusCode": 200, "body": json.dumps({"action": "pong"})}

    return {"statusCode": 200, "body": json.dumps({"action": "ack", "received": action})}


def _handle_subscribe(connection_id: str, message: dict[str, Any]) -> dict[str, Any]:
    """Subscribe a connection to session updates."""
    session_id = message.get("session_id")
    if not session_id:
        return {"statusCode": 400, "body": json.dumps({"error": "session_id required"})}

    table = _get_connections_table()
    try:
        table.update_item(
            Key={"connection_id": connection_id},
            UpdateExpression="SET session_id = :sid",
            ExpressionAttributeValues={":sid": session_id},
        )
        return {
            "statusCode": 200,
            "body": json.dumps({"action": "subscribed", "session_id": session_id}),
        }
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _handle_unsubscribe(connection_id: str, message: dict[str, Any]) -> dict[str, Any]:
    """Unsubscribe a connection from session updates."""
    table = _get_connections_table()
    try:
        table.update_item(
            Key={"connection_id": connection_id},
            UpdateExpression="REMOVE session_id",
        )
        return {
            "statusCode": 200,
            "body": json.dumps({"action": "unsubscribed"}),
        }
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Main WebSocket Lambda handler - routes by route key."""
    route_key = event.get("requestContext", {}).get("routeKey", "$default")

    if route_key == "$connect":
        return handle_connect(event)

    if route_key == "$disconnect":
        return handle_disconnect(event)

    return handle_default(event)
