from mt_quant_system.core.strategy import BaseStrategy
import pandas_ta as ta
import pandas as pd
from typing import Dict

class TemplateStrategy(BaseStrategy):
    """
    Template for your custom strategy.
    Now supports Multi-Timeframe.

    How to use Multi-Timeframe Data:
    --------------------------------
    The `generate_signals` method receives a `data` dictionary.
    - Keys: Timeframe strings (e.g., '1m', '3m', '5m', '15m', '1h', '1d').
            These depend on what data you have loaded/available.
    - Values: pandas DataFrames containing OHLCV data for that timeframe.
    
    Example:
        df_1m = data['1m']   # Base timeframe for entry/exit
        df_15m = data['15m'] # Higher timeframe for trend filter

    Output Requirements:
    --------------------
    You must return a SINGLE DataFrame (usually the base timeframe, e.g., '1m' or '3m').
    This DataFrame MUST contain a 'signal' column with the following values:
    -  1 : Long Entry / Hold Long
    - -1 : Short Entry / Hold Short
    -  0 : Neutral / Flat / Exit

    The system uses a stateful signal approach:
    - If signal changes from 0 to 1 -> Buy Trade
    - If signal changes from 1 to 0 -> Exit Buy
    - If signal changes from 0 to -1 -> Sell Trade
    - If signal changes from -1 to 0 -> Exit Sell
    """
    
    def __init__(self, **kwargs):
        super().__init__("TemplateStrategy", params=kwargs)

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        # 1. Select Base Timeframe (The timeframe where you execute trades)
        # Example: Use 1m as base for signals
        if '1m' in data:
            df = data['1m'].copy()
        else:
            # Fallback to the first available timeframe
            df = data[list(data.keys())[0]].copy()
            
        # 2. (Optional) Access Higher Timeframe Data
        # Example: Check 5m trend
        # if '5m' in data:
        #     df_5m = data['5m'].copy()
        #     # Calculate indicators on 5m
        #     df_5m['sma_50'] = ta.sma(df_5m['close'], length=50)
        #
        #     # Merge 5m data into base timeframe (e.g. 1m)
        #     # Use merge_asof to align timestamps (backward direction avoids lookahead bias)
        #     df = pd.merge_asof(
        #         df.sort_index(),
        #         df_5m[['sma_50']].sort_index(),
        #         left_index=True,
        #         right_index=True,
        #         direction='backward',
        #         suffixes=('', '_5m')
        #     )
        
        # 3. Calculate Indicators on Base Timeframe
        # df['rsi'] = ta.rsi(df['close'], length=14)
        
        # 4. Generate Signals
        # Logic: Set df['signal'] to 1 (Long), -1 (Short), or 0 (Neutral)
        df['signal'] = 0
        
        # Shift the signal column by one to ensure decisions are based on completed candles
        df['signal'] = df['signal'].shift(1)

        return df
