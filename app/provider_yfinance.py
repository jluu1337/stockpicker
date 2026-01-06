"""Yahoo Finance data provider implementation using yfinance."""

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests
import yfinance as yf

from app.config import get_settings
from app.market_calendar import get_previous_trading_day
from app.provider_base import DataProvider, Mover, ProviderInfo
from app.time_gate import CHICAGO_TZ

logger = logging.getLogger(__name__)


class YFinanceProvider(DataProvider):
    """
    Yahoo Finance data provider using yfinance library.

    This provider is FREE and requires NO API KEY.

    Features:
    - Historical bars via yfinance
    - Previous close from daily data
    - Movers from Yahoo Finance screener/trending

    Limitations:
    - Data may be 15-20 minutes delayed
    - Rate limits are informal (be respectful)
    - Movers endpoint uses web scraping (may break)
    """

    def __init__(self):
        """Initialize Yahoo Finance provider."""
        self._cache: dict[str, Any] = {}

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        return ProviderInfo(
            name="yfinance",
            data_type="delayed",
            delay_minutes=15,
            api_version="yfinance",
        )

    def get_movers(self, top_n: int = 50) -> list[Mover]:
        """
        Get top movers (gainers + most active).

        Uses Yahoo Finance screener for day gainers and most actives.

        Args:
            top_n: Number of each type to fetch

        Returns:
            Deduplicated list of Mover objects
        """
        movers: list[Mover] = []
        seen_symbols: set[str] = set()

        # Get day gainers
        try:
            gainers = self._get_yahoo_screener("day_gainers", top_n)
            for mover in gainers:
                if mover.symbol not in seen_symbols:
                    seen_symbols.add(mover.symbol)
                    movers.append(mover)
            logger.info(f"Fetched {len(gainers)} gainers from Yahoo Finance")
        except Exception as e:
            logger.warning(f"Failed to get gainers: {e}")

        # Get most actives
        try:
            actives = self._get_yahoo_screener("most_actives", top_n)
            for mover in actives:
                if mover.symbol not in seen_symbols:
                    seen_symbols.add(mover.symbol)
                    movers.append(mover)
            logger.info(f"Fetched {len(actives)} most actives from Yahoo Finance")
        except Exception as e:
            logger.warning(f"Failed to get most actives: {e}")

        # Fallback: if no movers found, use a predefined list
        if not movers:
            logger.warning("No movers from Yahoo screener, using predefined universe")
            movers = self._get_fallback_universe(top_n)

        logger.info(f"Retrieved {len(movers)} unique movers from Yahoo Finance")
        return movers

    def _get_yahoo_screener(self, screener_type: str, top_n: int) -> list[Mover]:
        """
        Get movers from Yahoo Finance screener.

        Args:
            screener_type: "day_gainers" or "most_actives"
            top_n: Number of results

        Returns:
            List of Mover objects
        """
        movers = []

        try:
            # Try yfinance Screener if available (version dependent)
            if hasattr(yf, 'Screener'):
                screener = yf.Screener()
                
                if screener_type == "day_gainers":
                    screener.set_predefined_body("day_gainers")
                elif screener_type == "most_actives":
                    screener.set_predefined_body("most_actives")
                else:
                    return []

                response = screener.response
                quotes = response.get("quotes", [])[:top_n]

                for quote in quotes:
                    symbol = quote.get("symbol", "")
                    if not symbol or "." in symbol:  # Skip non-US symbols
                        continue

                    movers.append(
                        Mover(
                            symbol=symbol,
                            price=float(quote.get("regularMarketPrice", 0) or 0),
                            change_percent=float(quote.get("regularMarketChangePercent", 0) or 0),
                            volume=int(quote.get("regularMarketVolume", 0) or 0),
                            source=screener_type,
                        )
                    )
            else:
                # Screener not available, use web scrape
                raise AttributeError("Screener not available")

        except Exception as e:
            logger.warning(f"yfinance screener failed: {e}, trying web scrape fallback")
            movers = self._scrape_yahoo_movers(screener_type, top_n)

        return movers

    def _scrape_yahoo_movers(self, mover_type: str, top_n: int) -> list[Mover]:
        """
        Fallback: scrape Yahoo Finance movers page, then enrich with live data.

        Args:
            mover_type: "day_gainers" or "most_actives"
            top_n: Number of results

        Returns:
            List of Mover objects
        """
        movers = []
        symbols = []

        url_map = {
            "day_gainers": "https://finance.yahoo.com/gainers",
            "most_actives": "https://finance.yahoo.com/most-active",
        }

        url = url_map.get(mover_type)
        if not url:
            return []

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            # Try to parse tables from HTML
            from io import StringIO
            tables = pd.read_html(StringIO(response.text))
            if tables:
                df = tables[0].head(top_n)

                # Get symbols from the table
                for _, row in df.iterrows():
                    symbol = str(row.get("Symbol", ""))
                    if not symbol or symbol == "nan" or "." in symbol:
                        continue
                    symbols.append(symbol)

        except Exception as e:
            logger.warning(f"Failed to scrape Yahoo movers page: {e}")
            return []

        # Now fetch live data for these symbols using yfinance
        if symbols:
            try:
                tickers = yf.Tickers(" ".join(symbols[:top_n]))
                
                for symbol in symbols[:top_n]:
                    try:
                        ticker = tickers.tickers.get(symbol)
                        if ticker:
                            info = ticker.fast_info
                            last_price = info.last_price or 0
                            prev_close = info.previous_close or last_price
                            pct_change = ((last_price - prev_close) / prev_close * 100) if prev_close else 0
                            
                            movers.append(
                                Mover(
                                    symbol=symbol,
                                    price=float(last_price),
                                    change_percent=float(pct_change),
                                    volume=int(info.last_volume or 0),
                                    source=mover_type,
                                )
                            )
                    except Exception as e:
                        logger.debug(f"Failed to get data for {symbol}: {e}")
                        continue
                        
            except Exception as e:
                logger.warning(f"Failed to fetch ticker data: {e}")

        return movers

    def _parse_volume(self, vol_str: str) -> int:
        """Parse volume string like '1.5M' or '500K'."""
        vol_str = vol_str.upper().replace(",", "")
        multiplier = 1

        if "M" in vol_str:
            multiplier = 1_000_000
            vol_str = vol_str.replace("M", "")
        elif "K" in vol_str:
            multiplier = 1_000
            vol_str = vol_str.replace("K", "")
        elif "B" in vol_str:
            multiplier = 1_000_000_000
            vol_str = vol_str.replace("B", "")

        try:
            return int(float(vol_str) * multiplier)
        except:
            return 0

    def _get_fallback_universe(self, top_n: int) -> list[Mover]:
        """
        Get movers from a predefined universe as fallback.

        Uses popular/liquid stocks when screeners fail.
        """
        # Popular liquid stocks to check
        universe = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
            "NFLX", "INTC", "PYPL", "SQ", "SHOP", "ROKU", "COIN", "PLTR",
            "SOFI", "RIVN", "LCID", "NIO", "BABA", "JD", "PDD", "SNAP",
            "UBER", "LYFT", "DASH", "ABNB", "RBLX", "DKNG", "PENN", "MGM",
            "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "ARKK",
        ]

        movers = []
        tickers = yf.Tickers(" ".join(universe[:top_n]))

        for symbol in universe[:top_n]:
            try:
                ticker = tickers.tickers.get(symbol)
                if ticker:
                    info = ticker.fast_info
                    movers.append(
                        Mover(
                            symbol=symbol,
                            price=float(info.last_price or 0),
                            change_percent=float(
                                ((info.last_price or 0) - (info.previous_close or 0))
                                / (info.previous_close or 1)
                                * 100
                            ),
                            volume=int(info.last_volume or 0),
                            source="universe",
                        )
                    )
            except Exception as e:
                logger.debug(f"Failed to get {symbol}: {e}")
                continue

        return movers

    def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1Min",
    ) -> pd.DataFrame:
        """
        Get OHLCV bars for a symbol.

        Args:
            symbol: Stock ticker symbol
            start: Start datetime
            end: End datetime
            timeframe: Bar timeframe (default: "1Min")

        Returns:
            DataFrame with OHLCV columns
        """
        # Map timeframe to yfinance interval
        interval_map = {
            "1Min": "1m",
            "2Min": "2m",
            "5Min": "5m",
            "15Min": "15m",
            "30Min": "30m",
            "1Hour": "1h",
            "1Day": "1d",
        }
        interval = interval_map.get(timeframe, "1m")

        try:
            ticker = yf.Ticker(symbol)

            # yfinance requires specific date formats
            # For intraday data, it only keeps 7 days of 1m data
            df = ticker.history(
                start=start,
                end=end,
                interval=interval,
                prepost=False,  # Regular session only
            )

            if df.empty:
                return pd.DataFrame()

            # Rename columns to lowercase
            df.columns = df.columns.str.lower()

            # Ensure we have required columns
            required_cols = ["open", "high", "low", "close", "volume"]
            for col in required_cols:
                if col not in df.columns:
                    return pd.DataFrame()

            # Select only needed columns
            df = df[["open", "high", "low", "close", "volume"]]

            # yfinance doesn't provide VWAP, add placeholder
            df["vwap"] = None

            return df

        except Exception as e:
            logger.warning(f"Failed to get bars for {symbol}: {e}")
            return pd.DataFrame()

    def get_bars_batch(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        timeframe: str = "1Min",
    ) -> dict[str, pd.DataFrame]:
        """
        Get bars for multiple symbols.

        Args:
            symbols: List of stock ticker symbols
            start: Start datetime
            end: End datetime
            timeframe: Bar timeframe

        Returns:
            Dict mapping symbol to DataFrame
        """
        interval_map = {
            "1Min": "1m",
            "2Min": "2m",
            "5Min": "5m",
            "15Min": "15m",
            "30Min": "30m",
            "1Hour": "1h",
            "1Day": "1d",
        }
        interval = interval_map.get(timeframe, "1m")

        results = {}

        try:
            # yfinance can download multiple tickers at once
            df = yf.download(
                tickers=symbols,
                start=start,
                end=end,
                interval=interval,
                group_by="ticker",
                prepost=False,
                progress=False,
                threads=True,
            )

            if df.empty:
                logger.warning("Batch download returned empty DataFrame")
                return results

            # Parse multi-ticker dataframe
            for symbol in symbols:
                try:
                    if len(symbols) == 1:
                        symbol_df = df.copy()
                    else:
                        # Multi-ticker returns multi-level columns
                        if symbol not in df.columns.get_level_values(0):
                            continue
                        symbol_df = df[symbol].copy()

                    # Check if we have data
                    if symbol_df.empty:
                        continue
                    
                    # Drop rows where ALL values are NaN
                    symbol_df = symbol_df.dropna(how='all')
                    if symbol_df.empty:
                        continue

                    # Lowercase column names
                    symbol_df.columns = symbol_df.columns.str.lower()
                    
                    # Select only needed columns
                    cols = ["open", "high", "low", "close", "volume"]
                    available_cols = [c for c in cols if c in symbol_df.columns]
                    if len(available_cols) < 5:
                        continue
                        
                    symbol_df = symbol_df[available_cols].copy()
                    symbol_df["vwap"] = None
                    
                    # Drop any remaining NaN rows
                    symbol_df = symbol_df.dropna(subset=["close"])

                    if not symbol_df.empty:
                        results[symbol] = symbol_df

                except Exception as e:
                    logger.debug(f"Failed to parse {symbol}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Batch download failed: {e}, falling back to individual")
            return super().get_bars_batch(symbols, start, end, timeframe)

        logger.info(f"Batch download got bars for {len(results)}/{len(symbols)} symbols")
        return results

    def get_previous_close(self, symbol: str) -> float | None:
        """
        Get previous day's closing price.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Previous close price, or None if unavailable
        """
        # Check cache
        if symbol in self._cache:
            return self._cache[symbol].get("prev_close")

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info

            prev_close = info.previous_close
            if prev_close:
                self._cache[symbol] = {"prev_close": float(prev_close)}
                return float(prev_close)

            return None

        except Exception as e:
            logger.warning(f"Failed to get previous close for {symbol}: {e}")
            return None

    def get_previous_closes_batch(self, symbols: list[str]) -> dict[str, float]:
        """
        Get previous close for multiple symbols.

        Args:
            symbols: List of stock ticker symbols

        Returns:
            Dict mapping symbol to previous close price
        """
        results = {}

        # Filter out cached
        uncached = [s for s in symbols if s not in self._cache]

        if uncached:
            try:
                tickers = yf.Tickers(" ".join(uncached))

                for symbol in uncached:
                    try:
                        ticker = tickers.tickers.get(symbol)
                        if ticker:
                            prev_close = ticker.fast_info.previous_close
                            if prev_close:
                                self._cache[symbol] = {"prev_close": float(prev_close)}
                    except Exception as e:
                        logger.debug(f"Failed to get prev close for {symbol}: {e}")

            except Exception as e:
                logger.warning(f"Batch previous close failed: {e}")

        # Build results from cache
        for symbol in symbols:
            if symbol in self._cache:
                close = self._cache[symbol].get("prev_close")
                if close is not None:
                    results[symbol] = close

        return results

    def get_metadata(self, symbol: str) -> dict[str, Any]:
        """
        Get metadata for a symbol including float and market cap.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Metadata dict with type, float, market cap, etc.
        """
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            quote_type = info.get("quoteType", "").upper()
            is_etf = quote_type == "ETF"
            
            # Get float and market cap for filtering
            shares_float = info.get("floatShares")
            market_cap = info.get("marketCap")

            return {
                "type_unknown": False,
                "is_etf": is_etf,
                "is_otc": False,  # yfinance doesn't easily identify OTC
                "name": info.get("shortName", ""),
                "sector": info.get("sector", ""),
                "avg_volume_20d": info.get("averageVolume", None),
                "shares_float": int(shares_float) if shares_float else None,
                "market_cap": int(market_cap) if market_cap else None,
            }

        except Exception as e:
            logger.debug(f"Could not get metadata for {symbol}: {e}")
            return {"type_unknown": True}


def get_provider() -> DataProvider:
    """Factory function to get the configured data provider."""
    settings = get_settings()

    if settings.provider_name == "yfinance":
        return YFinanceProvider()
    elif settings.provider_name == "alpaca":
        from app.provider_alpaca import AlpacaProvider
        return AlpacaProvider()

    # Default to yfinance (no API key needed)
    return YFinanceProvider()

