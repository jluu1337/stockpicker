"""Pytest configuration and shared fixtures."""

import os
import sys
from pathlib import Path

import pytest

# Add app to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set test environment variables
os.environ.setdefault("APCA_API_KEY_ID", "test_key")
os.environ.setdefault("APCA_API_SECRET_KEY", "test_secret")
os.environ.setdefault("SENDGRID_API_KEY", "test_sendgrid_key")
os.environ.setdefault("FROM_EMAIL", "test@example.com")
os.environ.setdefault("TO_EMAIL", "recipient@example.com")


@pytest.fixture
def mock_settings(monkeypatch):
    """Mock settings for testing."""
    monkeypatch.setenv("APCA_API_KEY_ID", "test_key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test_secret")
    monkeypatch.setenv("SENDGRID_API_KEY", "test_sendgrid_key")
    monkeypatch.setenv("FROM_EMAIL", "test@example.com")
    monkeypatch.setenv("TO_EMAIL", "recipient@example.com")
    monkeypatch.setenv("MIN_PRICE", "5")
    monkeypatch.setenv("MIN_VOLUME", "1000000")
    monkeypatch.setenv("PICKS", "5")
    
    # Clear cached settings
    from app.config import get_settings
    get_settings.cache_clear()
    
    yield
    
    # Clear cache after test
    get_settings.cache_clear()

