"""Tests for levels module."""

import pytest

from app.levels import (
    compute_risk_flags,
    classify_setup,
    compute_orb_breakout_levels,
    compute_vwap_reclaim_levels,
    compute_first_pullback_levels,
    compute_fallback_levels,
    compute_levels,
    add_levels_to_picks,
    TradeLevels,
)
from app.scanner import Candidate


@pytest.fixture
def orb_breakout_candidate():
    """Create candidate meeting ORB Breakout criteria."""
    return Candidate(
        symbol="ORBB",
        last=105.0,
        vwap=100.0,
        hod=106.0,
        lod=98.0,
        near_hod=0.99,  # 105/106 = 0.99
        orh=104.0,
        orl=99.0,
        atr_1m=0.50,
        volume_so_far=2_000_000,
        pct_change=5.0,
        rvol=2.0,
        above_vwap=True,
        vwap_cross=False,
        pullback_low=None,
    )


@pytest.fixture
def vwap_reclaim_candidate():
    """Create candidate meeting VWAP Reclaim criteria but NOT ORB Breakout."""
    return Candidate(
        symbol="VWPR",
        last=101.0,
        vwap=100.0,
        hod=105.0,  # HOD higher so near_hod < 0.98
        lod=97.0,
        near_hod=0.962,  # 101/105 = 0.962, below 0.98 threshold for ORB
        orh=102.0,  # Last (101) is below ORH (102)
        orl=97.0,
        atr_1m=0.40,
        volume_so_far=1_500_000,
        pct_change=3.0,
        rvol=1.5,
        above_vwap=True,
        vwap_cross=True,  # Key for VWAP Reclaim
        pullback_low=None,
    )


@pytest.fixture
def first_pullback_candidate():
    """Create candidate meeting First Pullback criteria but NOT ORB Breakout."""
    return Candidate(
        symbol="FPBK",
        last=104.0,
        vwap=100.0,
        hod=105.0,
        lod=98.0,
        near_hod=0.99,
        orh=105.0,  # Last (104) is below ORH (105), so NOT ORB Breakout
        orl=99.0,
        atr_1m=0.45,
        volume_so_far=1_800_000,
        pct_change=4.0,
        rvol=1.8,
        above_vwap=True,
        vwap_cross=False,
        pullback_low=101.5,  # Key for First Pullback (above VWAP)
    )


@pytest.fixture
def no_setup_candidate():
    """Create candidate not meeting any clean setup criteria."""
    return Candidate(
        symbol="NSET",
        last=99.0,
        vwap=100.0,  # Below VWAP
        hod=102.0,
        lod=97.0,
        near_hod=0.97,
        orh=101.0,
        orl=98.0,
        atr_1m=0.35,
        volume_so_far=1_200_000,
        pct_change=2.0,
        rvol=1.2,
        above_vwap=False,
        vwap_cross=False,
        pullback_low=None,
    )


class TestComputeRiskFlags:
    def test_below_vwap_flag(self, no_setup_candidate):
        """Test below_vwap flag."""
        flags = compute_risk_flags(no_setup_candidate)
        assert "below_vwap" in flags
    
    def test_overextended_flag(self):
        """Test overextended ATR flag."""
        c = Candidate(
            symbol="OVER",
            last=105.0,
            vwap=100.0,
            atr_1m=2.0,  # 5/2 = 2.5 ATR above VWAP (>2.0 threshold)
            above_vwap=True,
            volume_so_far=1_000_000,
            near_hod=0.98,
        )
        flags = compute_risk_flags(c)
        assert "overextended_atr" in flags
    
    def test_not_near_hod_flag(self):
        """Test not_near_hod flag."""
        c = Candidate(
            symbol="NHOD",
            last=96.0,
            vwap=95.0,
            hod=100.0,
            near_hod=0.96,  # <0.97
            above_vwap=True,
            volume_so_far=1_000_000,
        )
        flags = compute_risk_flags(c)
        assert "not_near_hod" in flags
    
    def test_low_volume_flag(self):
        """Test low_volume flag."""
        c = Candidate(
            symbol="LVOL",
            last=100.0,
            vwap=99.0,
            above_vwap=True,
            volume_so_far=300_000,  # <500k
            near_hod=0.99,
        )
        flags = compute_risk_flags(c)
        assert "low_volume" in flags
    
    def test_no_flags(self, orb_breakout_candidate):
        """Test candidate with no risk flags."""
        flags = compute_risk_flags(orb_breakout_candidate)
        # Should have no major flags
        assert "below_vwap" not in flags
        assert "low_volume" not in flags


