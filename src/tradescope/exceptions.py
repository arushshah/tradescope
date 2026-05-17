class TradeScopeError(Exception):
    """Base exception for TradeScope."""


class ConfigError(TradeScopeError):
    """Raised when a backtest config is invalid."""


class DataError(TradeScopeError):
    """Raised when market data cannot be fetched or validated."""


class NoDataError(DataError):
    """Raised when a provider returns no rows for a symbol/date range."""


class StrategyError(TradeScopeError):
    """Raised when a strategy cannot be loaded or returns invalid output."""
