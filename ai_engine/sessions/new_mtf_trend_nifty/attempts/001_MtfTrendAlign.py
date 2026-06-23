from mt_quant_system.core.strategy import BaseStrategy
import pandas_ta as ta
import pandas as pd
from typing import Dict


class MtfTrendAlign(BaseStrategy):
    """
    Multi-timeframe EMA trend-alignment (NIFTY intraday).

    Idea: the data shows no bar-level momentum (ac1 ~ 0) but higher-TF trends
    do align, so only trade when 5m and 15m agree, and sit out chop.

    Long  : 5m EMA fast > slow AND 15m close > 15m EMA.
    Short : 5m EMA fast < slow AND 15m close < 15m EMA.
    Flat  : timeframes disagree (avoids choppy periods).
    """

    def __init__(self, fast=9, slow=21, htf_ema=20, **kwargs):
        super().__init__("MtfTrendAlign", params=kwargs)
        self.fast = fast
        self.slow = slow
        self.htf_ema = htf_ema

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        df = data['5m'].copy()

        df['ema_fast'] = ta.ema(df['close'], length=self.fast)
        df['ema_slow'] = ta.ema(df['close'], length=self.slow)

        # Higher-TF (15m) trend filter, merged onto 5m without lookahead
        if '15m' in data:
            htf = data['15m'].copy()
            htf['htf_ema'] = ta.ema(htf['close'], length=self.htf_ema)
            htf['htf_up'] = htf['close'] > htf['htf_ema']
            df = pd.merge_asof(
                df.sort_values('timestamp'),
                htf[['timestamp', 'htf_up']].sort_values('timestamp'),
                on='timestamp',
                direction='backward',
            )
        else:
            df['htf_up'] = True

        long_ok = (df['ema_fast'] > df['ema_slow']) & (df['htf_up'])
        short_ok = (df['ema_fast'] < df['ema_slow']) & (~df['htf_up'])

        df['signal'] = 0
        df.loc[long_ok, 'signal'] = 1
        df.loc[short_ok, 'signal'] = -1

        # Base decisions on completed candles only (avoid lookahead bias)
        df['signal'] = df['signal'].shift(1)

        return df