class TestClassifySetup:
    def test_orb_breakout(self, orb_breakout_candidate):
        """Test ORB Breakout classification."""
        setup = classify_setup(orb_breakout_candidate)
        assert setup == "ORB Breakout"
    
    def test_vwap_reclaim(self, vwap_reclaim_candidate):
        """Test VWAP Reclaim classification."""
        setup = classify_setup(vwap_reclaim_candidate)
        assert setup == "VWAP Reclaim"
    
    def test_first_pullback(self, first_pullback_candidate):
        """Test First Pullback classification."""
        setup = classify_setup(first_pullback_candidate)
        assert setup == "First Pullback"
    
    def test_no_clean_setup(self, no_setup_candidate):
        """Test fallback classification."""
        setup = classify_setup(no_setup_candidate)
        assert setup == "No clean setup"
    
    def test_priority_orb_over_vwap_reclaim(self):
        """Test ORB Breakout takes priority over VWAP Reclaim."""
        c = Candidate(
            symbol="BOTH",
            last=105.0,
            vwap=100.0,
            near_hod=0.99,
            orh=104.0,
            orl=99.0,
            above_vwap=True,
            vwap_cross=True,  # Also meets VWAP Reclaim
            pullback_low=None,
        )
        setup = classify_setup(c)
        assert setup == "ORB Breakout"


class TestORBBreakoutLevels:
    def test_levels_structure(self, orb_breakout_candidate):
        """Test ORB Breakout levels structure."""
        atr = orb_breakout_candidate.atr_1m
        levels = compute_orb_breakout_levels(orb_breakout_candidate, atr)
        
        assert levels.setup_type == "ORB Breakout"
        assert levels.buy_area is not None
        assert levels.stop is not None
        assert levels.target_1 is not None
        assert levels.target_2 is not None
        assert levels.target_3 is not None
    
    def test_buy_area_above_orh(self, orb_breakout_candidate):
        """Test buy area is at or above ORH."""
        atr = orb_breakout_candidate.atr_1m
        levels = compute_orb_breakout_levels(orb_breakout_candidate, atr)
        
        assert levels.buy_area[0] >= orb_breakout_candidate.orh
    
    def test_stop_below_entry(self, orb_breakout_candidate):
        """Test stop is below entry."""
        atr = orb_breakout_candidate.atr_1m
        levels = compute_orb_breakout_levels(orb_breakout_candidate, atr)
        
        entry = (levels.buy_area[0] + levels.buy_area[1]) / 2
        assert levels.stop < entry
    
    def test_targets_ascending(self, orb_breakout_candidate):
        """Test targets are in ascending order."""
        atr = orb_breakout_candidate.atr_1m
        levels = compute_orb_breakout_levels(orb_breakout_candidate, atr)
        
        assert levels.target_1 < levels.target_2
        assert levels.target_2 < levels.target_3


class TestVWAPReclaimLevels:
    def test_levels_structure(self, vwap_reclaim_candidate):
        """Test VWAP Reclaim levels structure."""
        atr = vwap_reclaim_candidate.atr_1m
        levels = compute_vwap_reclaim_levels(vwap_reclaim_candidate, atr)
        
        assert levels.setup_type == "VWAP Reclaim"
        assert levels.buy_area is not None
        assert levels.stop is not None
    
    def test_buy_area_at_vwap(self, vwap_reclaim_candidate):
        """Test buy area starts at VWAP."""
        atr = vwap_reclaim_candidate.atr_1m
        levels = compute_vwap_reclaim_levels(vwap_reclaim_candidate, atr)
        
        assert levels.buy_area[0] == vwap_reclaim_candidate.vwap
    
    def test_stop_below_vwap(self, vwap_reclaim_candidate):
        """Test stop is below VWAP."""
        atr = vwap_reclaim_candidate.atr_1m
        levels = compute_vwap_reclaim_levels(vwap_reclaim_candidate, atr)
        
        assert levels.stop < vwap_reclaim_candidate.vwap


