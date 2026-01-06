"""Ranker module for scoring and ranking stock candidates."""

import logging
from typing import Callable

from app.config import get_settings
from app.scanner import Candidate

logger = logging.getLogger(__name__)


def rank_normalize(values: list[float]) -> list[float]:
    """
    Rank-normalize values to 0-1 range.

    Each value is replaced by its rank / (n - 1), where n is the count.
    This gives the lowest value 0.0 and highest 1.0.

    Args:
        values: List of numeric values

    Returns:
        List of normalized values (0-1)
    """
    n = len(values)

    if n == 0:
        return []

    if n == 1:
        return [0.5]  # Single value gets middle rank

    # Create (value, original_index) pairs
    indexed = list(enumerate(values))

    # Sort by value
    sorted_indexed = sorted(indexed, key=lambda x: x[1])

    # Assign ranks (handle ties with average rank)
    ranks = [0.0] * n

    i = 0
    while i < n:
        j = i

        # Find all items with same value (ties)
        while j < n and sorted_indexed[j][1] == sorted_indexed[i][1]:
            j += 1

        # Average rank for ties
        avg_rank = (i + j - 1) / 2

        # Assign to all tied items
        for k in range(i, j):
            original_idx = sorted_indexed[k][0]
            ranks[original_idx] = avg_rank / (n - 1)

        i = j

    return ranks


def compute_scores(candidates: list[Candidate]) -> list[Candidate]:
    """
    Compute momentum scores for candidates with improved logic.

    Scoring formula:
    base_score = 0.40*pct_change_rank + 0.35*rvol_rank + 0.25*near_hod_rank

    Bonuses/Penalties:
    - +0.05 if last > vwap
    - -0.10 if last < vwap
    - ATR-based overextension penalty (replaces fixed 3%)
    - Extreme gainer penalty (diminishing returns on 20%+ movers)
    - Gap-and-fade detection penalty
    - Strong continuation bonus

    Args:
        candidates: List of enriched candidates

    Returns:
        Candidates with score and final_score attributes set
    """
    if not candidates:
        return []

    n = len(candidates)
    settings = get_settings()
    logger.info(f"Computing scores for {n} candidates")

    # Extract values for ranking
    pct_changes = [c.pct_change for c in candidates]
    rvols = [c.rvol for c in candidates]
    near_hods = [c.near_hod for c in candidates]

    # Rank-normalize
    pct_change_ranks = rank_normalize(pct_changes)
    rvol_ranks = rank_normalize(rvols)
    near_hod_ranks = rank_normalize(near_hods)

    # Compute scores
    for i, c in enumerate(candidates):
        # Base score
        base_score = (
            0.40 * pct_change_ranks[i]
            + 0.35 * rvol_ranks[i]
            + 0.25 * near_hod_ranks[i]
        )

        # Apply bonuses/penalties
        adjustment = 0.0

        # VWAP position bonus/penalty
        if c.last > c.vwap:
            adjustment += 0.05
        elif c.last < c.vwap:
            adjustment -= 0.10

        # ATR-based overextension check (replaces fixed 3% threshold)
        # This adapts to each stock's volatility
        if c.vwap > 0 and c.atr_1m > 0:
            atr_above_vwap = (c.last - c.vwap) / c.atr_1m
            if atr_above_vwap > settings.max_extension_atr:
                adjustment -= 0.08
                c.metadata["overextended_atr"] = round(atr_above_vwap, 2)

        # Extreme gainer penalty (diminishing returns on big movers)
        # Stocks already up 40%+ have less upside potential
        if c.pct_change > 40:
            adjustment -= 0.12
        elif c.pct_change > 30:
            adjustment -= 0.08
        elif c.pct_change > 20:
            adjustment -= 0.04

        # Gap-and-fade detection penalty
        # If price is red from session open, it's likely fading
        if c.vs_open < -2.0:  # Down more than 2% from open
            adjustment -= 0.10
            c.metadata["fading_from_open"] = True
        elif c.vs_open < 0:  # Slightly red from open
            adjustment -= 0.03

        # Strong continuation bonus
        # Green from open AND near HOD = strong trend
        if c.is_green_since_open and c.near_hod >= 0.98:
            adjustment += 0.05

        # Final score (clamp to 0-1)
        final_score = max(0.0, min(1.0, base_score + adjustment))

        # Store in metadata
        c.metadata["base_score"] = round(base_score, 4)
        c.metadata["adjustment"] = round(adjustment, 4)
        c.metadata["final_score"] = round(final_score, 4)
        c.metadata["pct_change_rank"] = round(pct_change_ranks[i], 4)
        c.metadata["rvol_rank"] = round(rvol_ranks[i], 4)
        c.metadata["near_hod_rank"] = round(near_hod_ranks[i], 4)

    return candidates


def select_top(
    candidates: list[Candidate],
    n: int | None = None,
    min_score: float = 0.0,
) -> list[Candidate]:
    """
    Select top N candidates by final_score.

    Args:
        candidates: Scored candidates
        n: Number to select (default: from settings)
        min_score: Minimum score threshold

    Returns:
        Top N candidates sorted by score descending
    """
    settings = get_settings()

    if n is None:
        n = settings.picks

    # Filter by minimum score
    eligible = [
        c for c in candidates
        if c.metadata.get("final_score", 0) >= min_score
    ]

    # Sort by final_score descending
    sorted_candidates = sorted(
        eligible,
        key=lambda c: c.metadata.get("final_score", 0),
        reverse=True,
    )

    # Take top N
    top = sorted_candidates[:n]

    logger.info(
        f"Selected top {len(top)} from {len(candidates)} candidates "
        f"(min_score={min_score})"
    )

    return top


def get_leaderboard(
    candidates: list[Candidate],
    n: int = 10,
) -> list[dict]:
    """
    Get top N leaderboard for email display.

    Args:
        candidates: Scored candidates
        n: Number of entries (default: 10)

    Returns:
        List of dicts with leaderboard data
    """
    # Sort by final_score
    sorted_candidates = sorted(
        candidates,
        key=lambda c: c.metadata.get("final_score", 0),
        reverse=True,
    )

    leaderboard = []

    for i, c in enumerate(sorted_candidates[:n]):
        leaderboard.append({
            "rank": i + 1,
            "symbol": c.symbol,
            "score": c.metadata.get("final_score", 0),
            "pct_change": round(c.pct_change, 2),
            "rvol": round(c.rvol, 2),
            "near_hod": round(c.near_hod, 4),
            "above_vwap": c.above_vwap,
        })

    return leaderboard


def rank_candidates(candidates: list[Candidate]) -> tuple[list[Candidate], list[dict]]:
    """
    Full ranking pipeline: score, select top, build leaderboard.

    Args:
        candidates: Enriched candidates from scanner

    Returns:
        Tuple of (top_picks, leaderboard)
    """
    # Compute scores
    scored = compute_scores(candidates)

    # Select top picks
    picks = select_top(scored)

    # Build leaderboard
    leaderboard = get_leaderboard(scored)

    logger.info(
        f"Ranking complete: {len(picks)} picks, {len(leaderboard)} in leaderboard"
    )

    return picks, leaderboard

