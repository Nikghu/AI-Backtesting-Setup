import pandas as pd
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class SignalGenerator:
    """
    Converts strategy target signals (1, 0, -1) into discrete trade events.
    """

    @staticmethod
    def generate_trade_events(df: pd.DataFrame, intraday_enabled: bool = False, start_time: Any = None, stop_time: Any = None) -> List[Dict]:
        """
        Iterates through the DataFrame and generates trade events based on signal changes.
        
        Assumes 'signal' column exists where:
        1  = Target Long
        -1 = Target Short
        0  = Target Flat (Neutral)
        
        Outputs a list of dictionaries with:
        - Trade No
        - Type (Entry Long, Exit Long, Entry Short, Exit Short)
        - Date/Time
        """
        events = []
        trade_id = 0
        current_state = 0 # 0=Flat, 1=Long, -1=Short
        last_date = None
        
        # Ensure we have signal column
        if 'signal' not in df.columns:
            logger.warning("DataFrame missing 'signal' column. No trades generated.")
            return []

        # Iterate through rows. Using itertuples for speed.
        # df contains: timestamp, signal
        for row in df.itertuples():
            timestamp = row.timestamp
            signal = row.signal
            
            # Intraday Force Exit Logic
            if intraday_enabled and current_state != 0:
                exit_time = None
                if last_date is not None and timestamp.date() > last_date:
                    exit_time = pd.Timestamp.combine(last_date, stop_time)
                elif timestamp.time() >= stop_time:
                    exit_time = pd.Timestamp.combine(timestamp.date(), stop_time)
                
                if exit_time:
                    if current_state == 1:
                        events.append({"Trade No": trade_id, "Type": "Exit Long", "Date/Time": exit_time})
                    elif current_state == -1:
                        events.append({"Trade No": trade_id, "Type": "Exit Short", "Date/Time": exit_time})
                    current_state = 0

            last_date = timestamp.date()
            
            # Skip valid hold signals (NaN or same as current)
            # Treating NaN as "Hold/No Change"
            if pd.isna(signal):
                continue
                
            signal = int(signal)
            
            if signal == current_state:
                continue
                
            # State Change Detected
            
            # 1. Handle Exits first
            if current_state == 1:
                # closing long
                events.append({
                    "Trade No": trade_id,
                    "Type": "Exit Long",
                    "Date/Time": timestamp
                })
                current_state = 0
                
            elif current_state == -1:
                # closing short
                events.append({
                    "Trade No": trade_id,
                    "Type": "Exit Short",
                    "Date/Time": timestamp
                })
                current_state = 0
                
            # 2. Handle Entries
            # At this point current_state is 0
            
            if intraday_enabled and (timestamp.time() < start_time or timestamp.time() >= stop_time):
                continue

            if signal == 1:
                trade_id += 1
                events.append({
                    "Trade No": trade_id,
                    "Type": "Entry Long",
                    "Date/Time": timestamp
                })
                current_state = 1
                
            elif signal == -1:
                trade_id += 1
                events.append({
                    "Trade No": trade_id,
                    "Type": "Entry Short",
                    "Date/Time": timestamp
                })
                current_state = -1
                
        return events
