"""Levels module for computing buy/stop/target levels based on setup type."""

import logging
from dataclasses import dataclass, field
from typing import Literal

from app.config import get_settings
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


@dataclass
class PositionSizing:
    """Position sizing and P&L calculations for a trade."""

    shares: int
    entry_price: float
    risk_per_share: float
    total_risk: float
    profit_t1: float
    profit_t2: float
    profit_t3: float | None
    meets_daily_goal: bool
    capital: float
    max_risk_pct: float

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "shares": self.shares,
            "entry_price": round(self.entry_price, 2),
            "risk_per_share": round(self.risk_per_share, 2),
            "total_risk": round(self.total_risk, 2),
            "profit_t1": round(self.profit_t1, 2),
            "profit_t2": round(self.profit_t2, 2),
            "profit_t3": round(self.profit_t3, 2) if self.profit_t3 else None,
            "meets_daily_goal": self.meets_daily_goal,
            "capital": round(self.capital, 2),
            "max_risk_pct": round(self.max_risk_pct, 2),
        }


def compute_position_sizing(
    levels: TradeLevels,
    capital: float | None = None,
    max_risk_pct: float | None = None,
    daily_goal: float | None = None,
) -> PositionSizing | None:
    """
    Compute position sizing and dollar P&L for a trade.

    Args:
        levels: TradeLevels with buy_area, stop, and targets
        capital: Trading capital (default from settings)
        max_risk_pct: Max risk as % of capital (default from settings)
        daily_goal: Daily profit goal (default from settings)

    Returns:
        PositionSizing object or None if no valid entry
    """
    settings = get_settings()
    capital = capital or settings.trading_capital
    max_risk_pct = max_risk_pct or settings.max_risk_pct
    daily_goal = daily_goal or settings.daily_profit_goal

    # Need valid buy area and stop
    if not levels.buy_area or not levels.stop:
        return None

    # Entry is midpoint of buy area
    entry_price = (levels.buy_area[0] + levels.buy_area[1]) / 2

    # Risk per share
    risk_per_share = entry_price - levels.stop
    if risk_per_share <= 0:
        return None

    # Max risk in dollars
    max_risk_dollars = capital * (max_risk_pct / 100)

    # Position size (shares)
    shares = int(max_risk_dollars / risk_per_share)
    if shares <= 0:
        return None

    # Ensure we don't exceed capital
    max_shares_by_capital = int(capital / entry_price)
    shares = min(shares, max_shares_by_capital)

    if shares <= 0:
        return None

    # Actual risk
    total_risk = shares * risk_per_share

    # Profit at each target
    profit_t1 = shares * (levels.target_1 - entry_price) if levels.target_1 else 0
    profit_t2 = shares * (levels.target_2 - entry_price) if levels.target_2 else 0
    profit_t3 = shares * (levels.target_3 - entry_price) if levels.target_3 else None

    # Check if T1 meets daily goal
    meets_daily_goal = profit_t1 >= daily_goal

    return PositionSizing(
        shares=shares,
        entry_price=entry_price,
        risk_per_share=risk_per_share,
        total_risk=total_risk,
        profit_t1=profit_t1,
        profit_t2=profit_t2,
        profit_t3=profit_t3,
        meets_daily_goal=meets_daily_goal,
        capital=capital,
        max_risk_pct=max_risk_pct,
    )


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


@dataclass
class PositionSize:
    """Position sizing data for a trade setup."""
    
    capital: float              # Trading capital
    shares: int                 # Number of shares to buy
    entry_price: float          # Entry price (midpoint of buy area)
    stop_price: float           # Stop loss price
    risk_per_share: float       # Dollar risk per share
    total_risk: float           # Total dollar risk
    max_risk_percent: float     # Risk as % of capital
    profit_t1: float            # Profit at T1 in dollars
    profit_t2: float            # Profit at T2 in dollars
    profit_t3: float | None     # Profit at T3 in dollars (if T3 exists)
    daily_goal: float           # Daily profit goal
    meets_daily_goal: bool      # True if T1 profit >= daily goal
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "capital": self.capital,
            "shares": self.shares,
            "entry_price": round(self.entry_price, 2),
            "stop_price": round(self.stop_price, 2),
            "risk_per_share": round(self.risk_per_share, 2),
            "total_risk": round(self.total_risk, 2),
            "max_risk_percent": round(self.max_risk_percent, 2),
            "profit_t1": round(self.profit_t1, 2),
            "profit_t2": round(self.profit_t2, 2),
            "profit_t3": round(self.profit_t3, 2) if self.profit_t3 else None,
            "daily_goal": self.daily_goal,
            "meets_daily_goal": self.meets_daily_goal,
        }


