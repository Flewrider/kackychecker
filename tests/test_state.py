"""
Tests for watcher_state module.
"""
import time
import pytest

from watcher_state import WatcherState


def test_watcher_state_init():
    """Test WatcherState initialization."""
    state = WatcherState(live_duration_seconds=600)
    assert state.live_duration_seconds == 600
    assert state.eta_seconds_by_map == {}
    assert state.live_until_by_map == {}


def test_watcher_state_update_from_fetch():
    """Test updating state from fetched data."""
    state = WatcherState(live_duration_seconds=600)
    rows = [
        {"map_number": "379", "server": "Server 10", "is_live": True, "eta": ""},
        {"map_number": "385", "server": "Server 11", "is_live": False, "eta": "10:20"},
    ]
    watched = {379, 385}
    
    live_now = state.update_from_fetch(rows, watched)
    
    assert 379 in live_now
    assert 379 in state.live_until_by_map
    assert 385 in state.eta_seconds_by_map
    assert state.eta_seconds_by_map[385] == 620  # 10:20 = 10*60 + 20


def test_watcher_state_countdown_etas():
    """Test ETA countdown."""
    state = WatcherState()
    state.eta_seconds_by_map[385] = 100
    state.upcoming_by_map[385] = [("Server 11", 100)]
    
    state.countdown_etas(10)
    
    assert state.eta_seconds_by_map[385] == 90
    assert state.upcoming_by_map[385][0][1] == 90


def test_watcher_state_get_live_summary():
    """Test getting live summary."""
    state = WatcherState(live_duration_seconds=600)
    now_ts = time.time()
    
    # Set a live window
    state.live_until_by_map[379] = now_ts + 300
    state.live_servers_by_map[379] = {"Server 10"}
    
    watched = {379, 385}
    live_now = {379}
    
    live_summary = state.get_live_summary(watched, live_now, now_ts)
    assert 379 in live_summary
    assert 385 not in live_summary


def test_watcher_state_cleanup_expired():
    """Test cleanup of expired live windows."""
    state = WatcherState()
    now_ts = time.time()
    
    # Set expired and active windows
    state.live_until_by_map[379] = now_ts - 100  # expired
    state.live_until_by_map[385] = now_ts + 300  # active
    state.live_servers_by_map[379] = {"Server 10"}
    state.live_servers_by_map[385] = {"Server 11"}
    
    state.cleanup_expired_live_windows(now_ts)
    
    assert 379 not in state.live_until_by_map
    assert 385 in state.live_until_by_map
    assert 379 not in state.live_servers_by_map
    assert 385 in state.live_servers_by_map


def test_watcher_state_get_newly_live():
    """Test getting newly live maps."""
    state = WatcherState()
    state.notified_live = {379}
    
    watched = {379, 385}
    live_now = {379, 385}
    
    newly_live = state.get_newly_live(watched, live_now)
    assert 379 not in newly_live  # already notified
    assert 385 in newly_live  # newly live

