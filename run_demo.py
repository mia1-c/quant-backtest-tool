#!/usr/bin/env python3
"""回测示例：读取 CSV（或生成示例行情）→ 运行策略 → 输出图表与指标。

用法：
    # 用内置示例行情（1072 个交易日，2020-01 ~ 2024-02）
    python run_demo.py

    # 用你自己的数据（CSV 需包含 date,close 两列）
    python run_demo.py --csv data/688525.csv --strategy dual_ma --fast 5 --slow 20

    # 生成图表
    python run_demo.py --chart outputs/equity.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest import BacktestEngine, dual_ma_signals, rsi_signals, trades_to_frame


def generate_sample_prices(n: int = 1072, seed: int = 20200102) -> pd.Series:
    """生成确定性示例日线行情（几何随机游走 + 波动率状态切换）。

    没有真实数据时用来自检引擎与可视化，保证示例可复现。
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-02", periods=n)

    price = 40.0
    prices = []
    for i in range(n):
        regime = 1.0 if (i // 120) % 2 == 0 else -0.6
        drift = 0.00035 * regime
        vol = 0.012 + (i % 37) / 37 * 0.010
        price = max(3.0, price * (1 + drift + rng.normal(0, vol)))
        prices.append(round(price, 2))

    return pd.Series(prices, index=dates, name="close")


def load_csv(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    date_col = cols.get("date") or cols.get("日期") or df.columns[0]
    close_col = cols.get("close") or cols.get("收盘") or df.columns[-1]

    s = pd.Series(
        pd.to_numeric(df[close_col], errors="coerce").values,
        index=pd.to_datetime(df[date_col]),
        name="close",
    ).dropna().sort_index()
    if len(s) < 60:
        raise SystemExit(f"数据量不足：仅 {len(s)} 条，至少需要 60 条")
    return s


def save_chart(prices: pd.Series, result, out_path: Path) -> None:
    """输出净值曲线 + 回撤曲线。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("未安装 matplotlib，跳过图表输出（pip install matplotlib）")
        return

    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC", "DejaVu Sans",
    ]
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]}
    )

    ax1.plot(result.equity.index, result.equity, label="策略净值", color="#6d28d9", lw=1.6)
    ax1.plot(result.benchmark.index, result.benchmark, label="买入持有", color="#94a3b8", lw=1.2, ls="--")
    ax1.axhline(1.0, color="#cbd5e1", lw=0.8)
    ax1.set_ylabel("净值")
    ax1.legend(loc="upper left", frameon=False)
    ax1.grid(alpha=0.25)

    ax2.fill_between(result.drawdown.index, result.drawdown * 100, 0, color="#137333", alpha=0.25)
    ax2.plot(result.drawdown.index, result.drawdown * 100, color="#137333", lw=1.0)
    ax2.set_ylabel("回撤 (%)")
    ax2.grid(alpha=0.25)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    print(f"图表已保存：{out_path}")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="量化策略回测与研究工具")
    p.add_argument("--csv", type=Path, help="CSV 数据文件（含 date,close 两列）")
    p.add_argument("--strategy", choices=["dual_ma", "rsi"], default="dual_ma")
    p.add_argument("--fast", type=int, default=5, help="双均线快线周期")
    p.add_argument("--slow", type=int, default=20, help="双均线慢线周期")
    p.add_argument("--rsi-period", type=int, default=14)
    p.add_argument("--rsi-oversold", type=float, default=30.0)
    p.add_argument("--rsi-overbought", type=float, default=70.0)
    p.add_argument("--cash", type=float, default=100_000.0)
    p.add_argument("--fee", type=float, default=0.0003, help="单边费率，默认万三")
    p.add_argument("--chart", type=Path, help="图表输出路径，如 outputs/equity.png")
    p.add_argument("--trades-out", type=Path, help="交易明细导出路径（CSV）")
    p.add_argument("--seed", type=int, default=20200102, help="示例行情随机种子")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    prices = load_csv(args.csv) if args.csv else generate_sample_prices(seed=args.seed)
    print(f"数据区间：{prices.index[0].date()} ~ {prices.index[-1].date()}  "
          f"共 {len(prices)} 个交易日\n")

    if args.strategy == "dual_ma":
        signals = dual_ma_signals(prices, fast=args.fast, slow=args.slow)
        label = f"双均线 (fast={args.fast}, slow={args.slow})"
    else:
        signals = rsi_signals(
            prices,
            period=args.rsi_period,
            oversold=args.rsi_oversold,
            overbought=args.rsi_overbought,
        )
        label = f"RSI (period={args.rsi_period}, {args.rsi_oversold}/{args.rsi_overbought})"

    engine = BacktestEngine(fee_rate=args.fee, initial_cash=args.cash)
    result = engine.run(prices, signals)

    print(f"策略：{label}\n")
    print(result.summary())

    if result.monthly_returns is not None and len(result.monthly_returns):
        pos = result.monthly_returns[result.monthly_returns > 0]
        neg = result.monthly_returns[result.monthly_returns <= 0]
        print(f"  月度胜率      {len(pos) / len(result.monthly_returns):>9.1%}"
              f"  （上涨 {len(pos)} 月 / 下跌 {len(neg)} 月）")
        print(f"  最好月份      {result.monthly_returns.max():>9.2%}")
        print(f"  最差月份      {result.monthly_returns.min():>9.2%}")
        print("=" * 52)

    if args.trades_out:
        df = trades_to_frame(result.trades)
        args.trades_out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.trades_out, index=False, encoding="utf-8-sig")
        print(f"交易明细已保存：{args.trades_out}（{len(df)} 笔）")

    if args.chart:
        save_chart(prices, result, args.chart)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
