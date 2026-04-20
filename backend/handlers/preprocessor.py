"""Lambda preprocessor for 5map WiFi environment mapping.

Triggered by Kinesis Data Stream. Receives batches of RSSI observation
windows from WiFi Pineapple sensors (via IoT Core -> Kinesis), validates,
enriches, archives to S3, stores tracking data in DynamoDB, sends real-time
WebSocket updates, and optionally invokes SageMaker for inference.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ.get("S3_BUCKET", "")
DYNAMODB_DEVICE_TABLE = os.environ.get("DYNAMODB_DEVICE_TABLE", "")
DYNAMODB_PRESENCE_TABLE = os.environ.get("DYNAMODB_PRESENCE_TABLE", "")
WEBSOCKET_API_ENDPOINT = os.environ.get("WEBSOCKET_API_ENDPOINT", "")
SAGEMAKER_ENDPOINT = os.environ.get("SAGEMAKER_ENDPOINT", "")

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
sagemaker_runtime = boto3.client("sagemaker-runtime")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for Kinesis trigger.

    Args:
        event: Kinesis event containing base64-encoded records.
        context: Lambda context object.

    Returns:
        Processing summary with success/failure counts.
    """
    records = event.get("Records", [])
    logger.info("Received %d Kinesis records", len(records))

    results: dict[str, int] = {"processed": 0, "failed": 0, "skipped": 0}

    for record in records:
        try:
            payload = _decode_record(record)
            if payload is None:
                results["failed"] += 1
                continue

            if not _validate(payload):
                results["failed"] += 1
                continue

            if not payload.get("observations"):
                logger.info(
                    "Skipping record with zero observations: sensor_id=%s",
                    payload.get("sensor_id"),
                )
                results["skipped"] += 1
                continue

            enriched = _enrich(payload)
            _archive_to_s3(enriched)
            _store_device_tracks(enriched)
            _store_presence_events(enriched)
            _send_websocket_update(enriched)
            _invoke_sagemaker(enriched)

            results["processed"] += 1

        except Exception:
            logger.exception(
                "Unexpected error processing record: %s",
                record.get("kinesis", {}).get("sequenceNumber", "unknown"),
            )
            results["failed"] += 1

    logger.info("Processing complete: %s", results)
    return results


