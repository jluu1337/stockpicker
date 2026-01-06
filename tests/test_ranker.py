"""Tests for ranker module."""

import pytest

from app.ranker import (
    rank_normalize,
    compute_scores,
    select_top,
    get_leaderboard,
    rank_candidates,
)
from app.scanner import Candidate


@pytest.fixture
def sample_candidates():
    """Create sample candidates for testing."""
    candidates = []
    
    # Create 5 candidates with varying metrics
    # Note: For bonus to apply without overextended penalty, (last-vwap)/vwap must be <= 0.03
    data = [
        {"symbol": "AAA", "pct_change": 10.0, "rvol": 3.0, "near_hod": 0.99, "last": 50.0, "vwap": 49.0},  # 2% above VWAP (not overextended)
        {"symbol": "BBB", "pct_change": 8.0, "rvol": 2.5, "near_hod": 0.97, "last": 45.0, "vwap": 44.0},
        {"symbol": "CCC", "pct_change": 15.0, "rvol": 1.5, "near_hod": 0.95, "last": 60.0, "vwap": 62.0},  # Below VWAP
        {"symbol": "DDD", "pct_change": 5.0, "rvol": 4.0, "near_hod": 0.98, "last": 70.0, "vwap": 65.0},  # Overextended (7.7%)
        {"symbol": "EEE", "pct_change": 12.0, "rvol": 2.0, "near_hod": 0.96, "last": 55.0, "vwap": 54.0},
    ]
    
    for d in data:
        c = Candidate(
            symbol=d["symbol"],
            last=d["last"],
            vwap=d["vwap"],
            pct_change=d["pct_change"],
            rvol=d["rvol"],
            near_hod=d["near_hod"],
            above_vwap=d["last"] > d["vwap"],
        )
        candidates.append(c)
    
    return candidates


class TestRankNormalize:
    def test_basic_ranking(self):
        """Test basic rank normalization."""
        values = [10, 20, 30, 40, 50]
        ranks = rank_normalize(values)
        
        assert len(ranks) == 5
        assert ranks[0] == 0.0  # Lowest
        assert ranks[4] == 1.0  # Highest
        assert ranks[2] == 0.5  # Middle
    
    def test_reverse_order(self):
        """Test with reversed order."""
        values = [50, 40, 30, 20, 10]
        ranks = rank_normalize(values)
        
        assert ranks[0] == 1.0  # 50 is highest
        assert ranks[4] == 0.0  # 10 is lowest
    
    def test_ties(self):
        """Test handling of ties."""
        values = [10, 20, 20, 30]
        ranks = rank_normalize(values)
        
        assert ranks[0] == 0.0  # Lowest
        assert ranks[1] == ranks[2]  # Ties should have same rank
        assert ranks[3] == 1.0  # Highest
    
    def test_single_value(self):
        """Test with single value."""
        values = [100]
        ranks = rank_normalize(values)
        
        assert ranks == [0.5]
    
    def test_empty_list(self):
        """Test with empty list."""
        values = []
        ranks = rank_normalize(values)
        
        assert ranks == []
    
    def test_two_values(self):
        """Test with two values."""
        values = [10, 20]
        ranks = rank_normalize(values)
        
        assert ranks[0] == 0.0
        assert ranks[1] == 1.0


class TestComputeScores:
    def test_scores_computed(self, sample_candidates):
        """Test that scores are computed for all candidates."""
        scored = compute_scores(sample_candidates)
        
        assert len(scored) == len(sample_candidates)
        
        for c in scored:
            assert "final_score" in c.metadata
            assert "base_score" in c.metadata
            assert "adjustment" in c.metadata
            assert 0.0 <= c.metadata["final_score"] <= 1.0
    
    def test_above_vwap_bonus(self, sample_candidates):
        """Test that above VWAP candidates get bonus."""
        scored = compute_scores(sample_candidates)
        
        # AAA is above VWAP
        aaa = next(c for c in scored if c.symbol == "AAA")
        assert aaa.metadata["adjustment"] >= 0.05
    
    def test_below_vwap_penalty(self, sample_candidates):
        """Test that below VWAP candidates get penalty."""
        scored = compute_scores(sample_candidates)
        
        # CCC is below VWAP
        ccc = next(c for c in scored if c.symbol == "CCC")
        assert ccc.metadata["adjustment"] <= -0.10
    
    def test_overextended_penalty(self, sample_candidates):
        """Test overextended penalty."""
        scored = compute_scores(sample_candidates)
        
        # DDD is overextended (70 vs 65 = 7.7% above VWAP)
        ddd = next(c for c in scored if c.symbol == "DDD")
        # Should have -0.05 penalty (plus +0.05 for being above VWAP)
        # Net adjustment = 0
        assert ddd.metadata["adjustment"] == 0.0


class TestSelectTop:
    def test_select_top_n(self, sample_candidates):
        """Test selecting top N candidates."""
        scored = compute_scores(sample_candidates)
        top = select_top(scored, n=3)
        
        assert len(top) == 3
        
        # Verify sorted by score
        scores = [c.metadata["final_score"] for c in top]
        assert scores == sorted(scores, reverse=True)
    
    def test_select_more_than_available(self, sample_candidates):
        """Test selecting more than available."""
        scored = compute_scores(sample_candidates)
        top = select_top(scored, n=10)
        
        assert len(top) == len(sample_candidates)
    
    def test_min_score_filter(self, sample_candidates):
        """Test minimum score filter."""
        scored = compute_scores(sample_candidates)
        top = select_top(scored, n=5, min_score=0.9)
        
        # May get fewer results due to min_score
        for c in top:
            assert c.metadata["final_score"] >= 0.9


class TestGetLeaderboard:
    def test_leaderboard_format(self, sample_candidates):
        """Test leaderboard output format."""
        scored = compute_scores(sample_candidates)
        leaderboard = get_leaderboard(scored, n=5)
        
        assert len(leaderboard) == 5
        
        # Check required fields
        for entry in leaderboard:
            assert "rank" in entry
            assert "symbol" in entry
            assert "score" in entry
            assert "pct_change" in entry
            assert "rvol" in entry
            assert "near_hod" in entry
            assert "above_vwap" in entry
    
    def test_leaderboard_sorted(self, sample_candidates):
        """Test leaderboard is sorted by score."""
        scored = compute_scores(sample_candidates)
        leaderboard = get_leaderboard(scored, n=5)
        
        scores = [e["score"] for e in leaderboard]
        assert scores == sorted(scores, reverse=True)
    
    def test_leaderboard_ranks(self, sample_candidates):
        """Test leaderboard ranks are sequential."""
        scored = compute_scores(sample_candidates)
        leaderboard = get_leaderboard(scored, n=5)
        
        ranks = [e["rank"] for e in leaderboard]
        assert ranks == [1, 2, 3, 4, 5]


class TestRankCandidates:
    def test_full_pipeline(self, sample_candidates):
        """Test full ranking pipeline."""
        picks, leaderboard = rank_candidates(sample_candidates)
        
        # Should have picks (up to settings.picks, default 5)
        assert len(picks) > 0
        assert len(picks) <= 5
        
        # Should have leaderboard
        assert len(leaderboard) > 0
        assert len(leaderboard) <= 10
        
        # Picks should be subset of leaderboard symbols
        pick_symbols = {c.symbol for c in picks}
        leaderboard_symbols = {e["symbol"] for e in leaderboard}
        assert pick_symbols.issubset(leaderboard_symbols)

