from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any

class BaseStrategy(ABC):
    """
    Abstract Base Class for all strategies.
    Now supports Multi-Timeframe access.
    """

    def __init__(self, name: str, params: Dict[str, Any] = None):
        self.name = name
        self.params = params or {}

    @abstractmethod
    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Takes a dictionary of DataFrames for a SINGLE symbol, keyed by timeframe.
        Example: {'1m': df_1m, '5m': df_5m}
        
        Must return a SINGLE DataFrame (usually the 'base' timeframe, e.g., '1m')
        with an additional 'signal' column:
        1 = Buy Trigger
        -1 = Sell Trigger
        0 = Neutral
        """
        pass
