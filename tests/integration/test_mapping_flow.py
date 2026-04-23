"""Integration test for walk-and-tag mapping flow."""

import json
import pytest


def test_position_with_rssi_snapshot(api_client, session_id):
    """Tagging a position includes RSSI snapshot and returns position_id."""
    response = api_client.post("/api/positions", json={
        "session_id": session_id,
        "x": 2.5,
        "y": 3.0,
        "label": "P1",
        "rssi_snapshot": [
            {"mac": "aa:bb:cc:dd:ee:01", "rssi_dbm": -45, "channel": 6, "bandwidth": "2.4GHz"},
            {"mac": "aa:bb:cc:dd:ee:02", "rssi_dbm": -62, "channel": 36, "bandwidth": "5GHz"},
        ],
    })
    assert response.status_code == 201
    body = response.json()
    assert "position_id" in body


def test_map_generation_after_three_positions(api_client, session_id):
    """After 3 position tags, map_generated should be True."""
    positions = [
        {"x": 0, "y": 0, "rssi": [-45, -62, -71]},
        {"x": 5, "y": 0, "rssi": [-55, -48, -80]},
        {"x": 2.5, "y": 4, "rssi": [-60, -55, -65]},
    ]
    for i, p in enumerate(positions):
        response = api_client.post("/api/positions", json={
            "session_id": session_id,
            "x": p["x"],
            "y": p["y"],
            "label": f"P{i+1}",
            "rssi_snapshot": [
                {"mac": f"aa:bb:cc:dd:ee:0{j}", "rssi_dbm": r, "channel": 6, "bandwidth": "2.4GHz"}
                for j, r in enumerate(p["rssi"])
            ],
        })
        assert response.status_code == 201

    body = response.json()
    assert body.get("map_generated") is True
    assert body["position_count"] == 3


def test_map_retrieval_has_heatmap(api_client, session_id):
    """After map generation, GET /api/map returns heatmap data."""
    for i, (x, y) in enumerate([(0, 0), (5, 0), (2.5, 4)]):
        api_client.post("/api/positions", json={
            "session_id": session_id,
            "x": x,
            "y": y,
            "label": f"P{i+1}",
            "rssi_snapshot": [
                {"mac": "aa:bb:cc:dd:ee:01", "rssi_dbm": -50 - i * 10, "channel": 6, "bandwidth": "2.4GHz"},
            ],
        })

    response = api_client.get(f"/api/map/{session_id}")
    assert response.status_code == 200
    body = response.json()
    items = body.get("items", [])
    map_items = [item for item in items if item.get("type") == "heatmap"]
    assert len(map_items) >= 1

    heatmap = json.loads(map_items[0]["heatmap"])
    assert len(heatmap) == 30
    assert len(heatmap[0]) == 30
