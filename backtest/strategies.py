"""内置策略：双均线与 RSI。

约定：策略函数返回**目标仓位**信号序列（1 = 满仓，0 = 空仓），
索引与价格序列一致，由 BacktestEngine 按信号变化日的收盘价成交。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def dual_ma_signals(prices: pd.Series, fast: int = 5, slow: int = 20) -> pd.Series:
    """双均线策略：快线上穿慢线时持仓，下穿时清仓。

    Args:
        prices: 收盘价序列。
        fast: 快线周期。
        slow: 慢线周期。

    Raises:
        ValueError: 快线周期不小于慢线周期时。
    """
    if fast >= slow:
        raise ValueError(f"快线周期({fast})必须小于慢线周期({slow})")

    ma_fast = prices.rolling(fast).mean()
    ma_slow = prices.rolling(slow).mean()

    signal = pd.Series(0, index=prices.index, dtype=int)
    valid = ma_fast.notna() & ma_slow.notna()
    signal[valid & (ma_fast > ma_slow)] = 1
    return signal


def rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Wilder 平滑的 RSI 指标。"""
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100).where(avg_loss.notna(), np.nan)


def rsi_signals(
    prices: pd.Series,
    period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
) -> pd.Series:
    """RSI 超买超卖策略（带状态机的持仓规则）：

    - RSI 下穿超卖线 → 建仓
    - RSI 上穿超买线 → 清仓
    - 其余时间维持当前仓位

    Args:
        prices: 收盘价序列。
        period: RSI 周期。
        oversold: 超卖阈值。
        overbought: 超买阈值。

    Raises:
        ValueError: 超卖阈值不小于超买阈值时。
    """
    if oversold >= overbought:
        raise ValueError(f"超卖阈值({oversold})必须小于超买阈值({overbought})")

    values = rsi(prices, period)
    signal = pd.Series(0, index=prices.index, dtype=int)

    holding = 0
    for date, value in values.items():
        if pd.isna(value):
            signal.loc[date] = 0
            continue
        if holding == 0 and value < oversold:
            holding = 1
        elif holding == 1 and value > overbought:
            holding = 0
        signal.loc[date] = holding
    return signal


STRATEGIES = {
    "dual_ma": dual_ma_signals,
    "rsi": rsi_signals,
}
