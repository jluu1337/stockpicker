"""Levels module for computing buy/stop/target levels based on setup type."""

import logging
from dataclasses import dataclass, field
from typing import Literal

from app.scanner import Candidate

logger = logging.getLogger(__name__)

SetupType = Literal[
    "ORB Breakout",
    "VWAP Reclaim",
    "First Pullback",
    "No clean setup",
]


@dataclass
class TradeLevels:
    """Computed trade levels for a setup."""

    setup_type: SetupType
    buy_area: tuple[float, float] | None  # (low, high) zone
    stop: float | None
    target_1: float | None
    target_2: float | None
    target_3: float | None
    risk_reward: float | None  # R multiple to T1
    explanation: str = ""
    risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "setup_type": self.setup_type,
            "buy_area": (
                [round(self.buy_area[0], 2), round(self.buy_area[1], 2)]
                if self.buy_area
                else None
            ),
            "stop": round(self.stop, 2) if self.stop else None,
            "target_1": round(self.target_1, 2) if self.target_1 else None,
            "target_2": round(self.target_2, 2) if self.target_2 else None,
            "target_3": round(self.target_3, 2) if self.target_3 else None,
            "risk_reward": round(self.risk_reward, 2) if self.risk_reward else None,
            "explanation": self.explanation,
            "risk_flags": self.risk_flags,
        }


def compute_risk_flags(candidate: Candidate) -> list[str]:
    """
    Compute risk flags for a candidate.

    Flags:
    - below_vwap: Price is below VWAP
    - overextended_atr: Price > VWAP by more than 2 ATR
    - not_near_hod: near_hod < 0.97
    - low_volume: volume_so_far < 500k (half of min threshold)
    - fading_from_open: Price is red from session open
    - extreme_gainer: Up more than 30% on the day
    - low_float: Float < 10M shares (manipulation risk)
    - large_cap: Market cap > $20B (less explosive)

    Args:
        candidate: Enriched candidate

    Returns:
        List of risk flag strings
    """
    flags = []

    if not candidate.above_vwap:
        flags.append("below_vwap")

    # ATR-based overextension (replaces fixed 3% threshold)
    if candidate.vwap > 0 and candidate.atr_1m > 0:
        atr_extension = (candidate.last - candidate.vwap) / candidate.atr_1m
        if atr_extension > 2.0:
            flags.append("overextended_atr")

    if candidate.near_hod < 0.97:
        flags.append("not_near_hod")

    if candidate.volume_so_far < 500_000:
        flags.append("low_volume")

    # Gap-and-fade detection
    if not candidate.is_green_since_open:
        flags.append("fading_from_open")

    # Extreme gainer warning
    if candidate.pct_change > 30:
        flags.append("extreme_gainer")

    # Float warning (if available)
    if candidate.shares_float and candidate.shares_float < 10_000_000:
        flags.append("low_float")

    # Large cap warning (less explosive moves)
    if candidate.market_cap and candidate.market_cap > 20_000_000_000:
        flags.append("large_cap")

    return flags


def classify_setup(candidate: Candidate) -> SetupType:
    """
    Classify the setup type based on price action criteria.

    Priority: ORB Breakout > VWAP Reclaim > First Pullback > Fallback

    Enhanced logic:
    - ORB Breakout now requires green from open (no gap-and-fade)
    - First Pullback requires meaningful pullback depth (at least 1%)

    Args:
        candidate: Enriched candidate with indicators

    Returns:
        Setup type classification
    """
    # A) ORB Breakout
    # Condition: last >= ORH AND last > VWAP AND near_hod >= 0.98 AND green from open
    if (
        candidate.last >= candidate.orh
        and candidate.last > candidate.vwap
        and candidate.near_hod >= 0.98
        and candidate.orh > 0
        and candidate.is_green_since_open  # Must be green from open (no gap-and-fade)
    ):
        return "ORB Breakout"

    # B) VWAP Reclaim
    # Condition: last > VWAP AND recently crossed from below to above
    if candidate.last > candidate.vwap and candidate.vwap_cross:
        return "VWAP Reclaim"

    # C) First Pullback (tighter logic)
    # Condition: last > VWAP AND near_hod >= 0.97 AND pullback low above VWAP
    # Additional: must be green from open AND have meaningful pullback depth
    if (
        candidate.last > candidate.vwap
        and candidate.near_hod >= 0.97
        and candidate.pullback_low is not None
        and candidate.pullback_low > candidate.vwap
        and candidate.is_green_since_open  # Must be green from open
    ):
        # Check that pullback is meaningful (not just noise)
        # At least 1% pullback from HOD indicates real consolidation
        if candidate.hod > 0:
            pullback_depth = (candidate.hod - candidate.pullback_low) / candidate.hod
            if pullback_depth >= 0.01:  # At least 1% pullback
                return "First Pullback"

    # Fallback
    return "No clean setup"


