"""Abstract base class for data providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass
class Mover:
    """Represents a stock mover (gainer or most active)."""

    symbol: str
    price: float
    change_percent: float
    volume: int
    source: str  # "gainers" or "most_active"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderInfo:
    """Information about the data provider."""

    name: str
    data_type: str  # "realtime", "delayed", "unknown"
    delay_minutes: int | None = None
    api_version: str | None = None


class DataProvider(ABC):
    """
    Abstract base class for market data providers.

    Implementations must provide:
    - get_movers: Top gainers and most active stocks
    - get_bars: 1-minute OHLCV bars for a symbol
    - get_previous_close: Previous day's closing price
    - get_metadata: Optional metadata (ETF, OTC, etc.)

    Graceful Degradation:
    - If avg_volume_20d is unavailable, return None in metadata
    - If ETF/OTC detection is unavailable, return type_unknown=True
    - Log warnings but don't fail on non-critical data
    """

    @property
    @abstractmethod
    def info(self) -> ProviderInfo:
        """Get provider information."""
        pass

    @abstractmethod
    def get_movers(self, top_n: int = 50) -> list[Mover]:
        """
        Get top movers (gainers + most active).

        Args:
            top_n: Number of each type to fetch (returns up to 2*top_n total)

        Returns:
            List of Mover objects, deduplicated by symbol
        """
        pass

    @abstractmethod
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
            start: Start datetime (inclusive)
            end: End datetime (inclusive)
            timeframe: Bar timeframe (default: "1Min")

        Returns:
            DataFrame with columns: open, high, low, close, volume, vwap (if available)
            Index should be datetime
        """
        pass

    @abstractmethod
    def get_previous_close(self, symbol: str) -> float | None:
        """
        Get previous day's closing price.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Previous close price, or None if unavailable
        """
        pass

    def get_metadata(self, symbol: str) -> dict[str, Any]:
        """
        Get optional metadata for a symbol.

        Default implementation returns empty dict with type_unknown flag.
        Override in subclass if provider supports metadata.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Dict with optional keys:
            - is_etf: bool
            - is_otc: bool
            - type_unknown: bool (True if we can't determine type)
            - avg_volume_20d: float (average daily volume, or None)
            - market_cap: float (or None)
        """
        return {"type_unknown": True}

    def get_bars_batch(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        timeframe: str = "1Min",
    ) -> dict[str, pd.DataFrame]:
        """
        Get bars for multiple symbols (batch request if supported).

        Default implementation calls get_bars for each symbol.
        Override in subclass if provider supports batch requests.

        Args:
            symbols: List of stock ticker symbols
            start: Start datetime
            end: End datetime
            timeframe: Bar timeframe

        Returns:
            Dict mapping symbol to DataFrame
        """
        results = {}
        for symbol in symbols:
            try:
                bars = self.get_bars(symbol, start, end, timeframe)
                if not bars.empty:
                    results[symbol] = bars
            except Exception:
                # Graceful degradation - skip failed symbols
                continue
        return results

    def get_previous_closes_batch(self, symbols: list[str]) -> dict[str, float]:
        """
        Get previous close for multiple symbols (batch request if supported).

        Default implementation calls get_previous_close for each symbol.
        Override in subclass if provider supports batch requests.

        Args:
            symbols: List of stock ticker symbols

        Returns:
            Dict mapping symbol to previous close price
        """
        results = {}
        for symbol in symbols:
            try:
                close = self.get_previous_close(symbol)
                if close is not None:
                    results[symbol] = close
            except Exception:
                continue
        return results

