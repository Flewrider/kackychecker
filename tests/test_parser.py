"""
Tests for schedule_parser module.
"""
import pytest

from schedule_parser import parse_live_maps


def test_parse_live_maps_empty():
    """Test parsing empty HTML."""
    html = "<html><body></body></html>"
    rows = parse_live_maps(html)
    assert rows == []


def test_parse_live_maps_simple():
    """Test parsing simple schedule row."""
    html = """
    <div class="flex items-center justify-between gap-4 rounded-lg px-3 py-2">
        <div>379 - Map Name</div>
        <div>Server 10</div>
        <div>LIVE</div>
    </div>
    """
    rows = parse_live_maps(html)
    assert len(rows) == 1
    assert rows[0]["map_number"] == "379"
    assert rows[0]["server"] == "Server 10"
    assert rows[0]["is_live"] is True


def test_parse_live_maps_with_eta():
    """Test parsing schedule row with ETA."""
    html = """
    <div class="flex items-center justify-between gap-4 rounded-lg px-3 py-2">
        <div>385 - Map Name</div>
        <div>Server 11</div>
        <div>10:20</div>
    </div>
    """
    rows = parse_live_maps(html)
    assert len(rows) == 1
    assert rows[0]["map_number"] == "385"
    assert rows[0]["server"] == "Server 11"
    assert rows[0]["is_live"] is False
    assert rows[0]["eta"] == "10:20"


def test_parse_live_maps_multiple():
    """Test parsing multiple schedule rows."""
    html = """
    <div class="flex items-center justify-between gap-4 rounded-lg px-3 py-2">
        <div>379 - Map 1</div>
        <div>Server 10</div>
        <div>LIVE</div>
    </div>
    <div class="flex items-center justify-between gap-4 rounded-lg px-3 py-2">
        <div>385 - Map 2</div>
        <div>Server 11</div>
        <div>5:30</div>
    </div>
    """
    rows = parse_live_maps(html)
    assert len(rows) == 2
    assert rows[0]["map_number"] == "379"
    assert rows[1]["map_number"] == "385"

