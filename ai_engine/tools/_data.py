"""Shared data-loading helpers for ai_engine analysis tools."""
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mt_quant_system.core.data_loader import DataLoader


def resolve_data_file(arg=None):
    if arg:
        return arg
    files = sorted((PROJECT_ROOT / "data").glob("*.feather"))
    if not files:
        sys.exit("No .feather files found in data/")
    return str(files[0])


def load_symbol(symbol, data_path=None):
    """Returns Dict[tf, DataFrame] for one symbol, each sorted by timestamp."""
    data = DataLoader(resolve_data_file(data_path)).load_data()
    out = {tf: d.sort_values("timestamp").reset_index(drop=True)
           for (sym, tf), d in data.items() if sym == symbol}
    if not out:
        sys.exit(f"Symbol {symbol} not found. Available: {sorted({k[0] for k in data})}")
    return out


def daily_ohlc(df, session_end="15:30"):
    """Builds one OHLC row per day from intraday bars (regular session only)."""
    d = df[df["timestamp"].dt.strftime("%H:%M") <= session_end].copy()
    d["date"] = d["timestamp"].dt.date
    g = d.groupby("date")
    out = pd.DataFrame({
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
    })
    out["range"] = out["high"] - out["low"]
    out["net"] = out["close"] - out["open"]
    return out
