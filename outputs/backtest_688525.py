import csv
import math
from collections import OrderedDict
from pathlib import Path

INPUT = Path(r"C:\Users\hp\Documents\Codex\2026-07-08\bang\outputs\688525-baiwei-storage-20240101-20260713-close.csv")
OUT_SUMMARY = Path(r"C:\Users\hp\Documents\Codex\2026-07-08\bang\outputs\688525-backtest-summary.csv")
OUT_MONTHLY = Path(r"C:\Users\hp\Documents\Codex\2026-07-08\bang\outputs\688525-backtest-monthly.csv")

INITIAL_CASH = 100_000
MAX_POSITION = 0.80
FEE = 0.0005
SLIPPAGE = 0.0003
STOP_LOSS = 0.12


def load_prices():
    rows = []
    with INPUT.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append({"date": row["date"], "close": float(row["close"])})
    return rows


def sma(values, period):
    out = [None] * len(values)
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= period:
            total -= values[i - period]
        if i >= period - 1:
            out[i] = total / period
    return out


def rsi(values, period):
    out = [None] * len(values)
    gain = 0.0
    loss = 0.0
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        up = max(diff, 0)
        down = max(-diff, 0)
        if i <= period:
            gain += up
            loss += down
            if i == period:
                out[i] = 100 - 100 / (1 + gain / max(loss, 1e-9))
        else:
            gain = (gain * (period - 1) + up) / period
            loss = (loss * (period - 1) + down) / period
            out[i] = 100 - 100 / (1 + gain / max(loss, 1e-9))
    return out


def rolling_high(values, period):
    return [None if i < period else max(values[i - period:i]) for i in range(len(values))]


def rolling_low(values, period):
    return [None if i < period else min(values[i - period:i]) for i in range(len(values))]


def annualized_return(start, end, days):
    years = days / 252
    return end / start ** 1 - 1 if years <= 0 else (end / start) ** (1 / years) - 1


def signal(i, closes, cfg, ind, in_market):
    prev = i - 1
    if cfg["type"] == "ma":
        fast = ind["fast"][prev]
        slow = ind["slow"][prev]
        return in_market if fast is None or slow is None else fast > slow
    if cfg["type"] == "rsi":
        value = ind["rsi"][prev]
        if value is None:
            return in_market
        if not in_market and value <= cfg["rsi_buy"]:
            return True
        if in_market and value >= cfg["rsi_sell"]:
            return False
        return in_market
    high = ind["high"][prev]
    low = ind["low"][prev]
    if high is None or low is None:
        return in_market
    if not in_market and closes[prev] >= high:
        return True
    if in_market and closes[prev] <= low:
        return False
    return in_market


def backtest(rows, cfg):
    closes = [r["close"] for r in rows]
    ind = {
        "fast": sma(closes, cfg.get("fast", 20)),
        "slow": sma(closes, cfg.get("slow", 60)),
        "rsi": rsi(closes, cfg.get("rsi_period", 14)),
        "high": rolling_high(closes, cfg.get("breakout_high", 55)),
        "low": rolling_low(closes, cfg.get("breakout_low", 20)),
    }
    cash = INITIAL_CASH
    shares = 0
    entry = 0.0
    in_market = False
    equity = []
    trades = []

    for i in range(1, len(rows)):
        date = rows[i]["date"]
        close = closes[i]
        desired = signal(i, closes, cfg, ind, in_market)
        if in_market and STOP_LOSS > 0 and close <= entry * (1 - STOP_LOSS):
            desired = False

        if not in_market and desired:
            buy_price = close * (1 + SLIPPAGE)
            budget = (cash + shares * close) * MAX_POSITION
            shares_to_buy = math.floor(budget / buy_price)
            cost = shares_to_buy * buy_price * (1 + FEE)
            if shares_to_buy > 0 and cost <= cash:
                shares = shares_to_buy
                cash -= cost
                entry = buy_price
                in_market = True
                trades.append({"date": date, "action": "buy", "price": buy_price, "shares": shares, "pnl": 0.0})
        elif in_market and not desired:
            sell_price = close * (1 - SLIPPAGE)
            proceeds = shares * sell_price * (1 - FEE)
            pnl = proceeds - shares * entry
            cash += proceeds
            trades.append({"date": date, "action": "sell", "price": sell_price, "shares": shares, "pnl": pnl})
            shares = 0
            entry = 0.0
            in_market = False

        prev_equity = equity[-1]["equity"] if equity else INITIAL_CASH
        now_equity = cash + shares * close
        equity.append({"date": date, "equity": now_equity, "return": now_equity / prev_equity - 1})

    return summarize(rows, equity, trades, cfg)


