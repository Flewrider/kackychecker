"""
Tests for config module.
"""
import os
import pytest
from unittest.mock import patch

from config import load_config, setup_logging


def test_load_config_defaults():
    """Test loading config with default values."""
    with patch.dict(os.environ, {}, clear=True):
        config = load_config()
        assert config["CHECK_INTERVAL_SECONDS"] == 20
        assert config["REQUEST_TIMEOUT_SECONDS"] == 10
        assert config["LOG_LEVEL"] == "INFO"
        assert config["ENABLE_BROWSER"] is False
        assert config["LIVE_DURATION_SECONDS"] == 600


def test_load_config_custom():
    """Test loading config with custom values."""
    env_vars = {
        "CHECK_INTERVAL_SECONDS": "30",
        "LOG_LEVEL": "DEBUG",
        "ENABLE_BROWSER": "1",
        "LIVE_DURATION_SECONDS": "900",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        config = load_config()
        assert config["CHECK_INTERVAL_SECONDS"] == 30
        assert config["LOG_LEVEL"] == "DEBUG"
        assert config["ENABLE_BROWSER"] is True
        assert config["LIVE_DURATION_SECONDS"] == 900


def test_setup_logging():
    """Test logging setup."""
    # Should not raise
    setup_logging("INFO")
    setup_logging("DEBUG")
    setup_logging("WARNING")
    # Invalid level should default to INFO
    setup_logging("INVALID")