def compute_orb_breakout_levels(candidate: Candidate, atr: float) -> TradeLevels:
    """
    Compute levels for ORB Breakout setup.

    Buy area: [ORH, ORH + 0.15*ATR]
    Stop: min(VWAP, ORL) - 0.10*ATR
    Targets: entry + 1R, entry + 2R, max(HOD + 0.50*ATR, entry + 2.5R)
    """
    orh = candidate.orh
    orl = candidate.orl
    vwap = candidate.vwap
    hod = candidate.hod

    # Buy area
    buy_low = orh
    buy_high = orh + 0.15 * atr

    # Stop
    stop = min(vwap, orl) - 0.10 * atr

    # Entry (midpoint of buy area)
    entry = (buy_low + buy_high) / 2

    # Risk (R)
    risk = entry - stop

    # Targets
    t1 = entry + risk
    t2 = entry + 2 * risk
    t3 = max(hod + 0.50 * atr, entry + 2.5 * risk)

    return TradeLevels(
        setup_type="ORB Breakout",
        buy_area=(buy_low, buy_high),
        stop=stop,
        target_1=t1,
        target_2=t2,
        target_3=t3,
        risk_reward=1.0,  # 1R to T1
        explanation=(
            f"ORB Breakout: Price broke above Opening Range High ${orh:.2f}. "
            f"Stop below VWAP/ORL at ${stop:.2f}. "
            f"Targeting 1R/2R/HOD extension."
        ),
        risk_flags=compute_risk_flags(candidate),
    )


def compute_vwap_reclaim_levels(candidate: Candidate, atr: float) -> TradeLevels:
    """
    Compute levels for VWAP Reclaim setup.

    Buy area: [VWAP, VWAP + 0.20*ATR]
    Stop: VWAP - 0.25*ATR
    Targets: entry + 1R, entry + 2R, HOD retest (if below) else entry + 2.5R
    """
    vwap = candidate.vwap
    hod = candidate.hod
    last = candidate.last

    # Buy area
    buy_low = vwap
    buy_high = vwap + 0.20 * atr

    # Stop
    stop = vwap - 0.25 * atr

    # Entry
    entry = (buy_low + buy_high) / 2

    # Risk
    risk = entry - stop

    # Targets
    t1 = entry + risk
    t2 = entry + 2 * risk

    # T3: HOD retest if we're below it, else extension
    if last < hod:
        t3 = hod
    else:
        t3 = entry + 2.5 * risk

    return TradeLevels(
        setup_type="VWAP Reclaim",
        buy_area=(buy_low, buy_high),
        stop=stop,
        target_1=t1,
        target_2=t2,
        target_3=t3,
        risk_reward=1.0,
        explanation=(
            f"VWAP Reclaim: Price reclaimed VWAP ${vwap:.2f} from below. "
            f"Stop below VWAP at ${stop:.2f}. "
            f"Targeting 1R/2R/HOD retest."
        ),
        risk_flags=compute_risk_flags(candidate),
    )


