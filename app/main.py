"""Main entry point for the Momentum Watchlist scanner."""

import logging
import sys
from datetime import datetime

from app import __version__
from app.config import get_settings
from app.emailer import (
    send_market_closed_email,
    send_no_picks_email,
    send_watchlist_email,
)
from app.levels import add_levels_to_picks
from app.market_calendar import is_market_open_today
from app.persist import commit_to_repo, history_exists, save_run
from app.provider_yfinance import get_provider
from app.ranker import rank_candidates
from app.scanner import run_scan
from app.time_gate import (
    format_chicago_timestamp,
    get_today_date_str,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_SKIPPED = 2


def build_run_meta(provider_info: dict | None = None) -> dict:
    """Build run metadata dictionary."""
    return {
        "run_ts_ct": format_chicago_timestamp(),
        "provider": provider_info.name if provider_info else "unknown",
        "data_type": provider_info.data_type if provider_info else "unknown",
        "version": __version__,
        "date": get_today_date_str(),
    }


def main() -> int:
    """
    Main entry point for the momentum scanner.

    Returns:
        Exit code (0=success, 1=error, 2=skipped)
    """
    logger.info(f"Momentum Watchlist v{__version__} starting...")

    settings = get_settings()

    # Step 1: Check for duplicate run
    if history_exists():
        logger.info("Run already completed today, exiting.")
        return EXIT_SKIPPED

    # Step 3: Check market calendar
    logger.info("Checking market calendar...")
    market_open = is_market_open_today()

    if not market_open:
        logger.info("Market is closed today.")
        run_meta = build_run_meta()

        if settings.send_market_closed_email:
            send_market_closed_email(run_meta)
            logger.info("Sent market closed email.")

        return EXIT_SUCCESS

    # Step 4: Initialize provider
    logger.info("Initializing data provider...")
    try:
        provider = get_provider()
        provider_info = provider.info
        logger.info(f"Provider: {provider_info.name} ({provider_info.data_type})")
    except Exception as e:
        logger.error(f"Failed to initialize provider: {e}")
        return EXIT_ERROR

    run_meta = build_run_meta(provider_info)

    # Step 5: Run scanner
    logger.info("Running scanner...")
    try:
        candidates, rejected = run_scan(provider)
        logger.info(f"Scan complete: {len(candidates)} candidates, {len(rejected)} rejected")
    except Exception as e:
        logger.error(f"Scanner failed: {e}")
        return EXIT_ERROR

    # Step 6: Rank candidates
    logger.info("Ranking candidates...")
    try:
        picks, leaderboard = rank_candidates(candidates)
        logger.info(f"Selected {len(picks)} picks")
    except Exception as e:
        logger.error(f"Ranking failed: {e}")
        return EXIT_ERROR

    # Step 7: Compute levels for picks
    logger.info("Computing trade levels...")
    try:
        picks_with_levels = add_levels_to_picks(picks)
    except Exception as e:
        logger.error(f"Levels computation failed: {e}")
        return EXIT_ERROR

    # Step 8: Send email
    logger.info(f"Sending email... (picks={len(picks_with_levels)}, rejected={len(rejected)})")
    try:
        if picks_with_levels:
            email_sent = send_watchlist_email(picks_with_levels, leaderboard, run_meta)
        else:
            # No picks - send rejection report
            rejected_dicts = [
                {"symbol": r.symbol, "rejection_reason": r.rejection_reason}
                for r in rejected[:10]
            ]
            logger.info(f"Sending no-picks email with {len(rejected_dicts)} rejections")
            email_sent = send_no_picks_email(
                top_movers=[],
                rejected=rejected_dicts,
                run_meta=run_meta,
            )

        if email_sent:
            logger.info("Email sent successfully.")
        else:
            logger.warning("Email sending failed - check SendGrid configuration.")
    except Exception as e:
        logger.error(f"Email failed with exception: {e}", exc_info=True)
        # Continue to persist even if email fails

    # Step 9: Persist results
    logger.info("Persisting results...")
    try:
        success, path = save_run(picks_with_levels, leaderboard, run_meta)

        if success and path:
            # Commit to repo (only in GitHub Actions)
            commit_to_repo(path)
    except Exception as e:
        logger.error(f"Persistence failed: {e}")
        # Non-fatal, continue

    logger.info("Run complete.")
    return EXIT_SUCCESS


def run_force() -> int:
    """
    Force a run ignoring time gate and duplicate checks.

    Useful for testing and manual runs.

    Returns:
        Exit code
    """
    logger.info("FORCE MODE: Ignoring time gate and duplicate checks")

    settings = get_settings()

    # Check market calendar (still respect this)
    market_open = is_market_open_today()

    if not market_open:
        logger.info("Market is closed today, but continuing in force mode...")

    # Initialize provider
    try:
        provider = get_provider()
        provider_info = provider.info
    except Exception as e:
        logger.error(f"Failed to initialize provider: {e}")
        return EXIT_ERROR

    run_meta = build_run_meta(provider_info)

    # Run scanner
    try:
        candidates, rejected = run_scan(provider)
    except Exception as e:
        logger.error(f"Scanner failed: {e}")
        return EXIT_ERROR

    # Rank
    try:
        picks, leaderboard = rank_candidates(candidates)
    except Exception as e:
        logger.error(f"Ranking failed: {e}")
        return EXIT_ERROR

    # Levels
    try:
        picks_with_levels = add_levels_to_picks(picks)
    except Exception as e:
        logger.error(f"Levels failed: {e}")
        return EXIT_ERROR

    # Email
    try:
        if picks_with_levels:
            send_watchlist_email(picks_with_levels, leaderboard, run_meta)
        else:
            rejected_dicts = [
                {"symbol": r.symbol, "rejection_reason": r.rejection_reason}
                for r in rejected[:10]
            ]
            send_no_picks_email([], rejected_dicts, run_meta)
    except Exception as e:
        logger.error(f"Email failed: {e}")

    # Persist with force
    try:
        save_run(picks_with_levels, leaderboard, run_meta, force=True)
    except Exception as e:
        logger.error(f"Persistence failed: {e}")

    return EXIT_SUCCESS


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Momentum Watchlist Scanner")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force run, ignoring time gate and duplicate checks",
    )
    args = parser.parse_args()

    if args.force:
        sys.exit(run_force())
    else:
        sys.exit(main())

