"""Scanner module for seeding, filtering, and enriching stock candidates."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any

from app.config import get_settings
from app.indicators import compute_all_indicators, compute_rvol
from app.market_calendar import get_session_open
from app.provider_base import DataProvider, Mover
from app.time_gate import get_current_chicago_time

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    """Represents a scanned stock candidate with computed features."""

    symbol: str
    last: float = 0.0
    vwap: float = 0.0
    hod: float = 0.0
    lod: float = 0.0
    near_hod: float = 0.0
    volume_so_far: int = 0
    atr_1m: float = 0.0
    pct_change: float = 0.0
    rvol: float = 1.0
    orh: float = 0.0
    orl: float = 0.0
    above_vwap: bool = False
    vwap_cross: bool = False
    pullback_low: float | None = None
    prev_close: float | None = None
    source: str = ""  # "gainers", "most_active"
    type_unknown: bool = True
    is_etf: bool = False
    is_otc: bool = False
    rejection_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Enhanced fields for improved breakout detection
    open_price: float = 0.0           # First bar open price
    vs_open: float = 0.0              # (last - open) / open as %
    is_green_since_open: bool = True  # Direction since open
    shares_float: int | None = None   # Shares float
    market_cap: int | None = None     # Market cap in dollars

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "symbol": self.symbol,
            "last": round(self.last, 2),
            "vwap": round(self.vwap, 2),
            "hod": round(self.hod, 2),
            "lod": round(self.lod, 2),
            "near_hod": round(self.near_hod, 4),
            "volume_so_far": self.volume_so_far,
            "atr_1m": round(self.atr_1m, 4),
            "pct_change": round(self.pct_change, 2),
            "rvol": round(self.rvol, 2),
            "orh": round(self.orh, 2),
            "orl": round(self.orl, 2),
            "above_vwap": self.above_vwap,
            "vwap_cross": self.vwap_cross,
            "pullback_low": round(self.pullback_low, 2) if self.pullback_low else None,
            "source": self.source,
            "type_unknown": self.type_unknown,
            "is_etf": self.is_etf,
            "is_otc": self.is_otc,
            # Enhanced fields
            "open_price": round(self.open_price, 2),
            "vs_open": round(self.vs_open, 2),
            "is_green_since_open": self.is_green_since_open,
            "shares_float": self.shares_float,
            "market_cap": self.market_cap,
        }


def seed_candidates(provider: DataProvider, top_n_seed: int = 100) -> list[Candidate]:
    """
    Seed candidates from top gainers and most active.

    Args:
        provider: Data provider instance
        top_n_seed: Max number of unique symbols to seed

    Returns:
        List of Candidate objects (unfiltered, unenriched)
    """
    logger.info(f"Seeding candidates (top_n_seed={top_n_seed})")

    # Get movers from provider
    movers = provider.get_movers(top_n=top_n_seed)

    # Convert to candidates
    candidates = []
    seen = set()

    for mover in movers:
        if mover.symbol in seen:
            continue
        seen.add(mover.symbol)

        candidates.append(
            Candidate(
                symbol=mover.symbol,
                last=mover.price,
                pct_change=mover.change_percent,
                volume_so_far=mover.volume,
                source=mover.source,
            )
        )

        if len(candidates) >= top_n_seed:
            break

    logger.info(f"Seeded {len(candidates)} unique candidates")
    return candidates


def filter_candidates(
    candidates: list[Candidate],
    min_price: float = 5.0,
    min_volume: int = 1_000_000,
    apply_float_filters: bool = True,
) -> tuple[list[Candidate], list[Candidate]]:
    """
    Filter candidates based on price, volume, float, and market cap thresholds.

    Args:
        candidates: List of candidates to filter
        min_price: Minimum stock price
        min_volume: Minimum volume so far
        apply_float_filters: Whether to apply float/market cap filters (skip on pre-filter)

    Returns:
        Tuple of (passed, rejected) candidates
    """
    settings = get_settings()
    min_price = min_price or settings.min_price
    min_volume = min_volume or settings.min_volume

    passed = []
    rejected = []

    for c in candidates:
        # Price filter
        if c.last < min_price:
            c.rejection_reason = f"Price ${c.last:.2f} < ${min_price}"
            rejected.append(c)
            continue

        # Volume filter
        if c.volume_so_far < min_volume:
            c.rejection_reason = f"Volume {c.volume_so_far:,} < {min_volume:,}"
            rejected.append(c)
            continue

        # OTC filter
        if c.is_otc:
            c.rejection_reason = "OTC stock excluded"
            rejected.append(c)
            continue

        # ETF filter
        if c.is_etf:
            c.rejection_reason = "ETF excluded"
            rejected.append(c)
            continue

        # Apply float/market cap filters only after enrichment
        if apply_float_filters:
            # Float filter (if available)
            if c.shares_float is not None:
                if c.shares_float < settings.min_float:
                    c.rejection_reason = f"Float {c.shares_float:,} < {settings.min_float:,} (low float trap)"
                    rejected.append(c)
                    continue
                if c.shares_float > settings.max_float:
                    c.rejection_reason = f"Float {c.shares_float:,} > {settings.max_float:,} (too heavy)"
                    rejected.append(c)
                    continue

            # Market cap filter (if available)
            if c.market_cap is not None:
                if c.market_cap < settings.min_market_cap:
                    c.rejection_reason = f"Market cap ${c.market_cap:,} < ${settings.min_market_cap:,}"
                    rejected.append(c)
                    continue
                if c.market_cap > settings.max_market_cap:
                    c.rejection_reason = f"Market cap ${c.market_cap:,} > ${settings.max_market_cap:,} (mega cap)"
                    rejected.append(c)
                    continue

            # Extreme % change filter (avoid overextended stocks)
            if c.pct_change > settings.max_pct_change:
                c.rejection_reason = f"% change {c.pct_change:.1f}% > {settings.max_pct_change}% (overextended)"
                rejected.append(c)
                continue

        passed.append(c)

    logger.info(f"Filtered: {len(passed)} passed, {len(rejected)} rejected")
    return passed, rejected


def enrich_candidates(
    candidates: list[Candidate],
    provider: DataProvider,
    session_open: datetime | None = None,
    current_time: datetime | None = None,
) -> list[Candidate]:
    """
    Enrich candidates with full indicator data from 1-min bars.

    Args:
        candidates: List of candidates to enrich
        provider: Data provider instance
        session_open: Market open time (default: auto-detect)
        current_time: Current time for bar request (default: now)

    Returns:
        List of enriched candidates
    """
    if not candidates:
        return []

    # Get session times
    if session_open is None:
        session_open = get_session_open()

    if current_time is None:
        current_time = get_current_chicago_time()

    logger.info(
        f"Enriching {len(candidates)} candidates "
        f"(session: {session_open.strftime('%H:%M')} - {current_time.strftime('%H:%M')} CT)"
    )

    # Get symbols
    symbols = [c.symbol for c in candidates]

    # Batch request for bars
    # Try 1-minute bars first, fall back to 5-minute if not available
    bars_dict = provider.get_bars_batch(
        symbols=symbols,
        start=session_open,
        end=current_time,
        timeframe="1Min",
    )
    
    # If we got no bars at all, try 5-minute (more available outside market hours)
    if not bars_dict:
        logger.info("No 1-min bars available, trying 5-min bars")
        bars_dict = provider.get_bars_batch(
            symbols=symbols,
            start=session_open,
            end=current_time,
            timeframe="5Min",
        )

    # Batch request for previous closes
    prev_closes = provider.get_previous_closes_batch(symbols)

    # Compute median volume for RVOL fallback
    volumes = [c.volume_so_far for c in candidates if c.volume_so_far > 0]
    median_vol = median(volumes) if volumes else None

    # Enrich each candidate
    enriched = []

    for c in candidates:
        try:
            bars = bars_dict.get(c.symbol)

            if bars is None or bars.empty:
                logger.warning(f"No bars for {c.symbol}, skipping")
                continue

            prev_close = prev_closes.get(c.symbol)

            # Compute all indicators
            indicators = compute_all_indicators(
                bars=bars,
                session_open=session_open,
                prev_close=prev_close,
            )

            # Update candidate with indicators
            c.last = indicators["last"]
            c.vwap = indicators["vwap"]
            c.hod = indicators["hod"]
            c.lod = indicators["lod"]
            c.near_hod = indicators["near_hod"]
            c.volume_so_far = indicators["volume_so_far"]
            c.atr_1m = indicators["atr_1m"]
            c.pct_change = indicators["pct_change"]
            c.orh = indicators["orh"]
            c.orl = indicators["orl"]
            c.above_vwap = indicators["above_vwap"]
            c.vwap_cross = indicators["vwap_cross"]
            c.pullback_low = indicators["pullback_low"]
            c.prev_close = prev_close
            
            # Enhanced fields for breakout detection
            c.open_price = indicators.get("open_price", 0.0)
            c.vs_open = indicators.get("vs_open", 0.0)
            c.is_green_since_open = c.last > c.open_price if c.open_price > 0 else True

            # Compute RVOL (fallback to median)
            metadata = provider.get_metadata(c.symbol)
            avg_vol_20d = metadata.get("avg_volume_20d")
            c.rvol = compute_rvol(c.volume_so_far, avg_vol_20d, median_vol)

            # Update metadata
            c.type_unknown = metadata.get("type_unknown", True)
            c.is_etf = metadata.get("is_etf", False)
            c.is_otc = metadata.get("is_otc", False)
            c.shares_float = metadata.get("shares_float")
            c.market_cap = metadata.get("market_cap")

            # Store bars in metadata for levels computation
            c.metadata["bars"] = bars

            enriched.append(c)

        except Exception as e:
            logger.warning(f"Failed to enrich {c.symbol}: {e}")
            continue

    logger.info(f"Enriched {len(enriched)} candidates successfully")
    return enriched


def run_scan(provider: DataProvider) -> tuple[list[Candidate], list[Candidate]]:
    """
    Run the full scan pipeline: seed, filter, enrich.

    Args:
        provider: Data provider instance

    Returns:
        Tuple of (enriched_candidates, rejected_candidates)
    """
    settings = get_settings()

    # Seed candidates
    candidates = seed_candidates(provider, top_n_seed=settings.top_n_seed)

    # Pre-filter before enrichment (saves API calls)
    # Skip float/market cap filters here since we don't have that data yet
    passed, rejected = filter_candidates(
        candidates,
        min_price=settings.min_price,
        min_volume=settings.min_volume,
        apply_float_filters=False,  # Don't apply float/cap filters before enrichment
    )

    # Enrich passed candidates
    enriched = enrich_candidates(passed, provider)

    # Re-filter after enrichment with accurate data + float/market cap filters
    final_passed, newly_rejected = filter_candidates(
        enriched,
        min_price=settings.min_price,
        min_volume=settings.min_volume,
        apply_float_filters=True,  # Now apply float/market cap filters
    )

    # Combine rejected
    all_rejected = rejected + newly_rejected

    return final_passed, all_rejected