def compute_first_pullback_levels(candidate: Candidate, atr: float) -> TradeLevels:
    """
    Compute levels for First Pullback setup.

    Buy area: [PullbackLow + 0.10*ATR, PullbackLow + 0.30*ATR]
    Stop: PullbackLow - 0.20*ATR
    Targets: entry + 1R, entry + 2R, HOD + 0.25*ATR
    """
    pullback_low = candidate.pullback_low
    hod = candidate.hod

    if pullback_low is None:
        # Fallback if somehow pullback_low is missing
        pullback_low = candidate.lod

    # Buy area
    buy_low = pullback_low + 0.10 * atr
    buy_high = pullback_low + 0.30 * atr

    # Stop
    stop = pullback_low - 0.20 * atr

    # Entry
    entry = (buy_low + buy_high) / 2

    # Risk
    risk = entry - stop

    # Targets
    t1 = entry + risk
    t2 = entry + 2 * risk
    t3 = hod + 0.25 * atr

    return TradeLevels(
        setup_type="First Pullback",
        buy_area=(buy_low, buy_high),
        stop=stop,
        target_1=t1,
        target_2=t2,
        target_3=t3,
        risk_reward=1.0,
        explanation=(
            f"First Pullback: Trend continuation from pullback low ${pullback_low:.2f}. "
            f"Stop below pullback at ${stop:.2f}. "
            f"Targeting 1R/2R/HOD extension."
        ),
        risk_flags=compute_risk_flags(candidate),
    )


def compute_fallback_levels(candidate: Candidate, atr: float) -> TradeLevels:
    """
    Compute conservative fallback levels when no clean setup.

    Buy area: [VWAP, VWAP + 0.15*ATR] if last > VWAP, else skip
    Stop: VWAP - 0.25*ATR
    Targets: 1R / 2R only
    """
    vwap = candidate.vwap
    last = candidate.last

    flags = compute_risk_flags(candidate)

    # Skip if below VWAP
    if last <= vwap:
        return TradeLevels(
            setup_type="No clean setup",
            buy_area=None,
            stop=None,
            target_1=None,
            target_2=None,
            target_3=None,
            risk_reward=None,
            explanation="No clean setup: Price below VWAP. Skip or wait for reclaim.",
            risk_flags=flags,
        )

    # Conservative levels
    buy_low = vwap
    buy_high = vwap + 0.15 * atr
    stop = vwap - 0.25 * atr
    entry = (buy_low + buy_high) / 2
    risk = entry - stop
    t1 = entry + risk
    t2 = entry + 2 * risk

    return TradeLevels(
        setup_type="No clean setup",
        buy_area=(buy_low, buy_high),
        stop=stop,
        target_1=t1,
        target_2=t2,
        target_3=None,
        risk_reward=1.0,
        explanation=(
            f"No clean setup: Conservative VWAP-based entry. "
            f"Price ${last:.2f} above VWAP ${vwap:.2f}. "
            f"Limited to 1R/2R targets."
        ),
        risk_flags=flags,
    )


def compute_levels(candidate: Candidate) -> TradeLevels:
    """
    Compute trade levels for a candidate.

    Classifies setup and delegates to appropriate level calculator.

    Args:
        candidate: Enriched candidate with indicators

    Returns:
        TradeLevels object with buy area, stop, and targets
    """
    atr = candidate.atr_1m

    # Use a minimum ATR to avoid divide-by-zero issues
    if atr <= 0:
        atr = candidate.last * 0.001  # 0.1% of price as fallback

    # Classify setup
    setup_type = classify_setup(candidate)

    # Compute levels based on setup type
    if setup_type == "ORB Breakout":
        return compute_orb_breakout_levels(candidate, atr)
    elif setup_type == "VWAP Reclaim":
        return compute_vwap_reclaim_levels(candidate, atr)
    elif setup_type == "First Pullback":
        return compute_first_pullback_levels(candidate, atr)
    else:
        return compute_fallback_levels(candidate, atr)


def add_levels_to_picks(picks: list[Candidate]) -> list[dict]:
    """
    Compute levels for all picks and return enriched data.

    Args:
        picks: List of top picked candidates

    Returns:
        List of dicts with candidate data and levels
    """
    results = []

    for pick in picks:
        try:
            levels = compute_levels(pick)

            result = {
                **pick.to_dict(),
                "levels": levels.to_dict(),
                "score": pick.metadata.get("final_score", 0),
            }

            results.append(result)
            logger.info(
                f"{pick.symbol}: {levels.setup_type} - "
                f"Buy ${levels.buy_area[0]:.2f}-${levels.buy_area[1]:.2f} "
                if levels.buy_area
                else f"{pick.symbol}: {levels.setup_type} - No entry"
            )

        except Exception as e:
            logger.warning(f"Failed to compute levels for {pick.symbol}: {e}")
            # Include without levels
            results.append({
                **pick.to_dict(),
                "levels": None,
                "score": pick.metadata.get("final_score", 0),
            })

    return results