class TestFirstPullbackLevels:
    def test_levels_structure(self, first_pullback_candidate):
        """Test First Pullback levels structure."""
        atr = first_pullback_candidate.atr_1m
        levels = compute_first_pullback_levels(first_pullback_candidate, atr)
        
        assert levels.setup_type == "First Pullback"
        assert levels.buy_area is not None
    
    def test_buy_area_above_pullback_low(self, first_pullback_candidate):
        """Test buy area is above pullback low."""
        atr = first_pullback_candidate.atr_1m
        levels = compute_first_pullback_levels(first_pullback_candidate, atr)
        
        assert levels.buy_area[0] > first_pullback_candidate.pullback_low
    
    def test_stop_below_pullback_low(self, first_pullback_candidate):
        """Test stop is below pullback low."""
        atr = first_pullback_candidate.atr_1m
        levels = compute_first_pullback_levels(first_pullback_candidate, atr)
        
        assert levels.stop < first_pullback_candidate.pullback_low


class TestFallbackLevels:
    def test_skip_when_below_vwap(self, no_setup_candidate):
        """Test skip signal when below VWAP."""
        atr = no_setup_candidate.atr_1m
        levels = compute_fallback_levels(no_setup_candidate, atr)
        
        assert levels.setup_type == "No clean setup"
        assert levels.buy_area is None
    
    def test_conservative_when_above_vwap(self):
        """Test conservative levels when above VWAP."""
        c = Candidate(
            symbol="CONS",
            last=101.0,
            vwap=100.0,
            hod=102.0,
            lod=98.0,
            near_hod=0.95,  # Not near HOD
            orh=101.5,
            orl=99.0,
            atr_1m=0.30,
            above_vwap=True,
            vwap_cross=False,
            pullback_low=None,
            volume_so_far=1_000_000,
        )
        levels = compute_fallback_levels(c, c.atr_1m)
        
        assert levels.buy_area is not None
        assert levels.target_3 is None  # Conservative - only T1/T2


class TestComputeLevels:
    def test_dispatches_correctly(
        self,
        orb_breakout_candidate,
        vwap_reclaim_candidate,
        first_pullback_candidate,
        no_setup_candidate,
    ):
        """Test compute_levels dispatches to correct function."""
        orb_levels = compute_levels(orb_breakout_candidate)
        assert orb_levels.setup_type == "ORB Breakout"
        
        vwap_levels = compute_levels(vwap_reclaim_candidate)
        assert vwap_levels.setup_type == "VWAP Reclaim"
        
        fb_levels = compute_levels(first_pullback_candidate)
        assert fb_levels.setup_type == "First Pullback"
        
        fallback_levels = compute_levels(no_setup_candidate)
        assert fallback_levels.setup_type == "No clean setup"


class TestAddLevelsToPicks:
    def test_adds_levels_to_all_picks(
        self, orb_breakout_candidate, vwap_reclaim_candidate
    ):
        """Test levels are added to all picks."""
        picks = [orb_breakout_candidate, vwap_reclaim_candidate]
        # Add required metadata
        for p in picks:
            p.metadata["final_score"] = 0.8
        
        results = add_levels_to_picks(picks)
        
        assert len(results) == 2
        for r in results:
            assert "levels" in r
            assert "score" in r
            assert r["levels"] is not None


class TestTradeLevels:
    def test_to_dict(self, orb_breakout_candidate):
        """Test TradeLevels to_dict conversion."""
        atr = orb_breakout_candidate.atr_1m
        levels = compute_orb_breakout_levels(orb_breakout_candidate, atr)
        
        d = levels.to_dict()
        
        assert isinstance(d, dict)
        assert "setup_type" in d
        assert "buy_area" in d
        assert "stop" in d
        assert "target_1" in d
        assert "target_2" in d
        assert "target_3" in d
        assert "risk_flags" in d
        
        # Values should be rounded
        if d["buy_area"]:
            assert all(isinstance(v, float) for v in d["buy_area"])

