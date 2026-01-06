"""Technical indicators computed from 1-minute bars."""

import logging
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


def compute_vwap(bars: pd.DataFrame) -> float:
    """
    Compute Volume Weighted Average Price for the session.

    VWAP = sum(typical_price * volume) / sum(volume)
    where typical_price = (high + low + close) / 3

    Args:
        bars: DataFrame with high, low, close, volume columns

    Returns:
        Session VWAP value
    """
    if bars.empty:
        return 0.0

    typical_price = (bars["high"] + bars["low"] + bars["close"]) / 3
    total_volume = bars["volume"].sum()

    if total_volume == 0:
        return bars["close"].iloc[-1]

    vwap = (typical_price * bars["volume"]).sum() / total_volume
    return float(vwap)


def compute_atr(bars: pd.DataFrame, period: int = 14) -> float:
    """
    Compute Average True Range on 1-minute bars.

    ATR = SMA(TR, period)
    where TR = max(high-low, abs(high-prev_close), abs(low-prev_close))

    Args:
        bars: DataFrame with high, low, close columns
        period: ATR period (default: 14)

    Returns:
        ATR value
    """
    if bars.empty or len(bars) < 2:
        return 0.0

    high = bars["high"]
    low = bars["low"]
    close = bars["close"]

    # Calculate True Range
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Use simple moving average for ATR
    if len(true_range) >= period:
        atr = true_range.rolling(window=period).mean().iloc[-1]
    else:
        atr = true_range.mean()

    return float(atr) if pd.notna(atr) else 0.0


def compute_hod(bars: pd.DataFrame) -> float:
    """
    Compute High of Day from bars.

    Args:
        bars: DataFrame with high column

    Returns:
        Maximum high value
    """
    if bars.empty:
        return 0.0
    return float(bars["high"].max())


def compute_lod(bars: pd.DataFrame) -> float:
    """
    Compute Low of Day from bars.

    Args:
        bars: DataFrame with low column

    Returns:
        Minimum low value
    """
    if bars.empty:
        return 0.0
    return float(bars["low"].min())


def compute_or_levels(
    bars: pd.DataFrame, session_open: datetime, or_minutes: int = 5
) -> tuple[float, float]:
    """
    Compute Opening Range High and Low.

    OR is defined as the first N minutes after market open.

    Args:
        bars: DataFrame with datetime index, high, low columns
        session_open: Market open datetime
        or_minutes: Opening range duration in minutes (default: 5)

    Returns:
        Tuple of (ORH, ORL) - Opening Range High and Low
    """
    if bars.empty:
        return 0.0, 0.0

    # Ensure index is timezone-aware
    if bars.index.tz is None:
        bars = bars.copy()
        bars.index = bars.index.tz_localize("UTC")

    # Make session_open timezone-aware if needed
    if session_open.tzinfo is None:
        from app.time_gate import CHICAGO_TZ

        session_open = session_open.replace(tzinfo=CHICAGO_TZ)

    # Convert to UTC for comparison
    session_open_utc = session_open.astimezone(pd.Timestamp.now("UTC").tz)
    or_end = session_open_utc + timedelta(minutes=or_minutes)

    # Filter bars within OR window
    or_bars = bars[(bars.index >= session_open_utc) & (bars.index < or_end)]

    if or_bars.empty:
        # If no bars in OR window, use first available bars
        or_bars = bars.head(or_minutes)

    if or_bars.empty:
        return 0.0, 0.0

    orh = float(or_bars["high"].max())
    orl = float(or_bars["low"].min())

    return orh, orl


def compute_near_hod(last: float, hod: float) -> float:
    """
    Compute how close current price is to HOD.

    Args:
        last: Current/last price
        hod: High of day

    Returns:
        Ratio clamped to [0, 1]
    """
    if hod <= 0:
        return 0.0
    ratio = last / hod
    return max(0.0, min(1.0, ratio))


def detect_vwap_cross(
    bars: pd.DataFrame, vwap: float, lookback: int = 5
) -> bool:
    """
    Detect if price recently crossed from below to above VWAP.

    Args:
        bars: DataFrame with close column
        vwap: Current VWAP value
        lookback: Number of bars to check

    Returns:
        True if there was a cross from below to above VWAP
    """
    if bars.empty or len(bars) < 2:
        return False

    # Get last N bars
    recent = bars.tail(lookback)

    if len(recent) < 2:
        return False

    closes = recent["close"].values

    # Check if any bar was below VWAP and current is above
    was_below = any(c < vwap for c in closes[:-1])
    now_above = closes[-1] > vwap

    return bool(was_below and now_above)


