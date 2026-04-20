"""Tests for Lambda API handler."""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

os.environ["DYNAMODB_MAPS_TABLE"] = "test-maps"
os.environ["DYNAMODB_DEVICE_TABLE"] = "test-devices"
os.environ["DYNAMODB_PRESENCE_TABLE"] = "test-presence"
os.environ["DYNAMODB_SESSIONS_TABLE"] = "test-sessions"


def _make_api_event(method, path, path_params=None, body=None):
    return {
        "httpMethod": method,
        "path": path,
        "requestContext": {"http": {"method": method, "path": path}},
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else None,
        "headers": {},
    }


class TestAPIHandler:
    def _import_handler(self, mock_boto3):
        """Force re-import with mocked boto3."""
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": []}
        mock_table.put_item.return_value = {}
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        # Remove cached module to re-import with mock
        for mod in list(sys.modules):
            if "api_handler" in mod:
                del sys.modules[mod]

        from backend.handlers.api_handler import handler
        return handler, mock_table

    @patch("boto3.resource")
    def test_post_sessions_creates_session(self, mock_resource):
        mock_table = MagicMock()
        mock_table.put_item.return_value = {}
        mock_resource.return_value.Table.return_value = mock_table

        # Re-import to pick up mock
        for mod in list(sys.modules):
            if "api_handler" in mod:
                del sys.modules[mod]
        from backend.handlers.api_handler import handler

        event = _make_api_event("POST", "/api/sessions", body={"name": "Test Audit"})
        result = handler(event, {})

        assert result["statusCode"] in (200, 201)
        body = json.loads(result["body"])
        assert "session_id" in body

    @patch("boto3.resource")
    def test_get_devices_returns_list(self, mock_resource):
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": [
            {"mac_address": "aa:bb:cc:dd:ee:ff", "device_type": "phone"}
        ]}
        mock_resource.return_value.Table.return_value = mock_table

        for mod in list(sys.modules):
            if "api_handler" in mod:
                del sys.modules[mod]
        from backend.handlers.api_handler import handler

        event = _make_api_event("GET", "/api/devices/sess-123", {"session_id": "sess-123"})
        result = handler(event, {})

        assert result["statusCode"] == 200

    @patch("boto3.resource")
    def test_cors_headers_present(self, mock_resource):
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": []}
        mock_resource.return_value.Table.return_value = mock_table

        for mod in list(sys.modules):
            if "api_handler" in mod:
                del sys.modules[mod]
        from backend.handlers.api_handler import handler

        event = _make_api_event("GET", "/api/map/sess-123", {"session_id": "sess-123"})
        result = handler(event, {})

        assert result["headers"]["Access-Control-Allow-Origin"] == "*"
