"""轻量级量化策略回测引擎。"""

from .engine import BacktestEngine, BacktestResult, Trade, compute_metrics, trades_to_frame
from .strategies import STRATEGIES, dual_ma_signals, rsi, rsi_signals

__version__ = "0.1.0"

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "Trade",
    "compute_metrics",
    "trades_to_frame",
    "STRATEGIES",
    "dual_ma_signals",
    "rsi",
    "rsi_signals",
]
