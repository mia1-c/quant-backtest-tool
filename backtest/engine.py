"""轻量级回测引擎：逐日模拟信号与成交，支持手续费与全额进出。

设计目标：
- 只依赖 NumPy / Pandas，无第三方回测框架，逻辑完全可控、可读、可改；
- 单标的、仅做多、全额进出，便于研究者快速验证策略假设；
- 输出净值曲线与完整绩效指标，支持收益 / 风险 / 稳定性 / 成本多维诊断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass
class Trade:
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None

    @property
    def closed(self) -> bool:
        return self.exit_price is not None

    @property
    def ret(self) -> float:
        if not self.closed:
            return 0.0
        return self.exit_price / self.entry_price - 1


@dataclass
class BacktestResult:
    equity: pd.Series                    # 策略净值（已归一化到 1.0）
    benchmark: pd.Series                 # 买入持有基准净值
    positions: pd.Series                 # 每日持仓（0/1）
    trades: List[Trade] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    monthly_returns: Optional[pd.Series] = None
    drawdown: Optional[pd.Series] = None

    def summary(self) -> str:
        m = self.metrics
        lines = [
            "=" * 52,
            "  回测绩效摘要",
            "=" * 52,
            f"  累计收益      {m['total_return']:>9.2%}",
            f"  年化收益      {m['annual_return']:>9.2%}",
            f"  基准（买入持有）{m['benchmark_return']:>9.2%}",
            f"  年化波动率    {m['annual_volatility']:>9.2%}",
            f"  最大回撤      {m['max_drawdown']:>9.2%}",
            f"  夏普比率      {m['sharpe']:>9.2f}",
            f"  卡玛比率      {m['calmar']:>9.2f}",
            f"  胜率          {m['win_rate']:>9.2%}",
            f"  盈亏比        {m['profit_loss_ratio']:>9.2f}",
            f"  交易次数      {int(m['num_trades']):>9d}",
            "-" * 52,
        ]
        return "\n".join(lines)


class BacktestEngine:
    """逐日回测引擎。

    Args:
        fee_rate: 单边手续费率（如 0.0003 表示万三）。
        initial_cash: 初始资金。
    """

    def __init__(self, fee_rate: float = 0.0003, initial_cash: float = 100_000.0):
        self.fee_rate = fee_rate
        self.initial_cash = initial_cash

    def run(self, prices: pd.Series, signals: pd.Series) -> BacktestResult:
        """执行回测。

        Args:
            prices: 收盘价序列，索引为日期。
            signals: 目标仓位信号，取值 1（满仓）/ 0（空仓）；
                     引擎在信号变化日的收盘价成交。

        Returns:
            BacktestResult
        """
        prices = prices.astype(float)
        signals = signals.reindex(prices.index).fillna(0).astype(int).clip(0, 1)

        cash = self.initial_cash
        shares = 0.0
        equity_vals: List[float] = []
        position_vals: List[int] = []
        trades: List[Trade] = []
        open_trade: Optional[Trade] = None

        for date, price in prices.items():
            target = int(signals.loc[date])
            held = 1 if shares > 0 else 0

            if target == 1 and held == 0 and price > 0:
                qty = int(cash // (price * (1 + self.fee_rate)))
                if qty > 0:
                    cash -= qty * price * (1 + self.fee_rate)
                    shares = float(qty)
                    open_trade = Trade(entry_date=date, entry_price=float(price))

            elif target == 0 and held == 1:
                cash += shares * price * (1 - self.fee_rate)
                if open_trade is not None:
                    open_trade.exit_date = date
                    open_trade.exit_price = float(price)
                    trades.append(open_trade)
                    open_trade = None
                shares = 0.0

            equity_vals.append(cash + shares * float(price))
            position_vals.append(1 if shares > 0 else 0)

        equity = pd.Series(equity_vals, index=prices.index) / self.initial_cash
        benchmark = prices / prices.iloc[0]
        positions = pd.Series(position_vals, index=prices.index)

        result = BacktestResult(equity=equity, benchmark=benchmark, positions=positions, trades=trades)
        result.drawdown = equity / equity.cummax() - 1
        # 用 to_period 聚合，避免不同 pandas 版本 resample 别名差异
        monthly = equity.groupby(equity.index.to_period("M")).last()
        result.monthly_returns = monthly.pct_change().dropna()
        result.metrics = compute_metrics(equity, benchmark, trades, result.drawdown, positions)
        return result


def compute_metrics(
    equity: pd.Series,
    benchmark: pd.Series,
    trades: Sequence[Trade],
    drawdown: pd.Series,
    positions: Optional[pd.Series] = None,
) -> Dict[str, float]:
    """计算收益 / 风险 / 稳定性 / 成本四类指标。"""
    n = len(equity)
    total_return = float(equity.iloc[-1] - 1)
    years = n / TRADING_DAYS if n else 0
    annual_return = float((1 + total_return) ** (1 / years) - 1) if years > 0 and total_return > -1 else 0.0

    daily_ret = equity.pct_change().dropna()
    ann_vol = float(daily_ret.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(daily_ret) > 1 else 0.0
    sharpe = float(daily_ret.mean() / daily_ret.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(daily_ret) > 1 and daily_ret.std(ddof=1) > 0 else 0.0

    max_dd = float(drawdown.min()) if len(drawdown) else 0.0
    calmar = float(annual_return / abs(max_dd)) if max_dd < 0 else 0.0

    closed = [t for t in trades if t.closed]
    wins = [t for t in closed if t.ret > 0]
    losses = [t for t in closed if t.ret <= 0]
    win_rate = len(wins) / len(closed) if closed else 0.0
    avg_win = float(np.mean([t.ret for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([t.ret for t in losses])) if losses else 0.0
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "benchmark_return": float(benchmark.iloc[-1] - 1),
        "annual_volatility": ann_vol,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "calmar": calmar,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_loss_ratio": pl_ratio,
        "num_trades": float(len(closed)),
        "exposure": float(positions.mean()) if positions is not None and len(positions) else 0.0,
    }


def trades_to_frame(trades: Sequence[Trade]) -> pd.DataFrame:
    """把交易明细转为 DataFrame，便于导出 CSV 做进一步分析。"""
    rows = []
    for t in trades:
        if not t.closed:
            continue
        rows.append(
            {
                "入场日期": t.entry_date.date(),
                "出场日期": t.exit_date.date(),
                "入场价": round(t.entry_price, 3),
                "出场价": round(t.exit_price, 3),
                "收益率": round(t.ret, 4),
                "持仓天数": (t.exit_date - t.entry_date).days,
            }
        )
    return pd.DataFrame(rows)
