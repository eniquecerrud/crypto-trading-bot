"""Built-in strategies and the registry used by the CLI."""

from cryptobot.strategies.bollinger import BollingerBreakout, BollingerReversion
from cryptobot.strategies.crossover import EmaCrossover, SmaCrossover
from cryptobot.strategies.registry import available_strategies, create_strategy
from cryptobot.strategies.rsi import RsiMeanReversion

__all__ = [
    "BollingerBreakout",
    "BollingerReversion",
    "EmaCrossover",
    "RsiMeanReversion",
    "SmaCrossover",
    "available_strategies",
    "create_strategy",
]
