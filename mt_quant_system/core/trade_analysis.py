import pandas as pd
import numpy as np
from typing import List, Dict, Any

def analyze_trade_outcomes(trades: List[Dict], ohlc_data: pd.DataFrame, lookback_period: int = 20) -> Dict[str, Any]:
    """
    Analyzes losing trades based on specific boolean parameters.
    Returns the percentage of losing trades where each parameter was True.
    """
    
    # Filter for LOOSING trades only as per request
    losing_trades = [t for t in trades if t['PnL'] <= 0]
    total_losing = len(losing_trades)
    
    if total_losing == 0:
        return {}
    
    # Initialize counters & output structure first
    final_output = {
        'total_analyzed': total_losing,
        'metrics': {},
        'trades': []
    }

    counters = {
        'Opposite Move > 0.25%': 0,
        'Opposite Move > 0.50%': 0,
        'Favorable Move > 0.25%': 0,
        'Favorable Move > 0.50%': 0,
        'Recent Low Broken': 0,
        'Entry Candle High Never Broken': 0,
        'Breakout Failure': 0,
        'Range Re-Entry Failure': 0,
        'Immediate Reversal (5 candles)': 0,
        'Lower High Formation': 0
    }
    
    # Ensure OHLC data is sorted and accessible
    if not isinstance(ohlc_data.index, pd.DatetimeIndex):
         # Try setting index if possible, otherwise return empty
         pass 

    # Standardize columns
    col_map = {c.lower(): c for c in ohlc_data.columns}
    high_col = col_map.get('high', 'High' if 'High' in ohlc_data.columns else None)
    low_col = col_map.get('low', 'Low' if 'Low' in ohlc_data.columns else None)
    close_col = col_map.get('close', 'Close' if 'Close' in ohlc_data.columns else None)
    
    if not (high_col and low_col and close_col):
        return {}

    # Helper for finding local extrema
    def find_pivots(series, window=3):
        # A simple pivot detection
        pivots = []
        if len(series) < window * 2 + 1:
            return pivots
        
        for i in range(window, len(series) - window):
            curr = series.iloc[i]
            is_max = True
            for j in range(1, window + 1):
                if series.iloc[i-j] > curr or series.iloc[i+j] > curr:
                    is_max = False
                    break
            if is_max:
                pivots.append(curr)
        return pivots

    for trade in losing_trades:
        entry_time = pd.to_datetime(trade['Entry Date/Time'])
        exit_time = pd.to_datetime(trade['Exit Date/Time'])
        direction = trade['Type']
        entry_price = trade['Entry Price']
        
        # 1. Get Trade Data (Entry to Exit)
        # Use slicing on DatetimeIndex
        try:
            trade_data = ohlc_data.loc[entry_time:exit_time]
            if len(trade_data) == 0:
                continue
        except KeyError:
            continue
            
        # 2. Get Pre-Entry Data (Lookback)
        # We need to find the location of entry time and slice backwards
        try:
            # We use searchsorted to find position
            entry_idx = ohlc_data.index.searchsorted(entry_time)
            start_idx = max(0, entry_idx - lookback_period)
            pre_entry_data = ohlc_data.iloc[start_idx:entry_idx]
        except:
            pre_entry_data = pd.DataFrame()

        # --- Calculations ---
        
        # Common Arrays
        try:
            highs = trade_data[high_col]
            lows = trade_data[low_col]
            closes = trade_data[close_col]
        except KeyError: continue
        
        max_high = highs.max()
        min_low = lows.min()
        
        # Parameter 1 & 2: Opposite Move > 0.25% / 0.50%
        # Parameter 3 & 4: Favorable Move > 0.25% / 0.50%
        # Parameter 9: Immediate Reversal (Within 5 Candles)
        
        is_opp_25 = False
        is_opp_50 = False
        is_fav_25 = False
        is_fav_50 = False
        is_immed_rev = False
        
        # Check first 5 candles for reversal
        check_candles = 5
        early_data = trade_data.iloc[:check_candles]
        
        if direction == 'LONG':
            # Opposite = Down
            max_adverse = (entry_price - min_low) / entry_price
            max_favorable = (max_high - entry_price) / entry_price
            
            if max_adverse >= 0.0025: is_opp_25 = True
            if max_adverse >= 0.0050: is_opp_50 = True
            if max_favorable >= 0.0025: is_fav_25 = True
            if max_favorable >= 0.0050: is_fav_50 = True
            
            # Immediate Reversal: Close < Entry within N bars? 
            # Or simplified: Did it go against us immediately? 
            # "Did price move adversely" -> Let's check if Close < Entry at any point in first N bars
            if (early_data[close_col] < entry_price).any():
                is_immed_rev = True
                
        else: # SHORT
            # Opposite = Up
            max_adverse = (max_high - entry_price) / entry_price
            max_favorable = (entry_price - min_low) / entry_price
            
            if max_adverse >= 0.0025: is_opp_25 = True
            if max_adverse >= 0.0050: is_opp_50 = True
            if max_favorable >= 0.0025: is_fav_25 = True
            if max_favorable >= 0.0050: is_fav_50 = True
            
            if (early_data[close_col] > entry_price).any():
                is_immed_rev = True

        if is_opp_25: counters['Opposite Move > 0.25%'] += 1
        if is_opp_50: counters['Opposite Move > 0.50%'] += 1
        if is_fav_25: counters['Favorable Move > 0.25%'] += 1
        if is_fav_50: counters['Favorable Move > 0.50%'] += 1
        if is_immed_rev: counters['Immediate Reversal (5 candles)'] += 1
        
        # Parameter 5: Recent Low Broken (Long) / Recent High Broken (Short)
        is_recent_broken = False
        if not pre_entry_data.empty:
            if direction == 'LONG':
                recent_low = pre_entry_data[low_col].min()
                if min_low < recent_low:
                    is_recent_broken = True
            else:
                recent_high = pre_entry_data[high_col].max()
                if max_high > recent_high:
                    is_recent_broken = True
        
        if is_recent_broken: counters['Recent Low Broken'] += 1

        # Parameter 6: Entry Candle High Never Broken (Long) / Low Never Broken (Short)
        is_entry_unbroken = False
        # Entry candle is roughly the first candle of trade_data if timestamps align
        # or we might need the specific entry minute candle.
        # Assuming trade_data includes the entry candle at index 0 or close to it.
        # Strict interpretation: Price ACTION after entry.
        
        if len(trade_data) > 1:
            try:
                # Use the actual entry timestamp to find the entry candle row
                entry_candle_idx = ohlc_data.index.searchsorted(entry_time)
                if entry_candle_idx < len(ohlc_data):
                    entry_candle = ohlc_data.iloc[entry_candle_idx]
                    
                    # Look at future data during trade (excluding entry candle itself if possible? 
                    # usually "never broken" implies subsequent bars)
                    # Slicing trade_data from index 1:
                    future_prices = trade_data.iloc[1:]
                    
                    if not future_prices.empty:
                        if direction == 'LONG':
                            entry_high = entry_candle[high_col]
                            # Did we ever trade above entry high?
                            # If Max High of future < Entry High -> Never Broken
                            if future_prices[high_col].max() <= entry_high:
                                is_entry_unbroken = True
                        else:
                            entry_low = entry_candle[low_col]
                            # If Min Low of future > Entry Low -> Never Broken
                            if future_prices[low_col].min() >= entry_low:
                                is_entry_unbroken = True
            except:
                pass
        
        if is_entry_unbroken: counters['Entry Candle High Never Broken'] += 1
        
        # Parameter 7: Breakout Failure
        # Logic: If Entry was above Pre-Entry High (Long), did Price return below Pre-Entry High?
        # Parameter 8: Range Re-Entry Failure
        # Logic: Did price enter the body of the previous range?
        # We'll use lookback period min/max to define "Range"
        
        is_breakout_fail = False
        is_range_reentry = False
        
        if not pre_entry_data.empty:
            pre_high = pre_entry_data[high_col].max()
            pre_low = pre_entry_data[low_col].min()
            
            if direction == 'LONG':
                # Assume Breakout if Entry > Pre_High (or close to it)
                # But let's apply the condition regardless: Did price go back into the range?
                
                # Breakout Failure: Price drops below the breakout level (Pre_High)
                if min_low < pre_high:
                     # Check if it was logically a breakout (Entry >= Pre_High usually)
                     # If entry was inside range, this metric is less meaningful, but 
                     # "Breakout Failure" implies we tried to go up.
                     # Let's count it if we dipped below the recent high.
                     is_breakout_fail = True
                     
                # Range Re-Entry: Deeper penetration?
                # "Re-enter prior consolidation"
                # Let's say if it goes below the Midpoint of the prior range?
                # Or simply below the High again? (Same as 7?)
                # User distinguishes: 7 is "return back inside breakout range", 
                # 8 is "re-enter prior consolidation".
                # Let's define 7 as < Pre_High.
                # Let's define 8 as < (Pre_High + Pre_Low) / 2? Or simply < Pre_High is re-entry?
                # Maybe 7 is "Close < Pre_High" (Confirmed failure) vs just wicking?
                # Let's use: 7 -> Price < Pre_High. 8 -> Price < Midpoint.
                
                if min_low < pre_high:
                    is_breakout_fail = True
                
                midpoint = (pre_high + pre_low) / 2
                if min_low < midpoint:
                    is_range_reentry = True
                    
            else: # SHORT
                # Breakout below Pre_Low
                if max_high > pre_low:
                    is_breakout_fail = True
                
                midpoint = (pre_high + pre_low) / 2
                if max_high > midpoint:
                    is_range_reentry = True
                    
        if is_breakout_fail: counters['Breakout Failure'] += 1
        if is_range_reentry: counters['Range Re-Entry Failure'] += 1
        
        # Parameter 10: Lower High Formation (Long) / Higher Low (Short)
        is_structure_break = False
        
        if len(trade_data) > 5:
            # Detect peaks
            if direction == 'LONG':
                # Check for Lower Highs
                # We need at least two significant peaks
                peaks = find_pivots(trade_data[high_col])
                if len(peaks) >= 2:
                    # Check if any subsequent peak is lower than previous significant peak
                    # Simple check: Last peak < First peak?
                    # Or sequential descent?
                    # "Did price form a lower high after entry"
                    # If we find ANY instance of Peak2 < Peak1, it's a lower high.
                    for i in range(1, len(peaks)):
                        if peaks[i] < peaks[i-1]:
                            is_structure_break = True
                            break
            else:
                # Check for Higher Lows
                troughs = find_pivots(trade_data[low_col])
                if len(troughs) >= 2:
                    for i in range(1, len(troughs)):
                        if troughs[i] > troughs[i-1]:
                            is_structure_break = True
                            break
                            
        if is_structure_break: counters['Lower High Formation'] += 1
        
        # Append detailed trade result
        final_output['trades'].append({
            'Trade No': trade.get('Trade No', 'N/A'),
            'Entry Time': entry_time,
            'Exit Time': exit_time,
            'Type': direction,
            'Opp > 0.25%': 1 if is_opp_25 else 0,
            'Opp > 0.50%': 1 if is_opp_50 else 0,
            'Fav > 0.25%': 1 if is_fav_25 else 0,
            'Fav > 0.50%': 1 if is_fav_50 else 0,
            'Low Broken': 1 if is_recent_broken else 0,
            'Entry Unbroken': 1 if is_entry_unbroken else 0,
            'BO Fail': 1 if is_breakout_fail else 0,
            'Range Re-Entry': 1 if is_range_reentry else 0,
            'Imm. Rev': 1 if is_immed_rev else 0,
            'LH Form': 1 if is_structure_break else 0
        })

    # Returns Percentages and Counts
    
    for k, v in counters.items():
        final_output['metrics'][k] = {
            'count': v,
            'pct': (v / total_losing) * 100
        }
        
    return final_output
