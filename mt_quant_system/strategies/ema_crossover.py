from mt_quant_system.core.strategy import BaseStrategy
import pandas_ta as ta
import pandas as pd
from typing import Dict


class EmaCrossover(BaseStrategy):
    """
    Simple EMA crossover demo strategy.

    Long  when the fast EMA is above the slow EMA.
    Short when the fast EMA is below the slow EMA.

    Meant as a minimal, runnable example to verify the setup works.
    """

    def __init__(self, fast=9, slow=21, **kwargs):
        super().__init__("EmaCrossover", params=kwargs)
        self.fast = fast
        self.slow = slow

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        # Use 5m as the base timeframe (fall back to whatever is available)
        if '5m' in data:
            df = data['5m'].copy()
        else:
            df = data[list(data.keys())[0]].copy()

        df['ema_fast'] = ta.ema(df['close'], length=self.fast)
        df['ema_slow'] = ta.ema(df['close'], length=self.slow)

        df['signal'] = 0
        df.loc[df['ema_fast'] > df['ema_slow'], 'signal'] = 1
        df.loc[df['ema_fast'] < df['ema_slow'], 'signal'] = -1

        # Base decisions on completed candles only (avoid lookahead bias)
        df['signal'] = df['signal'].shift(1)

        return df
