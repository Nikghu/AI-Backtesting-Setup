"""
AI Backtest Runner — CLI tool used by the /ai-backtest Claude Code workflow.

Loads a strategy .py file, runs the full backtest pipeline from mt_quant_system,
and prints metrics as a single JSON line between markers so it is easy to parse.

Usage:
    python -m ai_engine.run_backtest --strategy-file path/to/strategy.py
    python -m ai_engine.run_backtest --strategy-file s.py --class-name MyStrategy
    python -m ai_engine.run_backtest --strategy-file s.py --report --outdir ai_engine/sessions/x/passed

Output (stdout):
    ===BACKTEST_RESULT===
    {"success": true, "metrics": {...}, ...}
    ===END_RESULT===
"""
import sys
import io
import json
import argparse
import importlib.util
import inspect
import traceback
from pathlib import Path
from datetime import time as dt_time
from typing import Dict, Any

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mt_quant_system.core.data_loader import DataLoader
from mt_quant_system.core.signal_generator import SignalGenerator
from mt_quant_system.core.strategy import BaseStrategy
from mt_quant_system.core.exporter import MtQuantExporter
from mt_quant_system.core.report_generator import (
    build_trades_from_events,
    calculate_trade_metrics,
    calculate_advanced_metrics,
    generate_backtest_report,
)

import pandas as pd

_TF_ORDER = {"1m": 1, "3m": 2, "5m": 3, "15m": 4, "30m": 5, "60m": 6, "1h": 7, "1d": 8}


def _tf_sort_key(tf: str) -> int:
    return _TF_ORDER.get(tf, 99)


def emit(result: Dict[str, Any]) -> None:
    print("===BACKTEST_RESULT===")
    print(json.dumps(result, default=str))
    print("===END_RESULT===")


def fail(error: str) -> None:
    emit({"success": False, "error": error, "metrics": {}})
    sys.exit(1)


def resolve_data_file(arg: str) -> str:
    if arg:
        return arg
    files = sorted((PROJECT_ROOT / "data").glob("*.feather"))
    if not files:
        fail("No .feather files found in data/ folder")
    return str(files[0])


def load_strategy_class(strategy_file: str, class_name: str = None):
    path = Path(strategy_file).resolve()
    if not path.exists():
        fail(f"Strategy file not found: {path}")
    spec = importlib.util.spec_from_file_location(f"ai_strategy_{path.stem}", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if class_name:
        cls = getattr(module, class_name, None)
        if cls is None:
            fail(f"Class '{class_name}' not found in {path.name}")
        return cls

    # Auto-detect: first BaseStrategy subclass defined in this module
    candidates = [
        obj for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, BaseStrategy) and obj is not BaseStrategy
        and obj.__module__ == module.__name__
    ]
    if not candidates:
        fail(f"No BaseStrategy subclass found in {path.name}")
    return candidates[0]


def probe(data_file: str) -> Dict[str, Any]:
    data = DataLoader(data_file).load_data()
    symbols = sorted({k[0] for k in data.keys()})
    timeframes = sorted({k[1] for k in data.keys()}, key=_tf_sort_key)
    all_ts = []
    for df in data.values():
        if not df.empty:
            all_ts.extend([df["timestamp"].min(), df["timestamp"].max()])
    return {
        "success": True,
        "data_file": data_file,
        "symbols": symbols,
        "timeframes": timeframes,
        "date_range": f"{min(all_ts).date()} to {max(all_ts).date()}" if all_ts else "unknown",
    }