def find_pullback_low(
    bars: pd.DataFrame, vwap: float, lookback: int = 5
) -> float | None:
    """
    Find pullback low in recent bars that is above VWAP.

    A valid pullback low is the minimum low in the lookback period,
    but only if it's above VWAP.

    Args:
        bars: DataFrame with low column
        vwap: Current VWAP value
        lookback: Number of bars to check

    Returns:
        Pullback low if valid (above VWAP), else None
    """
    if bars.empty or len(bars) < lookback:
        return None

    # Get last N bars
    recent = bars.tail(lookback)

    pullback_low = float(recent["low"].min())

    # Only valid if above VWAP
    if pullback_low > vwap:
        return pullback_low

    return None


def compute_volume_so_far(bars: pd.DataFrame) -> int:
    """
    Compute total volume from bars.

    Args:
        bars: DataFrame with volume column

    Returns:
        Total volume
    """
    if bars.empty:
        return 0
    return int(bars["volume"].sum())


def compute_pct_change(current: float, previous: float) -> float:
    """
    Compute percentage change.

    Args:
        current: Current price
        previous: Previous price (typically previous close)

    Returns:
        Percentage change (e.g., 5.0 for 5%)
    """
    if previous <= 0:
        return 0.0
    return ((current - previous) / previous) * 100


def compute_rvol(
    volume_so_far: int,
    avg_daily_volume: float | None,
    median_volume: float | None = None,
) -> float:
    """
    Compute Relative Volume.

    Preferred: rvol = volume_so_far / avg_daily_volume_20d
    Fallback: rvol_proxy = volume_so_far / median(volume_so_far across candidates)

    Args:
        volume_so_far: Current session volume
        avg_daily_volume: 20-day average daily volume (or None)
        median_volume: Median volume across candidates for fallback

    Returns:
        Relative volume ratio
    """
    if avg_daily_volume is not None and avg_daily_volume > 0:
        return volume_so_far / avg_daily_volume

    if median_volume is not None and median_volume > 0:
        return volume_so_far / median_volume

    return 1.0  # Default to 1.0 if no reference available


def get_last_price(bars: pd.DataFrame) -> float:
    """
    Get the most recent close price.

    Args:
        bars: DataFrame with close column

    Returns:
        Last close price
    """
    if bars.empty:
        return 0.0
    return float(bars["close"].iloc[-1])


def compute_all_indicators(
    bars: pd.DataFrame,
    session_open: datetime,
    prev_close: float | None = None,
    or_minutes: int = 5,
    atr_period: int = 14,
) -> dict:
    """
    Compute all indicators from bars.

    Args:
        bars: 1-minute OHLCV DataFrame
        session_open: Market open datetime
        prev_close: Previous day's close (for pct_change)
        or_minutes: Opening range minutes
        atr_period: ATR period

    Returns:
        Dict with all computed indicators
    """
    last = get_last_price(bars)
    vwap = compute_vwap(bars)
    hod = compute_hod(bars)
    lod = compute_lod(bars)
    near_hod = compute_near_hod(last, hod)
    volume_so_far = compute_volume_so_far(bars)
    atr_1m = compute_atr(bars, period=atr_period)
    orh, orl = compute_or_levels(bars, session_open, or_minutes)

    # Use prev_close for pct_change, fallback to first bar open
    reference = prev_close
    if reference is None and not bars.empty:
        reference = bars["open"].iloc[0]

    pct_change = compute_pct_change(last, reference) if reference else 0.0

    # VWAP cross detection
    vwap_cross = detect_vwap_cross(bars, vwap, lookback=5)

    # Pullback low detection
    pullback_low = find_pullback_low(bars, vwap, lookback=5)

    return {
        "last": last,
        "vwap": vwap,
        "hod": hod,
        "lod": lod,
        "near_hod": near_hod,
        "volume_so_far": volume_so_far,
        "atr_1m": atr_1m,
        "pct_change": pct_change,
        "orh": orh,
        "orl": orl,
        "vwap_cross": vwap_cross,
        "pullback_low": pullback_low,
        "above_vwap": last > vwap,
        "bars": bars,  # Include bars for further analysis
    }

