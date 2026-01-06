"""Tests for indicators module."""

import pandas as pd
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.indicators import (
    compute_vwap,
    compute_atr,
    compute_hod,
    compute_lod,
    compute_or_levels,
    compute_near_hod,
    detect_vwap_cross,
    find_pullback_low,
    compute_volume_so_far,
    compute_pct_change,
    compute_rvol,
    get_last_price,
    compute_all_indicators,
)


@pytest.fixture
def sample_bars():
    """Create sample 1-minute bars DataFrame."""
    # Create 20 bars of sample data
    chicago_tz = ZoneInfo("America/Chicago")
    base_time = datetime(2024, 1, 15, 8, 30, tzinfo=chicago_tz)
    
    data = []
    for i in range(20):
        timestamp = base_time + timedelta(minutes=i)
        # Simulating an uptrend with some pullbacks
        base_price = 100 + i * 0.5 + (i % 3) * 0.2
        data.append({
            "timestamp": timestamp,
            "open": base_price - 0.1,
            "high": base_price + 0.3,
            "low": base_price - 0.2,
            "close": base_price + 0.1,
            "volume": 10000 + i * 500,
        })
    
    df = pd.DataFrame(data)
    df.set_index("timestamp", inplace=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


@pytest.fixture
def empty_bars():
    """Create empty DataFrame."""
    return pd.DataFrame()


class TestComputeVWAP:
    def test_basic_vwap(self, sample_bars):
        """Test VWAP calculation with sample data."""
        vwap = compute_vwap(sample_bars)
        
        # VWAP should be within the price range
        assert vwap > sample_bars["low"].min()
        assert vwap < sample_bars["high"].max()
    
    def test_empty_bars(self, empty_bars):
        """Test VWAP with empty DataFrame."""
        vwap = compute_vwap(empty_bars)
        assert vwap == 0.0
    
    def test_single_bar(self):
        """Test VWAP with single bar."""
        df = pd.DataFrame([{
            "high": 105.0,
            "low": 95.0,
            "close": 100.0,
            "volume": 1000,
        }])
        vwap = compute_vwap(df)
        # Typical price = (105 + 95 + 100) / 3 = 100
        assert vwap == 100.0


class TestComputeATR:
    def test_basic_atr(self, sample_bars):
        """Test ATR calculation."""
        atr = compute_atr(sample_bars, period=14)
        
        # ATR should be positive
        assert atr > 0
        # ATR should be less than the price range
        assert atr < sample_bars["high"].max() - sample_bars["low"].min()
    
    def test_short_period(self, sample_bars):
        """Test ATR with short period."""
        atr = compute_atr(sample_bars, period=5)
        assert atr > 0
    
    def test_empty_bars(self, empty_bars):
        """Test ATR with empty DataFrame."""
        atr = compute_atr(empty_bars)
        assert atr == 0.0


class TestComputeHODLOD:
    def test_hod(self, sample_bars):
        """Test HOD calculation."""
        hod = compute_hod(sample_bars)
        assert hod == sample_bars["high"].max()
    
    def test_lod(self, sample_bars):
        """Test LOD calculation."""
        lod = compute_lod(sample_bars)
        assert lod == sample_bars["low"].min()
    
    def test_empty_bars(self, empty_bars):
        """Test HOD/LOD with empty DataFrame."""
        assert compute_hod(empty_bars) == 0.0
        assert compute_lod(empty_bars) == 0.0


class TestComputeORLevels:
    def test_or_levels(self, sample_bars):
        """Test Opening Range calculation."""
        chicago_tz = ZoneInfo("America/Chicago")
        session_open = datetime(2024, 1, 15, 8, 30, tzinfo=chicago_tz)
        
        orh, orl = compute_or_levels(sample_bars, session_open, or_minutes=5)
        
        # OR levels should be within the overall range
        assert orh > 0
        assert orl > 0
        assert orh >= orl
    
    def test_empty_bars(self, empty_bars):
        """Test OR levels with empty DataFrame."""
        session_open = datetime(2024, 1, 15, 8, 30)
        orh, orl = compute_or_levels(empty_bars, session_open)
        assert orh == 0.0
        assert orl == 0.0


class TestComputeNearHOD:
    def test_at_hod(self):
        """Test near_hod when at HOD."""
        assert compute_near_hod(100.0, 100.0) == 1.0
    
    def test_below_hod(self):
        """Test near_hod when below HOD."""
        near = compute_near_hod(98.0, 100.0)
        assert near == 0.98
    
    def test_above_hod(self):
        """Test near_hod clamped to 1.0."""
        near = compute_near_hod(105.0, 100.0)
        assert near == 1.0
    
    def test_zero_hod(self):
        """Test near_hod with zero HOD."""
        assert compute_near_hod(100.0, 0.0) == 0.0


class TestDetectVWAPCross:
    def test_cross_detected(self):
        """Test VWAP cross detection."""
        # Prices going from below VWAP to above
        df = pd.DataFrame({
            "close": [98.0, 99.0, 99.5, 100.0, 101.0]
        })
        assert detect_vwap_cross(df, vwap=100.0, lookback=5) is True
    
    def test_no_cross(self):
        """Test no VWAP cross when always above."""
        df = pd.DataFrame({
            "close": [101.0, 102.0, 103.0, 104.0, 105.0]
        })
        assert detect_vwap_cross(df, vwap=100.0, lookback=5) is False
    
    def test_empty_bars(self, empty_bars):
        """Test with empty DataFrame."""
        assert detect_vwap_cross(empty_bars, vwap=100.0) is False


class TestFindPullbackLow:
    def test_pullback_above_vwap(self):
        """Test finding pullback low above VWAP."""
        df = pd.DataFrame({
            "low": [102.0, 101.5, 101.0, 101.2, 101.8]
        })
        pullback = find_pullback_low(df, vwap=100.0, lookback=5)
        assert pullback == 101.0
    
    def test_pullback_below_vwap(self):
        """Test no valid pullback when low is below VWAP."""
        df = pd.DataFrame({
            "low": [99.0, 98.5, 98.0, 98.2, 99.8]
        })
        pullback = find_pullback_low(df, vwap=100.0, lookback=5)
        assert pullback is None


class TestComputeVolume:
    def test_volume_sum(self, sample_bars):
        """Test volume summation."""
        volume = compute_volume_so_far(sample_bars)
        assert volume == sample_bars["volume"].sum()
    
    def test_empty_bars(self, empty_bars):
        """Test with empty DataFrame."""
        assert compute_volume_so_far(empty_bars) == 0


class TestComputePctChange:
    def test_positive_change(self):
        """Test positive percentage change."""
        pct = compute_pct_change(105.0, 100.0)
        assert pct == 5.0
    
    def test_negative_change(self):
        """Test negative percentage change."""
        pct = compute_pct_change(95.0, 100.0)
        assert pct == -5.0
    
    def test_zero_previous(self):
        """Test with zero previous price."""
        pct = compute_pct_change(100.0, 0.0)
        assert pct == 0.0


class TestComputeRVOL:
    def test_with_avg_volume(self):
        """Test RVOL with average daily volume."""
        rvol = compute_rvol(500_000, avg_daily_volume=1_000_000)
        assert rvol == 0.5
    
    def test_with_median_fallback(self):
        """Test RVOL with median fallback."""
        rvol = compute_rvol(500_000, avg_daily_volume=None, median_volume=250_000)
        assert rvol == 2.0
    
    def test_no_reference(self):
        """Test RVOL with no reference."""
        rvol = compute_rvol(500_000, avg_daily_volume=None, median_volume=None)
        assert rvol == 1.0


class TestGetLastPrice:
    def test_last_price(self, sample_bars):
        """Test getting last price."""
        last = get_last_price(sample_bars)
        assert last == sample_bars["close"].iloc[-1]
    
    def test_empty_bars(self, empty_bars):
        """Test with empty DataFrame."""
        assert get_last_price(empty_bars) == 0.0


class TestComputeAllIndicators:
    def test_all_indicators(self, sample_bars):
        """Test computing all indicators at once."""
        chicago_tz = ZoneInfo("America/Chicago")
        session_open = datetime(2024, 1, 15, 8, 30, tzinfo=chicago_tz)
        
        result = compute_all_indicators(
            bars=sample_bars,
            session_open=session_open,
            prev_close=99.0,
        )
        
        # Check all expected keys are present
        expected_keys = [
            "last", "vwap", "hod", "lod", "near_hod", "volume_so_far",
            "atr_1m", "pct_change", "orh", "orl", "vwap_cross",
            "pullback_low", "above_vwap", "bars"
        ]
        for key in expected_keys:
            assert key in result
        
        # Check reasonable values
        assert result["last"] > 0
        assert result["vwap"] > 0
        assert result["hod"] >= result["lod"]
        assert 0 <= result["near_hod"] <= 1
        assert result["volume_so_far"] > 0

