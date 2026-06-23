"""
TEMPLATE: trigger-latch strategy.
Entry/exit conditions are VECTORIZED boolean columns; a small state loop
only LATCHES the position between entry trigger and exit trigger.
Use when exits are condition-based (EMA cross, regime flip, indicator cross) and do
NOT depend on the entry price. For entry-price exits (stop/target), use
stateful_template.py instead.
"""
from mt_quant_system.core.strategy import BaseStrategy
import talib
import pandas as pd
import numpy as np
from typing import Dict


class TriggerLatchTemplate(BaseStrategy):
    def __init__(self, **kwargs):
        super().__init__("TriggerLatchTemplate", params=kwargs)

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        # --- tunable parameters (overridable via --params JSON) ---
        adx_min = float(self.params.get("adx_min", 20))

        df = data["5m"].copy()  # <-- base timeframe

        close = df["close"].values.astype(float)
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)

        # --- indicators (talib only) ---
        df["ema5"] = talib.EMA(close, timeperiod=5)
        df["ema13"] = talib.EMA(close, timeperiod=13)
        df["adx"] = talib.ADX(high, low, close, timeperiod=14)

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

        # --- ENTRY triggers as vectorized conditions (edit here) ---
        entry_long = (
            (df["ema20_1h"] > df["ema50_1h"]) &
            (df["ema5"] > df["ema13"]) & (df["ema5"].shift(1) <= df["ema13"].shift(1)) &
            (df["adx"] >= adx_min)
        )
        entry_short = (
            (df["ema20_1h"] < df["ema50_1h"]) &
            (df["ema5"] < df["ema13"]) & (df["ema5"].shift(1) >= df["ema13"].shift(1)) &
            (df["adx"] >= adx_min)
        )

        # --- EXIT triggers as vectorized conditions (edit here) ---
        exit_long = df["close"] < df["ema13"]
        exit_short = df["close"] > df["ema13"]

        # --- state machine: latch position between triggers ---
        arr_entry_long = entry_long.fillna(False).values
        arr_entry_short = entry_short.fillna(False).values
        arr_exit_long = exit_long.fillna(False).values
        arr_exit_short = exit_short.fillna(False).values
        days = df["timestamp"].dt.date.values

        signals = np.zeros(len(df))
        current_pos = 0  # 0=Flat, 1=Long, -1=Short

        for i in range(len(df)):
            if i > 0 and days[i] != days[i - 1]:
                current_pos = 0  # intraday: never carry across days

            if current_pos == 0:
                if arr_entry_long[i]:
                    current_pos = 1
                elif arr_entry_short[i]:
                    current_pos = -1
            elif current_pos == 1:
                if arr_exit_long[i]:
                    current_pos = 0
            elif current_pos == -1:
                if arr_exit_short[i]:
                    current_pos = 0

            signals[i] = current_pos

        df["signal"] = signals
        df["signal"] = df["signal"].shift(1).fillna(0)  # MANDATORY — no lookahead
        return df