def _decode_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Decode a base64-encoded Kinesis record payload.

    Args:
        record: Raw Kinesis record.

    Returns:
        Decoded JSON payload or None on failure.
    """
    try:
        raw_data = record["kinesis"]["data"]
        decoded = base64.b64decode(raw_data).decode("utf-8")
        return json.loads(decoded)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        logger.error("Failed to decode record: %s", exc)
        return None


def _validate(payload: dict[str, Any]) -> bool:
    """Validate required fields in observation window.

    Args:
        payload: Decoded observation window.

    Returns:
        True if valid, False otherwise.
    """
    if not payload.get("sensor_id"):
        logger.warning("Record missing sensor_id, rejecting")
        return False

    if not payload.get("timestamp"):
        logger.warning("Record missing timestamp, rejecting")
        return False

    return True


def _enrich(payload: dict[str, Any]) -> dict[str, Any]:
    """Enrich observation window with computed metadata.

    Args:
        payload: Validated observation window.

    Returns:
        Enriched payload with additional fields.
    """
    observations = payload.get("observations", [])
    observation_count = len(observations)

    avg_rssi = 0.0
    if observation_count > 0:
        total_rssi = sum(obs.get("rssi_dbm", 0) for obs in observations)
        avg_rssi = round(total_rssi / observation_count, 2)

    payload["received_at"] = datetime.now(timezone.utc).isoformat()
    payload["observation_count"] = observation_count
    payload["avg_rssi"] = avg_rssi
    payload["session_id"] = _generate_session_id(payload)

    return payload


def _generate_session_id(payload: dict[str, Any]) -> str:
    """Generate a deterministic session ID from sensor and timestamp.

    Uses the date portion of the timestamp combined with sensor_id
    to group observations into daily sessions per sensor.

    Args:
        payload: Enriched observation window.

    Returns:
        Session identifier string.
    """
    timestamp_str = payload.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        date_part = dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        date_part = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sensor_id = payload.get("sensor_id", "unknown")
    return f"{sensor_id}#{date_part}"


def _archive_to_s3(payload: dict[str, Any]) -> None:
    """Archive validated record to S3 as JSON lines.

    Path: s3://{bucket}/raw/{date}/{sensor_id}/{timestamp}.jsonl

    Args:
        payload: Enriched observation window.
    """
    if not S3_BUCKET:
        logger.warning("S3_BUCKET not configured, skipping archive")
        return

    timestamp_str = payload.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        date_path = dt.strftime("%Y/%m/%d")
        ts_filename = dt.strftime("%Y%m%dT%H%M%S%f")
    except (ValueError, AttributeError):
        now = datetime.now(timezone.utc)
        date_path = now.strftime("%Y/%m/%d")
        ts_filename = now.strftime("%Y%m%dT%H%M%S%f")

    sensor_id = payload.get("sensor_id", "unknown")
    key = f"raw/{date_path}/{sensor_id}/{ts_filename}.jsonl"

    body = json.dumps(payload, default=str) + "\n"

    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/jsonl",
        )
        logger.info("Archived to s3://%s/%s", S3_BUCKET, key)
    except ClientError as exc:
        logger.error("Failed to archive to S3: %s", exc)


def _store_device_tracks(payload: dict[str, Any]) -> None:
    """Store unique MAC observations in device_tracks DynamoDB table.

    PK=session_id, SK=mac

    Args:
        payload: Enriched observation window.
    """
    if not DYNAMODB_DEVICE_TABLE:
        logger.warning("DYNAMODB_DEVICE_TABLE not configured, skipping")
        return

    table = dynamodb.Table(DYNAMODB_DEVICE_TABLE)
    session_id = payload.get("session_id", "")
    timestamp = payload.get("timestamp", "")
    sensor_id = payload.get("sensor_id", "")
    position = payload.get("position", {})

    seen_macs: set[str] = set()

    for obs in payload.get("observations", []):
        mac = obs.get("mac", "")
        if not mac or mac in seen_macs:
            continue
        seen_macs.add(mac)

        item = {
            "session_id": session_id,
            "mac": mac,
            "last_seen": timestamp,
            "sensor_id": sensor_id,
            "rssi_dbm": obs.get("rssi_dbm"),
            "channel": obs.get("channel"),
            "ssid": obs.get("ssid", ""),
            "is_randomized_mac": obs.get("is_randomized_mac", False),
            "count": obs.get("count", 1),
            "position": position,
        }

        try:
            table.put_item(Item=_sanitize_dynamodb_item(item))
        except ClientError as exc:
            logger.error("Failed to write device track for mac=%s: %s", mac, exc)


def _store_presence_events(payload: dict[str, Any]) -> None:
    """Store presence events in DynamoDB presence_events table.

    PK=session_id, SK=timestamp#event_id

    Args:
        payload: Enriched observation window.
    """
    if not DYNAMODB_PRESENCE_TABLE:
        logger.warning("DYNAMODB_PRESENCE_TABLE not configured, skipping")
        return

    table = dynamodb.Table(DYNAMODB_PRESENCE_TABLE)
    session_id = payload.get("session_id", "")
    timestamp = payload.get("timestamp", "")
    event_id = str(uuid.uuid4())
    sort_key = f"{timestamp}#{event_id}"

    item = {
        "session_id": session_id,
        "timestamp_event_id": sort_key,
        "timestamp": timestamp,
        "sensor_id": payload.get("sensor_id", ""),
        "observation_count": payload.get("observation_count", 0),
        "avg_rssi": str(payload.get("avg_rssi", 0)),
        "unique_macs": len(
            {obs.get("mac") for obs in payload.get("observations", []) if obs.get("mac")}
        ),
        "position": payload.get("position", {}),
        "received_at": payload.get("received_at", ""),
    }

    try:
        table.put_item(Item=_sanitize_dynamodb_item(item))
    except ClientError as exc:
        logger.error("Failed to write presence event: %s", exc)


def _send_websocket_update(payload: dict[str, Any]) -> None:
    """Send real-time update via API Gateway WebSocket.

    Posts to the connections management endpoint.

    Args:
        payload: Enriched observation window.
    """
    if not WEBSOCKET_API_ENDPOINT:
        logger.debug("WEBSOCKET_API_ENDPOINT not configured, skipping")
        return

    endpoint_url = WEBSOCKET_API_ENDPOINT.rstrip("/")
    apigw_management = boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=endpoint_url,
    )

    update_message = json.dumps(
        {
            "type": "observation_update",
            "sensor_id": payload.get("sensor_id"),
            "timestamp": payload.get("timestamp"),
            "observation_count": payload.get("observation_count"),
            "avg_rssi": payload.get("avg_rssi"),
            "unique_macs": len(
                {obs.get("mac") for obs in payload.get("observations", []) if obs.get("mac")}
            ),
            "position": payload.get("position"),
        },
        default=str,
    ).encode("utf-8")

    connection_ids = _get_active_connections()

    for connection_id in connection_ids:
        try:
            apigw_management.post_to_connection(
                ConnectionId=connection_id,
                Data=update_message,
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code == "GoneException":
                logger.info("Stale connection removed: %s", connection_id)
            else:
                logger.error(
                    "Failed to send WebSocket update to %s: %s",
                    connection_id,
                    exc,
                )


def _get_active_connections() -> list[str]:
    """Retrieve active WebSocket connection IDs.

    In production, these would be stored in DynamoDB when clients connect.
    This implementation checks for a connections table.

    Returns:
        List of active connection IDs.
    """
    connections_table_name = os.environ.get("WEBSOCKET_CONNECTIONS_TABLE", "")
    if not connections_table_name:
        return []

    try:
        table = dynamodb.Table(connections_table_name)
        response = table.scan(ProjectionExpression="connection_id")
        return [
            item["connection_id"]
            for item in response.get("Items", [])
            if item.get("connection_id")
        ]
    except ClientError as exc:
        logger.error("Failed to scan connections table: %s", exc)
        return []


def _invoke_sagemaker(payload: dict[str, Any]) -> None:
    """Invoke SageMaker endpoint for inference if configured.

    Args:
        payload: Enriched observation window.
    """
    if not SAGEMAKER_ENDPOINT:
        logger.debug("SAGEMAKER_ENDPOINT not configured, skipping inference")
        return

    inference_payload = {
        "sensor_id": payload.get("sensor_id"),
        "timestamp": payload.get("timestamp"),
        "observation_count": payload.get("observation_count"),
        "avg_rssi": payload.get("avg_rssi"),
        "observations": [
            {
                "mac": obs.get("mac"),
                "rssi_dbm": obs.get("rssi_dbm"),
                "noise_dbm": obs.get("noise_dbm"),
                "channel": obs.get("channel"),
                "bandwidth": obs.get("bandwidth"),
                "is_randomized_mac": obs.get("is_randomized_mac"),
                "count": obs.get("count"),
            }
            for obs in payload.get("observations", [])
        ],
        "position": payload.get("position"),
    }

    try:
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT,
            ContentType="application/json",
            Body=json.dumps(inference_payload, default=str).encode("utf-8"),
        )
        result = json.loads(response["Body"].read().decode("utf-8"))
        logger.info(
            "SageMaker inference result for sensor=%s: %s",
            payload.get("sensor_id"),
            result,
        )
    except ClientError as exc:
        logger.error("SageMaker inference failed: %s", exc)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse SageMaker response: %s", exc)


def _sanitize_dynamodb_item(item: dict[str, Any]) -> dict[str, Any]:
    """Remove None values and empty strings from DynamoDB item.

    DynamoDB does not accept None or empty string values for non-key attributes.

    Args:
        item: Raw item dictionary.

    Returns:
        Sanitized item safe for DynamoDB put_item.
    """
    sanitized: dict[str, Any] = {}
    for key, value in item.items():
        if value is None:
            continue
        if isinstance(value, float):
            from decimal import Decimal

            sanitized[key] = Decimal(str(value))
        elif isinstance(value, dict):
            nested = _sanitize_dynamodb_item(value)
            if nested:
                sanitized[key] = nested
        elif value == "" and key not in ("session_id", "mac", "timestamp_event_id"):
            continue
        else:
            sanitized[key] = value
    return sanitized
