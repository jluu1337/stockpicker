"""Configuration management using pydantic-settings."""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Alpaca API settings (optional - only needed if using Alpaca provider)
    apca_api_key_id: str = Field(default="", description="Alpaca API Key ID")
    apca_api_secret_key: str = Field(default="", description="Alpaca API Secret Key")
    apca_base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        description="Alpaca API base URL (paper or live)",
    )
    apca_data_url: str = Field(
        default="https://data.alpaca.markets",
        description="Alpaca Data API URL",
    )

    # SendGrid settings
    sendgrid_api_key: str = Field(..., description="SendGrid API Key")
    from_email: str = Field(..., description="Sender email address")
    to_email: str = Field(..., description="Recipient email address")

    # Scanner settings
    min_price: float = Field(default=5.0, description="Minimum stock price filter")
    min_volume: int = Field(
        default=1_000_000, description="Minimum volume so far filter"
    )
    top_n_seed: int = Field(
        default=100, description="Number of candidates to seed from movers"
    )
    picks: int = Field(default=5, description="Number of top picks to include (3-5)")

    # Time gate settings
    execution_window_minutes: int = Field(
        default=2,
        description="Minutes tolerance around 8:40 CT for execution window",
    )
    target_hour: int = Field(default=8, description="Target hour CT for execution")
    target_minute: int = Field(default=40, description="Target minute for execution")

    # Email behavior
    send_market_closed_email: bool = Field(
        default=False,
        description="Whether to send email when market is closed",
    )

    # Provider settings
    provider_name: str = Field(
        default="yfinance",
        description="Data provider name (yfinance or alpaca)",
    )
    data_delay_type: Optional[str] = Field(
        default=None,
        description="Data delay type (realtime, delayed, or None if unknown)",
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

