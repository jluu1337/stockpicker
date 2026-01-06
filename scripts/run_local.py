#!/usr/bin/env python
"""
Local runner script for testing the momentum watchlist.

Usage:
    python scripts/run_local.py              # Normal run (respects time gate)
    python scripts/run_local.py --force      # Force run (ignores time gate)
    python scripts/run_local.py --dry-run    # Dry run (no email, no persist)
"""

import argparse
import os
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file
from dotenv import load_dotenv
load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Run Momentum Watchlist locally")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force run, ignoring time gate and duplicate checks",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true", 
        help="Dry run: scan and rank but don't email or persist",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN MODE ===\n")
        run_dry()
    elif args.force:
        from app.main import run_force
        sys.exit(run_force())
    else:
        from app.main import main as run_main
        sys.exit(run_main())


def run_dry():
    """Run scan and ranking without email or persistence."""
    from app.config import get_settings
    from app.market_calendar import is_market_open_today
    from app.provider_yfinance import get_provider
    from app.scanner import run_scan
    from app.ranker import rank_candidates
    from app.levels import add_levels_to_picks
    
    settings = get_settings()
    
    print(f"Settings:")
    print(f"  MIN_PRICE: {settings.min_price}")
    print(f"  MIN_VOLUME: {settings.min_volume}")
    print(f"  PICKS: {settings.picks}")
    print(f"  TOP_N_SEED: {settings.top_n_seed}")
    print()
    
    print(f"Market open today: {is_market_open_today()}")
    print()
    
    print("Initializing provider...")
    provider = get_provider()
    print(f"Provider: {provider.info.name} ({provider.info.data_type})")
    print()
    
    print("Running scanner...")
    candidates, rejected = run_scan(provider)
    print(f"  Candidates: {len(candidates)}")
    print(f"  Rejected: {len(rejected)}")
    print()
    
    if rejected:
        print("Sample rejections:")
        for r in rejected[:5]:
            print(f"  {r.symbol}: {r.rejection_reason}")
        print()
    
    print("Ranking candidates...")
    picks, leaderboard = rank_candidates(candidates)
    print(f"  Selected {len(picks)} picks")
    print()
    
    print("Computing levels...")
    picks_with_levels = add_levels_to_picks(picks)
    print()
    
    print("=" * 60)
    print("PICKS")
    print("=" * 60)
    for i, p in enumerate(picks_with_levels):
        levels = p.get("levels", {})
        print(f"\n#{i+1} {p['symbol']}")
        print(f"  Last: ${p['last']:.2f} ({p['pct_change']:+.2f}%)")
        print(f"  Score: {p['score']:.3f}")
        print(f"  Setup: {levels.get('setup_type', 'N/A')}")
        if levels.get('buy_area'):
            print(f"  Buy: ${levels['buy_area'][0]:.2f} - ${levels['buy_area'][1]:.2f}")
            print(f"  Stop: ${levels.get('stop', 0):.2f}")
            print(f"  T1: ${levels.get('target_1', 0):.2f} | T2: ${levels.get('target_2', 0):.2f}")
        if levels.get('risk_flags'):
            print(f"  Flags: {', '.join(levels['risk_flags'])}")
    
    print("\n" + "=" * 60)
    print("LEADERBOARD")
    print("=" * 60)
    print(f"{'Rank':<5} {'Symbol':<8} {'Score':>8} {'%Chg':>8} {'RVOL':>8}")
    print("-" * 40)
    for entry in leaderboard:
        print(f"{entry['rank']:<5} {entry['symbol']:<8} {entry['score']:>8.3f} {entry['pct_change']:>+7.2f}% {entry['rvol']:>7.1f}x")
    
    print("\n=== DRY RUN COMPLETE ===")
    print("No email sent. No history saved.")


if __name__ == "__main__":
    main()

