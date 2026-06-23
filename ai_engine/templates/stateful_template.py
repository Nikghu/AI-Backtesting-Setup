"""
TEMPLATE: stateful strategy (bar-by-bar state machine).
Use when exits depend on the ENTRY price: profit target, ATR stop,
timeout, first-profitable-close.

Tunable knobs read from self.params -> sweep them without editing the file:
    python -m ai_engine.run_backtest --strategy-file s.py --params '{"stop_atr": 1.0}'
"""
from mt_quant_system.core.strategy import BaseStrategy
import talib
import pandas as pd
import numpy as np
from typing import Dict


class StatefulTemplate(BaseStrategy):
    def __init__(self, **kwargs):
        super().__init__("StatefulTemplate", params=kwargs)

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        # --- tunable parameters (overridable via --params JSON) ---
        stop_atr = float(self.params.get("stop_atr", 1.5))
        max_bars = int(self.params.get("max_bars", 12))
        adx_min = float(self.params.get("adx_min", 20))
        last_entry_minute = int(self.params.get("last_entry_minute", 14 * 60 + 30))

        df = data["5m"].copy()  # <-- base timeframe

        close = df["close"].values.astype(float)
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)

        df["ema20"] = talib.EMA(close, timeperiod=20)
        df["atr"] = talib.ATR(high, low, close, timeperiod=14)

        if "1h" in data:
            df1h = data["1h"].copy()
            c1h = df1h["close"].values.astype(float)
            h1h = df1h["high"].values.astype(float)
            l1h = df1h["low"].values.astype(float)
            df1h["ema20_1h"] = talib.EMA(c1h, timeperiod=20)
            df1h["ema50_1h"] = talib.EMA(c1h, timeperiod=50)
            df1h["adx_1h"] = talib.ADX(h1h, l1h, c1h, timeperiod=14)
            df = pd.merge_asof(
                df.sort_values("timestamp"),
                df1h[["timestamp", "ema20_1h", "ema50_1h", "adx_1h"]].sort_values("timestamp"),
                on="timestamp", direction="backward",
            )

        ema20 = df["ema20"].values
        atr = df["atr"].values
        adx = df["adx_1h"].values
        up_regime = (df["ema20_1h"] > df["ema50_1h"]).values & (adx >= adx_min)
        dn_regime = (df["ema20_1h"] < df["ema50_1h"]).values & (adx >= adx_min)
        close = df["close"].values.astype(float)
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        open_ = df["open"].values.astype(float)
        days = df["timestamp"].dt.date.values
        minutes = (df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute).values

        n = len(df)
        signal = np.zeros(n, dtype=np.int8)
        state = 0           # 0 flat, 1 long, -1 short
        entry_close = 0.0
        stop = 0.0
        bars_held = 0

        for i in range(1, n):
            if days[i] != days[i - 1]:
                state = 0  # never carry state across days (intraday)

            if state == 0:
                if not np.isfinite(ema20[i]) or not np.isfinite(atr[i]) or not np.isfinite(adx[i]):
                    signal[i] = 0
                    continue
                if minutes[i] > last_entry_minute:
                    signal[i] = 0
                    continue
                # --- ENTRY conditions (edit here) ---
                if up_regime[i] and low[i] <= ema20[i] and close[i] > ema20[i] and close[i] > open_[i]:
                    state = 1
                    entry_close = close[i]
                    stop = close[i] - stop_atr * atr[i]
                    bars_held = 0
                elif dn_regime[i] and high[i] >= ema20[i] and close[i] < ema20[i] and close[i] < open_[i]:
                    state = -1
                    entry_close = close[i]
                    stop = close[i] + stop_atr * atr[i]
                    bars_held = 0
            elif state == 1:
                bars_held += 1
                # --- EXIT conditions long (edit here) ---
                if close[i] > entry_close or close[i] < stop or bars_held >= max_bars or not up_regime[i]:
                    state = 0
            elif state == -1:
                bars_held += 1
                # --- EXIT conditions short (edit here) ---
                if close[i] < entry_close or close[i] > stop or bars_held >= max_bars or not dn_regime[i]:
                    state = 0

            signal[i] = state

        df["signal"] = signal
        df["signal"] = df["signal"].shift(1)  # MANDATORY — no lookahead
        return df
