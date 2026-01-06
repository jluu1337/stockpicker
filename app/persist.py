"""Persistence module for saving daily run results."""

import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from app import __version__
from app.time_gate import format_chicago_timestamp, get_today_date_str

logger = logging.getLogger(__name__)

# Base directory for history files
HISTORY_DIR = Path(__file__).parent.parent / "data" / "history"


def get_history_path(date_str: str | None = None) -> Path:
    """
    Get the path for a daily history file.

    Args:
        date_str: Date string YYYY-MM-DD (default: today)

    Returns:
        Path to history JSON file
    """
    if date_str is None:
        date_str = get_today_date_str()

    return HISTORY_DIR / f"{date_str}.json"


def history_exists(date_str: str | None = None) -> bool:
    """
    Check if history file already exists for a date.

    Args:
        date_str: Date string YYYY-MM-DD (default: today)

    Returns:
        True if file exists
    """
    path = get_history_path(date_str)
    exists = path.exists()

    if exists:
        logger.info(f"History file already exists: {path}")

    return exists


def save_run(
    picks: list[dict],
    leaderboard: list[dict],
    run_meta: dict,
    force: bool = False,
) -> tuple[bool, Path | None]:
    """
    Save run results to JSON file.

    Args:
        picks: List of pick dicts with levels
        leaderboard: Top 10 leaderboard entries
        run_meta: Run metadata
        force: Overwrite if file exists

    Returns:
        Tuple of (success, file_path)
    """
    date_str = get_today_date_str()
    path = get_history_path(date_str)

    # Check for existing file
    if path.exists() and not force:
        logger.warning(f"History file exists, skipping (use force=True to overwrite): {path}")
        return False, path

    # Ensure directory exists
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    # Build output data
    output = {
        "run_ts_ct": run_meta.get("run_ts_ct", format_chicago_timestamp()),
        "provider": run_meta.get("provider", "unknown"),
        "data_type": run_meta.get("data_type", "unknown"),
        "version": run_meta.get("version", __version__),
        "picks_count": len(picks),
        "picks": picks,
        "leaderboard": leaderboard,
    }

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, default=str)

        logger.info(f"Saved run to {path}")
        return True, path

    except Exception as e:
        logger.error(f"Failed to save run: {e}")
        return False, None


def commit_to_repo(path: Path, message: str | None = None) -> bool:
    """
    Commit and push the history file to the repository.

    Only runs if in GitHub Actions environment.

    Args:
        path: Path to file to commit
        message: Commit message (default: auto-generated)

    Returns:
        True if committed successfully (or not in Actions)
    """
    # Only commit in GitHub Actions
    if not os.environ.get("GITHUB_ACTIONS"):
        logger.info("Not in GitHub Actions, skipping commit")
        return True

    if message is None:
        date_str = get_today_date_str()
        message = f"Add daily scan {date_str}"

    try:
        # Configure git
        subprocess.run(
            ["git", "config", "user.name", "github-actions[bot]"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
            check=True,
            capture_output=True,
        )

        # Add the file
        subprocess.run(
            ["git", "add", str(path)],
            check=True,
            capture_output=True,
        )

        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            capture_output=True,
        )

        if result.returncode == 0:
            logger.info("No changes to commit")
            return True

        # Commit
        subprocess.run(
            ["git", "commit", "-m", message],
            check=True,
            capture_output=True,
        )

        # Push
        subprocess.run(
            ["git", "push"],
            check=True,
            capture_output=True,
        )

        logger.info(f"Committed and pushed: {message}")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"Git operation failed: {e}")
        logger.error(f"Stderr: {e.stderr.decode() if e.stderr else 'N/A'}")
        return False
    except Exception as e:
        logger.error(f"Failed to commit: {e}")
        return False


def load_run(date_str: str) -> dict | None:
    """
    Load a historical run from JSON.

    Args:
        date_str: Date string YYYY-MM-DD

    Returns:
        Run data dict, or None if not found
    """
    path = get_history_path(date_str)

    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load run: {e}")
        return None


def list_history(limit: int = 30) -> list[str]:
    """
    List available history dates.

    Args:
        limit: Maximum number of dates to return

    Returns:
        List of date strings (most recent first)
    """
    if not HISTORY_DIR.exists():
        return []

    files = sorted(HISTORY_DIR.glob("*.json"), reverse=True)

    dates = []
    for f in files[:limit]:
        # Extract date from filename (YYYY-MM-DD.json)
        date_str = f.stem
        dates.append(date_str)

    return dates


def cleanup_old_history(keep_days: int = 90) -> int:
    """
    Remove history files older than keep_days.

    Args:
        keep_days: Number of days to keep

    Returns:
        Number of files deleted
    """
    if not HISTORY_DIR.exists():
        return 0

    from datetime import timedelta

    cutoff = datetime.now() - timedelta(days=keep_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    deleted = 0

    for f in HISTORY_DIR.glob("*.json"):
        date_str = f.stem
        if date_str < cutoff_str:
            try:
                f.unlink()
                deleted += 1
                logger.info(f"Deleted old history: {f}")
            except Exception as e:
                logger.warning(f"Failed to delete {f}: {e}")

    return deleted

