# Momentum Watchlist

A GitHub Actions–scheduled stock momentum scanner that sends a daily email watchlist at 8:40 AM Central Time.

## Features

- **Automated Daily Scans**: Runs automatically via GitHub Actions on trading days
- **DST-Safe Scheduling**: Dual cron schedule ensures correct 8:40 AM CT execution year-round
- **Momentum Scoring**: Rank-normalized scoring based on % change, relative volume, and proximity to HOD
- **Trade Levels**: Rule-based buy areas, stops, and targets (T1/T2/T3) for each setup
- **Setup Classification**: Identifies ORB Breakout, VWAP Reclaim, First Pullback, or conservative fallback
- **Email Delivery**: Beautiful HTML email via SendGrid with picks and top-10 leaderboard
- **History Persistence**: Daily results saved as JSON and committed to the repo

## Quick Start

### 1. Fork/Clone the Repository

```bash
git clone https://github.com/yourusername/momentum-watchlist.git
cd momentum-watchlist
```

### 2. Set Up Local Environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp env.example .env
```

### 3. Configure API Keys

Edit `.env` with your credentials:

- **Alpaca Markets**: Get API keys from [alpaca.markets](https://alpaca.markets/)
- **SendGrid**: Get API key from [sendgrid.com](https://sendgrid.com/)

### 4. Test Locally

```bash
# Run with force flag (ignores time gate)
python -m app.main --force
```

### 5. Configure GitHub Secrets

In your GitHub repository, go to **Settings → Secrets and variables → Actions** and add:

| Secret | Description |
|--------|-------------|
| `APCA_API_KEY_ID` | Alpaca API Key ID |
| `APCA_API_SECRET_KEY` | Alpaca API Secret Key |
| `SENDGRID_API_KEY` | SendGrid API Key |
| `FROM_EMAIL` | Sender email address |
| `TO_EMAIL` | Recipient email address |

### 6. Enable GitHub Actions

Push to your repository. The workflow runs automatically at 8:40 AM CT on weekdays.

## Architecture

```
momentum-watchlist/
├── app/
│   ├── __init__.py         # Package init with version
│   ├── config.py           # Pydantic settings management
│   ├── time_gate.py        # DST-safe execution window check
│   ├── market_calendar.py  # NYSE calendar integration
│   ├── provider_base.py    # Abstract data provider interface
│   ├── provider_alpaca.py  # Alpaca implementation
│   ├── indicators.py       # VWAP, ATR, ORH/ORL, etc.
│   ├── scanner.py          # Candidate seeding and filtering
│   ├── ranker.py           # Score computation and ranking
│   ├── levels.py           # Trade level calculation
│   ├── emailer.py          # SendGrid email formatting
│   ├── persist.py          # JSON history persistence
│   └── main.py             # Main entry point
├── data/history/           # Daily JSON outputs (git-committed)
├── tests/                  # Unit tests
├── .github/workflows/      # GitHub Actions workflow
├── requirements.txt        # Python dependencies
├── .env.example            # Environment template
└── README.md               # This file
```

## How It Works

### Scheduling (DST-Safe)

GitHub Actions only supports UTC cron schedules. To hit 8:40 AM Central Time year-round:

1. **Two cron triggers**: `40 13 * * 1-5` (CDT) and `40 14 * * 1-5` (CST)
2. **Time gate in code**: Only proceeds if current CT time is within 08:38-08:42
3. **Result**: Exactly one run per trading day at the right time

### Scanning Pipeline

1. **Seed Candidates**: Get top gainers + most active from Alpaca (up to 100)
2. **Filter**: Apply price (≥$5) and volume (≥1M) thresholds
3. **Enrich**: Fetch 1-minute bars and compute indicators
4. **Score**: Rank-normalize and apply bonuses/penalties
5. **Select**: Pick top 3-5 by final score
6. **Levels**: Compute buy area, stop, and targets for each
7. **Email**: Send formatted HTML via SendGrid
8. **Persist**: Save JSON and commit to repo

### Scoring Formula

```
base_score = 0.40 × pct_change_rank + 0.35 × rvol_rank + 0.25 × near_hod_rank

Adjustments:
  +0.05 if price > VWAP
  -0.10 if price < VWAP
  -0.05 if overextended (price > VWAP × 1.03)
```

### Setup Types

| Setup | Condition | Entry |
|-------|-----------|-------|
| **ORB Breakout** | Price ≥ ORH, above VWAP, near_hod ≥ 0.98 | Above ORH |
| **VWAP Reclaim** | Price > VWAP, recently crossed from below | At VWAP |
| **First Pullback** | Above VWAP, near_hod ≥ 0.97, pullback low > VWAP | Above pullback |
| **Fallback** | None of the above | Conservative/Skip |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MIN_PRICE` | 5 | Minimum stock price |
| `MIN_VOLUME` | 1,000,000 | Minimum volume so far |
| `PICKS` | 5 | Number of picks (3-5) |
| `TOP_N_SEED` | 100 | Candidates to seed |
| `SEND_MARKET_CLOSED_EMAIL` | false | Email on closed days |

### GitHub Variables (Optional)

Set repository variables for configuration overrides:
- `MIN_PRICE`, `MIN_VOLUME`, `PICKS`, `TOP_N_SEED`

## API Requirements

### Alpaca Markets

- **Subscription**: Free tier works, but data is 15-minute delayed
- **Endpoints Used**:
  - `/v1beta1/screener/stocks/movers` - Top gainers and most active
  - `/v2/stocks/{symbol}/bars` - 1-minute OHLCV bars
  - `/v2/stocks/{symbol}/bars` (daily) - Previous close

### SendGrid

- **Plan**: Free tier (100 emails/day) is sufficient
- **Setup**: Verify sender email and generate API key

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Code Structure

- **Indicators**: Pure functions for technical calculations
- **Scanner**: Data fetching and enrichment
- **Ranker**: Scoring and selection logic
- **Levels**: Setup classification and level computation
- **Emailer**: HTML formatting and SendGrid integration

### Adding a New Provider

1. Create `app/provider_yourprovider.py`
2. Implement the `DataProvider` abstract class
3. Update `get_provider()` factory function
4. Add provider-specific env vars to config

## Troubleshooting

### Email Not Sending

1. Check SendGrid API key is correct
2. Verify sender email is authenticated in SendGrid
3. Check spam folder

### No Picks Generated

1. Market may be slow (low volatility day)
2. Check MIN_PRICE and MIN_VOLUME thresholds
3. Review rejection reasons in email

### Workflow Not Running

1. Check GitHub Actions is enabled
2. Verify secrets are set correctly
3. Check workflow file syntax

### Duplicate Runs

The time gate prevents duplicate runs, but if you see issues:
1. Check `data/history/{date}.json` exists
2. Review workflow run logs

## Disclaimer

This tool is for informational and educational purposes only. It does not constitute investment advice. Trading stocks involves risk, and you may lose money. Always do your own research and consider your risk tolerance before making any trades. The author is not a licensed financial advisor.

## License

MIT License - see LICENSE file for details.

