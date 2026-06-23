"""
TEMPLATE: simple vectorized strategy (entry/exit as column conditions).
Use when exits are condition-based (opposite signal, indicator cross).
Copy, rename the class, and edit the marked sections.
"""
from mt_quant_system.core.strategy import BaseStrategy
import talib
import pandas as pd
import numpy as np
from typing import Dict


class VectorizedTemplate(BaseStrategy):
    def __init__(self, **kwargs):
        super().__init__("VectorizedTemplate", params=kwargs)

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        df = data["5m"].copy()  # <-- base timeframe

        close = df["close"].values.astype(float)
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)

        # --- indicators (talib only; pandas_ta is NOT installed) ---
        df["ema20"] = talib.EMA(close, timeperiod=20)
        df["rsi"] = talib.RSI(close, timeperiod=14)

        # --- higher-TF regime via merge_asof (backward = no lookahead) ---
        if "1h" in data:
            df1h = data["1h"].copy()
            c1h = df1h["close"].values.astype(float)
            df1h["ema20_1h"] = talib.EMA(c1h, timeperiod=20)
            df1h["ema50_1h"] = talib.EMA(c1h, timeperiod=50)
            df = pd.merge_asof(
                df.sort_values("timestamp"),
                df1h[["timestamp", "ema20_1h", "ema50_1h"]].sort_values("timestamp"),
                on="timestamp", direction="backward",
            )

        # --- signal: 1 = Long, -1 = Short, 0 = Flat ---
        df["signal"] = 0
        long_cond = (df["ema20_1h"] > df["ema50_1h"]) & (df["close"] > df["ema20"]) & (df["rsi"] > 50)
        short_cond = (df["ema20_1h"] < df["ema50_1h"]) & (df["close"] < df["ema20"]) & (df["rsi"] < 50)
        df.loc[long_cond, "signal"] = 1
        df.loc[short_cond, "signal"] = -1

        df["signal"] = df["signal"].shift(1)  # MANDATORY — no lookahead
        return df