def run(args) -> Dict[str, Any]:
    strategy_class = load_strategy_class(args.strategy_file, args.class_name)
    strategy_name = strategy_class.__name__

    data = DataLoader(args.data).load_data()
    all_ts = []
    for _df in data.values():
        if not _df.empty:
            all_ts.extend([_df["timestamp"].min(), _df["timestamp"].max()])
    date_range = f"{min(all_ts).date()} to {max(all_ts).date()}" if all_ts else "unknown"
    symbols = sorted({k[0] for k in data.keys()})
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(",")}
        symbols = [s for s in symbols if s.upper() in wanted]
        if not symbols:
            fail(f"None of the requested symbols found. Available: {sorted({k[0] for k in data.keys()})}")
    all_tfs = sorted({k[1] for k in data.keys()}, key=_tf_sort_key)

    start_time = stop_time = None
    if args.intraday:
        h, m = map(int, args.start_time.split(":"))
        start_time = dt_time(h, m)
        h, m = map(int, args.stop_time.split(":"))
        stop_time = dt_time(h, m)

    params = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as e:
            fail(f"--params is not valid JSON: {e}")

    try:
        strategy = strategy_class(**params)
    except Exception as e:
        fail(f"Strategy init error: {e}")

    all_processed = []
    per_symbol = {}
    outdir = Path(args.outdir)
    if args.report:
        outdir.mkdir(parents=True, exist_ok=True)
    timestamp_str = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

    # For intraday reports, embed start/stop time in the filename (matches
    # mt_quant_system naming, e.g. _091600_152000).
    file_suffix = ""
    if args.intraday and start_time and stop_time:
        file_suffix = f"_{str(start_time).replace(':', '')}_{str(stop_time).replace(':', '')}"

    for symbol in symbols:
        tf_data = {tf: data[(sym, tf)] for (sym, tf) in data.keys() if sym == symbol}
        if not tf_data:
            continue

        try:
            df_signals = strategy.generate_signals(tf_data)
        except Exception as e:
            fail(f"generate_signals error ({symbol}): {e}\n{traceback.format_exc(limit=3)}")

        if "signal" not in df_signals.columns:
            fail("Strategy output missing 'signal' column")
        if "timestamp" not in df_signals.columns:
            df_signals = df_signals.reset_index()
        if "timestamp" not in df_signals.columns:
            fail("No timestamp column in strategy output")

        events = SignalGenerator.generate_trade_events(
            df_signals, args.intraday, start_time, stop_time
        )
        if not events:
            per_symbol[symbol] = {"total_trades": 0}
            continue

        events_df = pd.DataFrame(events)
        trades = build_trades_from_events(events_df)
        if not trades:
            per_symbol[symbol] = {"total_trades": 0}
            continue

        # Finest available TF for trade pricing
        ohlc_data = None
        for tf in all_tfs:
            if (symbol, tf) in data:
                ohlc_data = data[(symbol, tf)].copy()
                if not isinstance(ohlc_data.index, pd.DatetimeIndex):
                    ohlc_data = ohlc_data.set_index("timestamp")
                ohlc_data = ohlc_data.sort_index()
                break
        if ohlc_data is None:
            continue

        # Lot size: explicit --lot-size overrides; otherwise per-symbol default.
        lot_size = args.lot_size if args.lot_size is not None else {"NIFTY": 65, "BANKNIFTY": 35}.get(symbol, 75)

        open_col = "open" if "open" in ohlc_data.columns else "Open"
        processed, _ = calculate_trade_metrics(
            trades, ohlc_data, open_col, args.instrument, lot_size
        )
        all_processed.extend(processed)

        wins = sum(1 for t in processed if t["PnL"] > 0)
        per_symbol[symbol] = {
            "total_trades": len(processed),
            "win_rate_pct": round(wins / len(processed) * 100, 2) if processed else 0.0,
            "total_pnl": round(sum(t["PnL"] for t in processed), 2),
        }

        if args.report:
            base = outdir / f"signals_{strategy_name}_{symbol}{file_suffix}_{timestamp_str}"
            MtQuantExporter.export_csv(events, str(base) + ".csv")
            generate_backtest_report(
                events, tf_data, str(base) + ".html",
                args.capital, args.instrument, lot_size,
                args.analysis_tf, args.analysis_lookback, args.losing_analysis,
            )
            per_symbol[symbol]["csv"] = str(base) + ".csv"
            per_symbol[symbol]["html"] = str(base) + ".html"

    if not all_processed:
        return {
            "success": True,
            "strategy": strategy_name,
            "date_range": date_range,
            "error": None,
            "metrics": {
                "total_trades": 0, "win_rate_pct": 0.0, "trades_per_year": 0.0,
                "avg_pnl": 0.0, "total_pnl": 0.0, "highest_mdd": 0.0,
                "sharpe_ratio": 0.0, "winning_trades": 0, "losing_trades": 0,
                "daily_win_rate_pct": 0.0, "trading_days": 0, "positive_days": 0,
                "max_dd_days": 0,
            },
            "per_symbol": per_symbol,
        }

    advanced, _, _ = calculate_advanced_metrics(all_processed, args.capital)
    total = len(all_processed)
    winning = sum(1 for t in all_processed if t["PnL"] > 0)
    total_pnl = sum(t["PnL"] for t in all_processed)

    entry_times = [t["Entry Date/Time"] for t in all_processed]
    span_days = (max(entry_times) - min(entry_times)).days if len(entry_times) > 1 else 365
    years = max(span_days / 365.25, 0.1)

    daily_pnl: Dict[Any, float] = {}
    for t in all_processed:
        d = pd.Timestamp(t["Entry Date/Time"]).date()
        daily_pnl[d] = daily_pnl.get(d, 0.0) + t["PnL"]
    trading_days = len(daily_pnl)
    positive_days = sum(1 for v in daily_pnl.values() if v > 0)

    # Longest underwater stretch: calendar days the daily-PnL equity curve
    # stays below its previous peak (includes an unrecovered tail).
    max_dd_days = 0
    equity = peak = 0.0
    peak_date = None
    for d in sorted(daily_pnl):
        if peak_date is None:
            peak_date = d
        equity += daily_pnl[d]
        if equity >= peak:
            peak = equity
            peak_date = d
        else:
            max_dd_days = max(max_dd_days, (d - peak_date).days)

    return {
        "success": True,
        "strategy": strategy_name,
        "params": params,
        "date_range": date_range,
        "error": None,
        "metrics": {
            "total_trades": total,
            "win_rate_pct": round(winning / total * 100, 2),
            "trades_per_year": round(total / years, 1),
            "avg_pnl": round(total_pnl / total, 2),
            "total_pnl": round(total_pnl, 2),
            "highest_mdd": round(advanced.get("Highest MDD", 0), 2),
            "sharpe_ratio": round(advanced.get("Sharpe Ratio", 0), 2),
            "winning_trades": winning,
            "losing_trades": total - winning,
            "daily_win_rate_pct": round(positive_days / trading_days * 100, 2) if trading_days else 0.0,
            "trading_days": trading_days,
            "positive_days": positive_days,
            "max_dd_days": max_dd_days,
        },
        "per_symbol": per_symbol,
    }


