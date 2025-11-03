"""
Tests for watchlist_manager module.
"""
import os
import tempfile
import pytest

from watchlist_manager import load_watchlist, save_watchlist, validate_map_number


def test_load_watchlist_empty_file():
    """Test loading empty watchlist."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("")
        fpath = f.name
    
    try:
        watched = load_watchlist(fpath)
        assert watched == set()
    finally:
        os.unlink(fpath)


def test_load_watchlist_basic():
    """Test loading watchlist with map numbers."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("379\n385\n391\n")
        fpath = f.name
    
    try:
        watched = load_watchlist(fpath)
        assert watched == {379, 385, 391}
    finally:
        os.unlink(fpath)


def test_load_watchlist_with_comments():
    """Test loading watchlist with comments."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("# Comment line\n379\n# Another comment\n385\n")
        fpath = f.name
    
    try:
        watched = load_watchlist(fpath)
        assert watched == {379, 385}
    finally:
        os.unlink(fpath)


def test_load_watchlist_with_formatting():
    """Test loading watchlist with formatted lines."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("379 - some text\n385\n")
        fpath = f.name
    
    try:
        watched = load_watchlist(fpath)
        assert watched == {379, 385}
    finally:
        os.unlink(fpath)


def test_save_watchlist():
    """Test saving watchlist."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        fpath = f.name
    
    try:
        map_numbers = {379, 385, 391}
        save_watchlist(map_numbers, fpath)
        
        # Verify file was created and contains map numbers
        assert os.path.exists(fpath)
        watched = load_watchlist(fpath)
        assert watched == map_numbers
    finally:
        os.unlink(fpath)


def test_validate_map_number():
    """Test map number validation."""
    assert validate_map_number("379") == 379
    assert validate_map_number("  379  ") == 379
    assert validate_map_number("379 - some text") == 379
    assert validate_map_number("# comment") is None
    assert validate_map_number("") is None
    assert validate_map_number("abc") is None

