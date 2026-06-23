from mt_quant_system.core.strategy import BaseStrategy
import pandas_ta as ta
import pandas as pd
from typing import Dict


class DIR_UP_MultiCheck(BaseStrategy):
    """
    Lower timeframe strategy.
    1.  3m Above 200 SMA
    2.  If ADX is lower than 20 there is chance of ranging market

    
    Defaults to '1m' timeframe.
    """
    
    def __init__(self, period=10, multiplier=3.0):
        super().__init__("SupertrendStrategy_1m_10_3")
        self.period = period
        self.multiplier = multiplier

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        # Select Timeframe
        if '1m' in data:
            df = data['1m'].copy()
        else:
            # Fallback
            tf = list(data.keys())[0]
            df = data[tf].copy()
        
        # Calculate Supertrend
        st_df = ta.supertrend(df['high'], df['low'], df['close'], 
                                           length=self.period, 
                                           multiplier=self.multiplier)
        
        if st_df is None:
             return df
        
        # Identify Direction Column
        dir_col = f"SUPERTd_{self.period}_{self.multiplier}"
        if dir_col not in st_df.columns:
            possible_cols = [c for c in st_df.columns if c.startswith('SUPERTd')]
            if possible_cols:
                dir_col = possible_cols[0]
            else:
                # Fallback if pandas_ta behaves oddly
                return df 

        df['st_dir'] = st_df[dir_col]
        df['signal'] = 0
        
        df.loc[df['st_dir'] == 1, 'signal'] = 1
        df.loc[df['st_dir'] == -1, 'signal'] = -1

        # Shift the signal column by one to ensure decisions are based on completed candles
        df['signal'] = df['signal'].shift(1)

        return df


class SupertrendStrategy_1h_10_3(BaseStrategy):
    """
    Supertrend Strategy (10, 3)
    Long when Supertrend Direction is Bullish (1)
    Short when Supertrend Direction is Bearish (-1)

    Defaults to '1m' timeframe.
    """

    def __init__(self, period=10, multiplier=3.0):
        super().__init__("SupertrendStrategy_1h_10_3")
        self.period = period
        self.multiplier = multiplier

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        # Select Timeframe
        if '1h' in data:
            df = data['1h'].copy()
        else:
            # Fallback
            tf = list(data.keys())[0]
            df = data[tf].copy()

        # Calculate Supertrend
        st_df = ta.supertrend(df['high'], df['low'], df['close'],
                              length=self.period,
                              multiplier=self.multiplier)

        if st_df is None:
            return df

        # Identify Direction Column
        dir_col = f"SUPERTd_{self.period}_{self.multiplier}"
        if dir_col not in st_df.columns:
            possible_cols = [c for c in st_df.columns if c.startswith('SUPERTd')]
            if possible_cols:
                dir_col = possible_cols[0]
            else:
                # Fallback if pandas_ta behaves oddly
                return df

        df['st_dir'] = st_df[dir_col]
        df['signal'] = 0

        df.loc[df['st_dir'] == 1, 'signal'] = 1
        df.loc[df['st_dir'] == -1, 'signal'] = -1

        # Shift the signal column by one to ensure decisions are based on completed candles
        df['signal'] = df['signal'].shift(1)

        return df


class SupertrendStrategy_3m_10_2(BaseStrategy):
    """
    Supertrend Strategy (10, 3)
    Long when Supertrend Direction is Bullish (1)
    Short when Supertrend Direction is Bearish (-1)

    Defaults to '1m' timeframe.
    """

    def __init__(self, period=10, multiplier=2.0):
        super().__init__("SupertrendStrategy_3m_10_2")
        self.period = period
        self.multiplier = multiplier

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        # Select Timeframe
        if '3m' in data:
            df = data['3m'].copy()
        else:
            # Fallback
            tf = list(data.keys())[0]
            df = data[tf].copy()

        # Calculate Supertrend
        st_df = ta.supertrend(df['high'], df['low'], df['close'],
                              length=self.period,
                              multiplier=self.multiplier)

        if st_df is None:
            return df

        # Identify Direction Column
        dir_col = f"SUPERTd_{self.period}_{self.multiplier}"
        if dir_col not in st_df.columns:
            possible_cols = [c for c in st_df.columns if c.startswith('SUPERTd')]
            if possible_cols:
                dir_col = possible_cols[0]
            else:
                # Fallback if pandas_ta behaves oddly
                return df

        df['st_dir'] = st_df[dir_col]
        df['signal'] = 0

        df.loc[df['st_dir'] == 1, 'signal'] = 1
        df.loc[df['st_dir'] == -1, 'signal'] = -1

        # Shift the signal column by one to ensure decisions are based on completed candles
        df['signal'] = df['signal'].shift(1)

        return df