def main():
    parser = argparse.ArgumentParser(description="AI Backtest Runner")
    parser.add_argument("--strategy-file", help="Path to strategy .py file")
    parser.add_argument("--class-name", default=None, help="Strategy class name (auto-detected if omitted)")
    parser.add_argument("--data", default=None, help="Path to .feather data file (auto-picked from data/ if omitted)")
    parser.add_argument("--probe", action="store_true", help="Only print data file info (symbols, timeframes, date range)")
    parser.add_argument("--symbols", default=None, help="Comma-separated symbol filter, e.g. NIFTY or NIFTY,BANKNIFTY")
    parser.add_argument("--params", default=None, help='JSON kwargs passed to the strategy, e.g. \'{"stop_atr": 1.0}\'')
    parser.add_argument("--intraday", action="store_true", default=True)
    parser.add_argument("--no-intraday", dest="intraday", action="store_false")
    parser.add_argument("--start-time", default="09:16")
    parser.add_argument("--stop-time", default="15:15")
    parser.add_argument("--instrument", default="Future", choices=["Spot", "Future"])
    parser.add_argument("--lot-size", type=int, default=None,
                        help="Lot size; if unset, defaults per symbol (NIFTY=65, BANKNIFTY=35, else 75)")
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument("--report", action="store_true", help="Also export CSV + HTML report")
    parser.add_argument("--outdir", default="output", help="Folder for CSV/HTML when --report is set")
    parser.add_argument("--analysis-tf", default="3m")
    parser.add_argument("--analysis-lookback", type=int, default=10)
    parser.add_argument("--losing-analysis", action="store_true")
    args = parser.parse_args()

    args.data = resolve_data_file(args.data)

    try:
        if args.probe:
            emit(probe(args.data))
            return
        if not args.strategy_file:
            fail("--strategy-file is required (or use --probe)")
        emit(run(args))
    except SystemExit:
        raise
    except Exception as e:
        fail(f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}")


if __name__ == "__main__":
    main()
