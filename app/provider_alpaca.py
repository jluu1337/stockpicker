"""Alpaca Markets data provider implementation."""

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestQuoteRequest,
    StockSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient

from app.config import get_settings
from app.market_calendar import get_previous_trading_day
from app.provider_base import DataProvider, Mover, ProviderInfo
from app.time_gate import CHICAGO_TZ

logger = logging.getLogger(__name__)


class AlpacaProvider(DataProvider):
    """
    Alpaca Markets data provider.

    Uses Alpaca's official Python SDK (alpaca-py) for:
    - Screener API for top movers (gainers + most active)
    - Historical bars for 1-minute OHLCV data
    - Snapshots for previous close

    Note: Movers API requires a paid subscription for real-time data.
    Free tier gets 15-minute delayed data.
    """

    def __init__(self):
        """Initialize Alpaca clients."""
        settings = get_settings()

        # Data client for historical bars and quotes
        self.data_client = StockHistoricalDataClient(
            api_key=settings.apca_api_key_id,
            secret_key=settings.apca_api_secret_key,
        )

        # Trading client for account info (and can be used for screener)
        self.trading_client = TradingClient(
            api_key=settings.apca_api_key_id,
            secret_key=settings.apca_api_secret_key,
        )

        # Determine data type based on subscription
        self._data_type = settings.data_delay_type or "unknown"

        # Cache for snapshots
        self._snapshot_cache: dict[str, dict] = {}

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        return ProviderInfo(
            name="alpaca",
            data_type=self._data_type,
            delay_minutes=15 if self._data_type == "delayed" else None,
            api_version="v2",
        )

    def get_movers(self, top_n: int = 50) -> list[Mover]:
        """
        Get top movers (gainers + most active).

        Uses Alpaca's screener API endpoint.

        Args:
            top_n: Number of each type to fetch

        Returns:
            Deduplicated list of Mover objects
        """
        movers: list[Mover] = []
        seen_symbols: set[str] = set()

        try:
            # Get top gainers using the screener endpoint
            gainers = self._get_screener_movers("gainers", top_n)
            for mover in gainers:
                if mover.symbol not in seen_symbols:
                    seen_symbols.add(mover.symbol)
                    movers.append(mover)

        except Exception as e:
            logger.warning(f"Failed to get gainers: {e}")

        try:
            # Get most active using the screener endpoint
            active = self._get_screener_movers("most_active", top_n)
            for mover in active:
                if mover.symbol not in seen_symbols:
                    seen_symbols.add(mover.symbol)
                    movers.append(mover)

        except Exception as e:
            logger.warning(f"Failed to get most active: {e}")

        logger.info(f"Retrieved {len(movers)} unique movers from Alpaca")
        return movers

    def _get_screener_movers(self, mover_type: str, top_n: int) -> list[Mover]:
        """
        Get movers from Alpaca screener API.

        Args:
            mover_type: "gainers" or "most_active"
            top_n: Number of results

        Returns:
            List of Mover objects
        """
        import requests

        settings = get_settings()

        # Alpaca screener endpoint
        url = f"https://data.alpaca.markets/v1beta1/screener/stocks/movers"
        headers = {
            "APCA-API-KEY-ID": settings.apca_api_key_id,
            "APCA-API-SECRET-KEY": settings.apca_api_secret_key,
        }
        params = {"top": top_n}

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        movers = []

        # Parse gainers
        if mover_type == "gainers" and "gainers" in data:
            for item in data["gainers"][:top_n]:
                movers.append(
                    Mover(
                        symbol=item.get("symbol", ""),
                        price=float(item.get("price", 0)),
                        change_percent=float(item.get("percent_change", 0)),
                        volume=int(item.get("volume", 0)),
                        source="gainers",
                    )
                )

        # Parse most active (losers can also be active, so we combine)
        if mover_type == "most_active":
            # Most active are typically the highest volume
            # Alpaca returns gainers and losers, combine for volume
            all_movers = data.get("gainers", []) + data.get("losers", [])
            # Sort by volume descending
            all_movers.sort(key=lambda x: x.get("volume", 0), reverse=True)
            for item in all_movers[:top_n]:
                movers.append(
                    Mover(
                        symbol=item.get("symbol", ""),
                        price=float(item.get("price", 0)),
                        change_percent=float(item.get("percent_change", 0)),
                        volume=int(item.get("volume", 0)),
                        source="most_active",
                    )
                )

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
        # Map timeframe string to Alpaca TimeFrame
        tf_map = {
            "1Min": TimeFrame.Minute,
            "5Min": TimeFrame(5, "Min"),
            "15Min": TimeFrame(15, "Min"),
            "1Hour": TimeFrame.Hour,
            "1Day": TimeFrame.Day,
        }
        tf = tf_map.get(timeframe, TimeFrame.Minute)

        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start,
                end=end,
            )

            bars = self.data_client.get_stock_bars(request)

            # Convert to DataFrame
            if symbol in bars.data and bars.data[symbol]:
                bar_list = bars.data[symbol]
                df = pd.DataFrame(
                    [
                        {
                            "timestamp": b.timestamp,
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": b.volume,
                            "vwap": b.vwap if hasattr(b, "vwap") else None,
                        }
                        for b in bar_list
                    ]
                )
                df.set_index("timestamp", inplace=True)
                df.index = pd.to_datetime(df.index, utc=True)
                return df

            return pd.DataFrame()

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
        Get bars for multiple symbols in a single request.

        Args:
            symbols: List of stock ticker symbols
            start: Start datetime
            end: End datetime
            timeframe: Bar timeframe

        Returns:
            Dict mapping symbol to DataFrame
        """
        tf_map = {
            "1Min": TimeFrame.Minute,
            "5Min": TimeFrame(5, "Min"),
            "15Min": TimeFrame(15, "Min"),
            "1Hour": TimeFrame.Hour,
            "1Day": TimeFrame.Day,
        }
        tf = tf_map.get(timeframe, TimeFrame.Minute)

        results = {}

        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=tf,
                start=start,
                end=end,
            )

            bars = self.data_client.get_stock_bars(request)

            for symbol in symbols:
                if symbol in bars.data and bars.data[symbol]:
                    bar_list = bars.data[symbol]
                    df = pd.DataFrame(
                        [
                            {
                                "timestamp": b.timestamp,
                                "open": b.open,
                                "high": b.high,
                                "low": b.low,
                                "close": b.close,
                                "volume": b.volume,
                                "vwap": b.vwap if hasattr(b, "vwap") else None,
                            }
                            for b in bar_list
                        ]
                    )
                    df.set_index("timestamp", inplace=True)
                    df.index = pd.to_datetime(df.index, utc=True)
                    results[symbol] = df

        except Exception as e:
            logger.warning(f"Failed batch bar request: {e}")
            # Fall back to individual requests
            return super().get_bars_batch(symbols, start, end, timeframe)

        return results

    def get_previous_close(self, symbol: str) -> float | None:
        """
        Get previous day's closing price.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Previous close price, or None if unavailable
        """
        # Check cache first
        if symbol in self._snapshot_cache:
            return self._snapshot_cache[symbol].get("prev_close")

        try:
            # Get previous trading day
            prev_day = get_previous_trading_day()

            # Request daily bar for previous day
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=datetime.combine(prev_day, datetime.min.time()),
                end=datetime.combine(prev_day, datetime.max.time()),
            )

            bars = self.data_client.get_stock_bars(request)

            if symbol in bars.data and bars.data[symbol]:
                close = bars.data[symbol][-1].close
                self._snapshot_cache[symbol] = {"prev_close": close}
                return close

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

        # Filter out cached symbols
        uncached = [s for s in symbols if s not in self._snapshot_cache]

        if uncached:
            try:
                prev_day = get_previous_trading_day()

                request = StockBarsRequest(
                    symbol_or_symbols=uncached,
                    timeframe=TimeFrame.Day,
                    start=datetime.combine(prev_day, datetime.min.time()),
                    end=datetime.combine(prev_day, datetime.max.time()),
                )

                bars = self.data_client.get_stock_bars(request)

                for symbol in uncached:
                    if symbol in bars.data and bars.data[symbol]:
                        close = bars.data[symbol][-1].close
                        self._snapshot_cache[symbol] = {"prev_close": close}

            except Exception as e:
                logger.warning(f"Failed batch previous close request: {e}")

        # Build results from cache
        for symbol in symbols:
            if symbol in self._snapshot_cache:
                close = self._snapshot_cache[symbol].get("prev_close")
                if close is not None:
                    results[symbol] = close

        return results

    def get_metadata(self, symbol: str) -> dict[str, Any]:
        """
        Get metadata for a symbol.

        Note: Alpaca's free tier doesn't provide detailed asset metadata
        like ETF classification. We mark as type_unknown.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Metadata dict
        """
        try:
            # Try to get asset info from trading client
            asset = self.trading_client.get_asset(symbol)

            return {
                "type_unknown": False,
                "is_etf": asset.asset_class == "us_equity"
                and getattr(asset, "easy_to_borrow", True),
                "is_otc": not asset.tradable,
                "exchange": asset.exchange.value if asset.exchange else None,
                "name": asset.name,
            }
        except Exception as e:
            logger.debug(f"Could not get metadata for {symbol}: {e}")
            return {"type_unknown": True}


def get_provider() -> DataProvider:
    """Factory function to get the configured data provider."""
    settings = get_settings()

    if settings.provider_name == "alpaca":
        return AlpacaProvider()

    raise ValueError(f"Unknown provider: {settings.provider_name}")

