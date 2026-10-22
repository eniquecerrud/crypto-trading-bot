"""Application errors raised for the operator to read."""


class CryptobotError(Exception):
    """Base class for expected cryptobot failures."""


class ConfigError(CryptobotError):
    """The configuration file is missing a field or contains an invalid value."""


class DataError(CryptobotError):
    """OHLCV data is missing, malformed, or inconsistent."""


class StrategyError(CryptobotError):
    """A strategy name or parameter is not valid."""


class LiveTradingDisabled(CryptobotError):
    """Live trading was requested without every required opt-in."""