def compute_position_sizing(levels: TradeLevels) -> PositionSize | None:
    """
    Compute position sizing based on trade levels and config.
    
    Uses max risk % to determine position size, then calculates
    expected profits at each target.
    
    Args:
        levels: TradeLevels with buy_area, stop, and targets
        
    Returns:
        PositionSize object or None if no valid entry
    """
    settings = get_settings()
    
    # Skip if no buy area or stop
    if not levels.buy_area or not levels.stop:
        return None
    
    capital = settings.trading_capital
    max_risk_pct = settings.max_risk_percent
    daily_goal = settings.daily_profit_goal
    
    # Calculate entry price (midpoint of buy area)
    entry = (levels.buy_area[0] + levels.buy_area[1]) / 2
    stop = levels.stop
    
    # Risk per share
    risk_per_share = entry - stop
    
    if risk_per_share <= 0:
        return None
    
    # Max dollar risk
    max_risk_dollars = capital * (max_risk_pct / 100)
    
    # Position size (shares)
    shares = int(max_risk_dollars / risk_per_share)
    
    # Make sure we can afford the shares
    max_shares_by_capital = int(capital / entry)
    shares = min(shares, max_shares_by_capital)
    
    if shares <= 0:
        return None
    
    # Actual risk
    total_risk = shares * risk_per_share
    
    # Profits at each target
    profit_t1 = shares * (levels.target_1 - entry) if levels.target_1 else 0
    profit_t2 = shares * (levels.target_2 - entry) if levels.target_2 else 0
    profit_t3 = shares * (levels.target_3 - entry) if levels.target_3 else None
    
    # Check if meets daily goal at T1
    meets_goal = profit_t1 >= daily_goal
    
    return PositionSize(
        capital=capital,
        shares=shares,
        entry_price=entry,
        stop_price=stop,
        risk_per_share=risk_per_share,
        total_risk=total_risk,
        max_risk_percent=max_risk_pct,
        profit_t1=profit_t1,
        profit_t2=profit_t2,
        profit_t3=profit_t3,
        daily_goal=daily_goal,
        meets_daily_goal=meets_goal,
    )


def add_levels_to_picks(picks: list[Candidate]) -> list[dict]:
    """
    Compute levels and position sizing for all picks.

    Args:
        picks: List of top picked candidates

    Returns:
        List of dicts with candidate data, levels, and position sizing
    """
    results = []

    for pick in picks:
        try:
            levels = compute_levels(pick)
            
            # Compute position sizing
            position = compute_position_sizing(levels)

            result = {
                **pick.to_dict(),
                "levels": levels.to_dict(),
                "position": position.to_dict() if position else None,
                "score": pick.metadata.get("final_score", 0),
            }

            results.append(result)
            
            # Enhanced logging with position info
            if levels.buy_area and position:
                logger.info(
                    f"{pick.symbol}: {levels.setup_type} - "
                    f"Buy ${levels.buy_area[0]:.2f}-${levels.buy_area[1]:.2f} | "
                    f"{position.shares} shares | Risk ${position.total_risk:.2f} | "
                    f"T1 profit ${position.profit_t1:.2f}"
                )
            elif levels.buy_area:
                logger.info(
                    f"{pick.symbol}: {levels.setup_type} - "
                    f"Buy ${levels.buy_area[0]:.2f}-${levels.buy_area[1]:.2f}"
                )
            else:
                logger.info(f"{pick.symbol}: {levels.setup_type} - No entry")

        except Exception as e:
            logger.warning(f"Failed to compute levels for {pick.symbol}: {e}")
            # Include without levels
            results.append({
                **pick.to_dict(),
                "levels": None,
                "position": None,
                "score": pick.metadata.get("final_score", 0),
            })

    return results

