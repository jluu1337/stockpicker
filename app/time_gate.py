"""Time gate module for DST-safe execution window checking."""

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.config import get_settings

logger = logging.getLogger(__name__)

CHICAGO_TZ = ZoneInfo("America/Chicago")


def get_current_chicago_time() -> datetime:
    """Get current time in America/Chicago timezone."""
    return datetime.now(CHICAGO_TZ)


def is_in_execution_window(
    current_time: datetime | None = None,
    target_hour: int | None = None,
    target_minute: int | None = None,
    window_minutes: int | None = None,
) -> tuple[bool, datetime]:
    """
    Check if current time is within the execution window around target time.

    This is DST-safe because we work in America/Chicago timezone directly.
    GitHub Actions triggers at both UTC times (13:40 and 14:40), but only
    one will fall within the 08:38-08:42 CT window.

    Args:
        current_time: Override current time (for testing)
        target_hour: Target hour in CT (default: from settings)
        target_minute: Target minute (default: from settings)
        window_minutes: Minutes tolerance around target (default: from settings)

    Returns:
        Tuple of (should_run, current_chicago_time)
    """
    settings = get_settings()

    if current_time is None:
        current_time = get_current_chicago_time()
    elif current_time.tzinfo is None:
        # Assume naive datetime is in Chicago time
        current_time = current_time.replace(tzinfo=CHICAGO_TZ)

    if target_hour is None:
        target_hour = settings.target_hour
    if target_minute is None:
        target_minute = settings.target_minute
    if window_minutes is None:
        window_minutes = settings.execution_window_minutes

    # Calculate window bounds
    # Window: [target - window, target + window]
    # e.g., for 08:40 with window=2: 08:38 to 08:42
    target_time = time(target_hour, target_minute)

    # Get current time as time object
    current_t = current_time.time()

    # Calculate minutes from midnight for comparison
    current_minutes = current_t.hour * 60 + current_t.minute
    target_minutes = target_time.hour * 60 + target_time.minute

    # Check if within window
    lower_bound = target_minutes - window_minutes
    upper_bound = target_minutes + window_minutes

    in_window = lower_bound <= current_minutes <= upper_bound

    if in_window:
        logger.info(
            f"Time gate PASSED: {current_time.strftime('%H:%M:%S %Z')} "
            f"is within window [{target_hour:02d}:{target_minute-window_minutes:02d} - "
            f"{target_hour:02d}:{target_minute+window_minutes:02d}]"
        )
    else:
        logger.info(
            f"Time gate SKIPPED: {current_time.strftime('%H:%M:%S %Z')} "
            f"is outside window [{target_hour:02d}:{target_minute-window_minutes:02d} - "
            f"{target_hour:02d}:{target_minute+window_minutes:02d}]"
        )

    return in_window, current_time


def format_chicago_timestamp(dt: datetime | None = None) -> str:
    """Format datetime as Chicago timezone string."""
    if dt is None:
        dt = get_current_chicago_time()
    return dt.strftime("%Y-%m-%d %H:%M:%S CT")


def get_today_date_str(dt: datetime | None = None) -> str:
    """Get today's date as YYYY-MM-DD string in Chicago timezone."""
    if dt is None:
        dt = get_current_chicago_time()
    return dt.strftime("%Y-%m-%d")

