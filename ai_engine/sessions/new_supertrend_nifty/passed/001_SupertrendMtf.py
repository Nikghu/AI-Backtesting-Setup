from mt_quant_system.core.strategy import BaseStrategy
import pandas_ta as ta
import pandas as pd
from typing import Dict


class SupertrendMtf(BaseStrategy):
    """
    Supertrend trend-following with a higher-timeframe filter (NIFTY intraday).

    Supertrend gives a clean trend direction (+1 up / -1 down). The sample data
    has no bar-level edge but higher-TF trends align, so we only take a side
    when the 5m and 15m Supertrend agree, and go flat when they disagree.

    Long  : 5m Supertrend up   AND 15m Supertrend up.
    Short : 5m Supertrend down AND 15m Supertrend down.
    Flat  : the two timeframes disagree.
    """

    def __init__(self, period=10, multiplier=3.0, **kwargs):
        super().__init__("SupertrendMtf", params=kwargs)
        self.period = period
        self.multiplier = multiplier

    def _st_dir(self, frame: pd.DataFrame) -> pd.Series:
        st = ta.supertrend(frame['high'], frame['low'], frame['close'],
                           length=self.period, multiplier=self.multiplier)
        dir_col = [c for c in st.columns if c.startswith('SUPERTd')][0]
        return st[dir_col]

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        df = data['5m'].copy()
        df['st_dir'] = self._st_dir(df)

        # Higher-TF (15m) Supertrend filter, merged onto 5m without lookahead
        if '15m' in data:
            htf = data['15m'].copy()
            htf['htf_st_dir'] = self._st_dir(htf)
            df = pd.merge_asof(
                df.sort_values('timestamp'),
                htf[['timestamp', 'htf_st_dir']].sort_values('timestamp'),
                on='timestamp',
                direction='backward',
            )
        else:
            df['htf_st_dir'] = df['st_dir']

        long_ok = (df['st_dir'] == 1) & (df['htf_st_dir'] == 1)
        short_ok = (df['st_dir'] == -1) & (df['htf_st_dir'] == -1)

        df['signal'] = 0
        df.loc[long_ok, 'signal'] = 1
        df.loc[short_ok, 'signal'] = -1

        # Base decisions on completed candles only (avoid lookahead bias)
        df['signal'] = df['signal'].shift(1)

        return df
