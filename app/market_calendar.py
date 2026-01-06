"""Market calendar module for NYSE trading schedule."""

import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

from app.time_gate import CHICAGO_TZ, get_current_chicago_time

logger = logging.getLogger(__name__)

# NYSE calendar instance (cached)
_nyse_calendar = None

# NYSE timezone
NYSE_TZ = ZoneInfo("America/New_York")


def get_nyse_calendar() -> xcals.ExchangeCalendar:
    """Get cached NYSE calendar instance."""
    global _nyse_calendar
    if _nyse_calendar is None:
        _nyse_calendar = xcals.get_calendar("XNYS")
    return _nyse_calendar


def is_market_open_today(check_date: date | None = None) -> bool:
    """
    Check if NYSE is open on the given date.

    Args:
        check_date: Date to check (default: today in Chicago timezone)

    Returns:
        True if NYSE is open, False otherwise
    """
    if check_date is None:
        check_date = get_current_chicago_time().date()

    cal = get_nyse_calendar()

    try:
        # Check if date is a valid trading session
        is_session = cal.is_session(check_date)
        if is_session:
            logger.info(f"NYSE is OPEN on {check_date}")
        else:
            logger.info(f"NYSE is CLOSED on {check_date} (weekend/holiday)")
        return is_session
    except Exception as e:
        logger.warning(f"Error checking market calendar: {e}. Assuming market is open.")
        # Default to open on weekdays if calendar check fails
        return check_date.weekday() < 5


def get_session_open(check_date: date | None = None) -> datetime:
    """
    Get the market open time for the given date in America/Chicago timezone.

    NYSE opens at 9:30 AM ET, which is 8:30 AM CT (standard) or 8:30 AM CT (DST).

    Args:
        check_date: Date to get open time for (default: today)

    Returns:
        Market open datetime in America/Chicago timezone
    """
    if check_date is None:
        check_date = get_current_chicago_time().date()

    cal = get_nyse_calendar()

    try:
        if cal.is_session(check_date):
            # Get session open in UTC
            session = cal.session_open(check_date)
            # Convert to Chicago time
            return session.astimezone(CHICAGO_TZ)
    except Exception as e:
        logger.warning(f"Error getting session open: {e}")

    # Fallback: 8:30 AM CT (typical NYSE open in Central time)
    return datetime.combine(check_date, time(8, 30), tzinfo=CHICAGO_TZ)


def get_session_close(check_date: date | None = None) -> datetime:
    """
    Get the market close time for the given date in America/Chicago timezone.

    NYSE closes at 4:00 PM ET, which is 3:00 PM CT.

    Args:
        check_date: Date to get close time for (default: today)

    Returns:
        Market close datetime in America/Chicago timezone
    """
    if check_date is None:
        check_date = get_current_chicago_time().date()

    cal = get_nyse_calendar()

    try:
        if cal.is_session(check_date):
            # Get session close in UTC
            session = cal.session_close(check_date)
            # Convert to Chicago time
            return session.astimezone(CHICAGO_TZ)
    except Exception as e:
        logger.warning(f"Error getting session close: {e}")

    # Fallback: 3:00 PM CT (typical NYSE close in Central time)
    return datetime.combine(check_date, time(15, 0), tzinfo=CHICAGO_TZ)


def is_early_close_today(check_date: date | None = None) -> bool:
    """
    Check if today is an early close day (e.g., day before holidays).

    Args:
        check_date: Date to check (default: today)

    Returns:
        True if early close, False otherwise
    """
    if check_date is None:
        check_date = get_current_chicago_time().date()

    cal = get_nyse_calendar()

    try:
        if not cal.is_session(check_date):
            return False

        # Get normal close time (4:00 PM ET = 21:00 UTC in winter, 20:00 UTC in summer)
        close = cal.session_close(check_date)
        # Early closes are typically 1:00 PM ET
        return close.hour < 20  # If close is before 20:00 UTC, it's early
    except Exception as e:
        logger.warning(f"Error checking early close: {e}")
        return False


def get_previous_trading_day(check_date: date | None = None) -> date:
    """
    Get the previous trading day.

    Args:
        check_date: Reference date (default: today)

    Returns:
        Previous trading day date
    """
    if check_date is None:
        check_date = get_current_chicago_time().date()

    cal = get_nyse_calendar()

    try:
        prev_session = cal.previous_session(check_date)
        return prev_session.date() if hasattr(prev_session, "date") else prev_session
    except Exception as e:
        logger.warning(f"Error getting previous trading day: {e}")
        # Fallback: go back day by day until we find a weekday
        from datetime import timedelta

        prev = check_date - timedelta(days=1)
        while prev.weekday() >= 5:  # Skip weekends
            prev -= timedelta(days=1)
        return prev