def monthly_returns(equity):
    buckets = OrderedDict()
    for row in equity:
        month = row["date"][:7]
        if month not in buckets:
            buckets[month] = {"first": row["equity"], "last": row["equity"]}
        buckets[month]["last"] = row["equity"]
    return [{"month": k, "return": v["last"] / v["first"] - 1, "end": v["last"]} for k, v in buckets.items()]


def summarize(rows, equity, trades, cfg):
    start = INITIAL_CASH
    end = equity[-1]["equity"]
    peak = start
    max_dd = 0.0
    for row in equity:
        peak = max(peak, row["equity"])
        max_dd = min(max_dd, row["equity"] / peak - 1)
    daily = [r["return"] for r in equity[1:]]
    avg = sum(daily) / max(len(daily), 1)
    var = sum((x - avg) ** 2 for x in daily) / max(len(daily) - 1, 1)
    sharpe = math.sqrt(252) * avg / math.sqrt(max(var, 1e-12))
    closed = [t for t in trades if t["action"] == "sell"]
    wins = [t for t in closed if t["pnl"] > 0]
    months = monthly_returns(equity)
    positive_months = [m for m in months if m["return"] > 0]
    return {
        "name": cfg["name"],
        "final_equity": end,
        "total_return": end / start - 1,
        "annual_return": annualized_return(start, end, len(equity)),
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "trade_count": len(closed),
        "win_rate": len(wins) / len(closed) if closed else 0,
        "positive_month_rate": len(positive_months) / len(months) if months else 0,
        "best_month": max((m["return"] for m in months), default=0),
        "worst_month": min((m["return"] for m in months), default=0),
        "months": months,
        "trades": trades,
    }


def buy_and_hold(rows):
    start_price = rows[0]["close"]
    shares = math.floor(INITIAL_CASH * MAX_POSITION / (start_price * (1 + SLIPPAGE)))
    cash = INITIAL_CASH - shares * start_price * (1 + SLIPPAGE) * (1 + FEE)
    equity = []
    for row in rows[1:]:
        current = cash + shares * row["close"]
        prev = equity[-1]["equity"] if equity else INITIAL_CASH
        equity.append({"date": row["date"], "equity": current, "return": current / prev - 1})
    result = summarize(rows, equity, [], {"name": "买入持有80%仓位"})
    result["trade_count"] = 1
    result["win_rate"] = 1.0 if result["total_return"] > 0 else 0.0
    return result


def pct(x):
    return f"{x * 100:.2f}%"


def main():
    rows = load_prices()
    configs = [
        {"name": "买入持有80%仓位", "type": "hold"},
        {"name": "双均线 20/60", "type": "ma", "fast": 20, "slow": 60},
        {"name": "双均线 10/30", "type": "ma", "fast": 10, "slow": 30},
        {"name": "RSI 14 买30卖65", "type": "rsi", "rsi_period": 14, "rsi_buy": 30, "rsi_sell": 65},
        {"name": "通道突破 55/20", "type": "breakout", "breakout_high": 55, "breakout_low": 20},
        {"name": "通道突破 20/10", "type": "breakout", "breakout_high": 20, "breakout_low": 10},
    ]
    results = []
    for cfg in configs:
        results.append(buy_and_hold(rows) if cfg["type"] == "hold" else backtest(rows, cfg))

    fields = [
        "name", "final_equity", "total_return", "annual_return", "max_drawdown",
        "sharpe", "trade_count", "win_rate", "positive_month_rate",
        "best_month", "worst_month"
    ]
    with OUT_SUMMARY.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in results:
            writer.writerow({k: r[k] for k in fields})

    best = max(results, key=lambda r: (r["total_return"], r["max_drawdown"]))
    with OUT_MONTHLY.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["strategy", "month", "return", "end"])
        writer.writeheader()
        for m in best["months"]:
            writer.writerow({"strategy": best["name"], **m})

    print(f"data: {rows[0]['date']} to {rows[-1]['date']}, {len(rows)} rows")
    print("summary_csv:", OUT_SUMMARY)
    print("monthly_csv:", OUT_MONTHLY)
    print()
    for r in sorted(results, key=lambda x: x["total_return"], reverse=True):
        print(
            f"{r['name']}: final={r['final_equity']:.0f}, total={pct(r['total_return'])}, "
            f"annual={pct(r['annual_return'])}, max_dd={pct(r['max_drawdown'])}, "
            f"sharpe={r['sharpe']:.2f}, trades={r['trade_count']}, "
            f"win={pct(r['win_rate'])}, pos_month={pct(r['positive_month_rate'])}"
        )


if __name__ == "__main__":
    main()
