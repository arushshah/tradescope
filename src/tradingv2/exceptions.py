class TradingV2Error(Exception):
    """Base exception for TradingV2."""


class ConfigError(TradingV2Error):
    """Raised when a backtest config is invalid."""


class DataError(TradingV2Error):
    """Raised when market data cannot be fetched or validated."""


class NoDataError(DataError):
    """Raised when a provider returns no rows for a symbol/date range."""


class StrategyError(TradingV2Error):
    """Raised when a strategy cannot be loaded or returns invalid output."""
