import pandas as pd
import numpy as np
import json
from typing import List, Dict, Any, Union, Tuple
from pathlib import Path
from .trade_analysis import analyze_trade_outcomes
# BO Fail analysis – temporary module; remove this import + call below to disable
from .bo_fail_analysis import run_bo_fail_analysis
import logging

logger = logging.getLogger(__name__)

def generate_backtest_report(events: Union[List[Dict], pd.DataFrame], tf_data: Dict[str, pd.DataFrame], output_path: str = None, 
                             initial_capital: float = 100000.0, instrument_type: str = "Spot", lot_size: int = 1,
                             analysis_tf: str = "3m", analysis_lookback: int = 10, losing_analysis: bool = False):
    """
    Generates a backtest report from trade events and market data.
    
    Args:
        events: List of event dictionaries or DataFrame with columns: 
               ['Trade No', 'Type', 'signal', 'Date/Time']
        tf_data: Dictionary containing dataframe of 1m candle data by timeframe key '1m'.
                 Must contain 'Open'/'open' column and 'timestamp' column or DatetimeIndex.
        output_path: Optional path to save the HTML report. If None, saves to reports/backtest_report.html
        initial_capital: Starting capital for ROI calculation.
        instrument_type: "Spot" or "Future".
        lot_size: Multiplier for Future contracts.
        analysis_tf: Timeframe to use for detailed trade analysis ('1m' or '3m').
        analysis_lookback: Number of bars to look back for swing analysis.
        losing_analysis: Whether to generate a separate detailed report for losing trades.
    """
    logger.info("Generating backtest report...")
    if '1m' not in tf_data:
        logger.error("1-minute data (tf_data['1m']) is required for report generation.")
        return

    # Use 1m data as base
    ohlc_data = tf_data['1m'].copy()
    
    # Ensure DatetimeIndex for searchsorted
    if not isinstance(ohlc_data.index, pd.DatetimeIndex):
        if 'timestamp' in ohlc_data.columns:
            ohlc_data = ohlc_data.set_index('timestamp')
        elif 'Date/Time' in ohlc_data.columns:
            ohlc_data = ohlc_data.set_index('Date/Time')
        else:
            # Fallback: look for any datetime column
            dt_cols = ohlc_data.select_dtypes(include=['datetime64']).columns
            if len(dt_cols) > 0:
                logger.info(f"Using column '{dt_cols[0]}' as index for pricing lookup.")
                ohlc_data = ohlc_data.set_index(dt_cols[0])
            else:
                logger.error("1-minute data must be indexed by datetime or contain a timestamp column.")
                return

    # Sort by time
    ohlc_data = ohlc_data.sort_index()

    # Determine Correct 'Open' Column Name (Case-insensitive check)
    open_col = 'Open'
    if 'open' in ohlc_data.columns:
        open_col = 'open'
    elif 'Open' not in ohlc_data.columns:
         logger.error("1-minute data must contain an 'Open' or 'open' column.")
         return

    # --- 1. Filter Data for Trade Analysis (Check available TFs first) ---
    analysis_data = None
    
    # 1. Try to use existing data if available
    if analysis_tf in tf_data:
        logger.info(f"Using provided {analysis_tf} data for Trade Analysis.")
        analysis_data = tf_data[analysis_tf].copy()
        # Ensure index
        if not isinstance(analysis_data.index, pd.DatetimeIndex):
            if 'timestamp' in analysis_data.columns:
                analysis_data = analysis_data.set_index('timestamp')
            elif 'Date/Time' in analysis_data.columns:
                analysis_data = analysis_data.set_index('Date/Time')
        # Sort
        analysis_data = analysis_data.sort_index()

    # 2. If not found, Resample from 1m
    if analysis_data is None:
        if analysis_tf == "3m":
            logger.info("Resampling 1m data to 3m for Trade Analysis (Source TF not provided)...")
            # Resample logic
            agg_dict = {}
            col_map = {c.lower(): c for c in ohlc_data.columns}
            
            o = col_map.get('open', 'Open')
            h = col_map.get('high', 'High')
            l = col_map.get('low', 'Low')
            c_col = col_map.get('close', 'Close')
            v = col_map.get('volume', 'Volume')
            
            if o in ohlc_data: agg_dict[o] = 'first'
            if h in ohlc_data: agg_dict[h] = 'max'
            if l in ohlc_data: agg_dict[l] = 'min'
            if c_col in ohlc_data: agg_dict[c_col] = 'last'
            if v in ohlc_data: agg_dict[v] = 'sum'
            
            if agg_dict:
                 analysis_data = ohlc_data.resample('3min').agg(agg_dict).dropna()
            else:
                logger.warning("Could not define aggregation logic for 3m resample. Using 1m data.")
                analysis_data = ohlc_data.copy()
        
        elif analysis_tf == "1m":
             logger.info("Using 1m data for Trade Analysis.")
             analysis_data = ohlc_data.copy()
             
        else:
             logger.warning(f"Unsupported analysis timeframe '{analysis_tf}' for resampling. Defaulting to 1m.")
             analysis_data = ohlc_data.copy()
            
    
    # Ensure events is a DataFrame for easier processing
    if isinstance(events, list):
        events_df = pd.DataFrame(events)
    else:
        events_df = events.copy()
        
    # Standardize Date/Time column to datetime objects
    # Handle potentially different formats. The example shows '03-01-2022 09:20' (DD-MM-YYYY)
    try:
        if not pd.api.types.is_datetime64_any_dtype(events_df['Date/Time']):
            events_df['Date/Time'] = pd.to_datetime(events_df['Date/Time'], dayfirst=True)
    except Exception as e:
        logger.error(f"Error parsing event dates: {e}")
        return

    trades = build_trades_from_events(events_df)
    
    if not trades:
        logger.warning("No complete trades found to report on.")
        return

    enriched_trades, summary_stats = calculate_trade_metrics(trades, ohlc_data, open_col, instrument_type, lot_size)
    
    # Calculate Advanced Metrics
    advanced_stats, chart_data, breakdowns = calculate_advanced_metrics(enriched_trades, initial_capital)
    
    # Merge stats
    full_stats = {**summary_stats, **advanced_stats}
    full_stats['Instrument Type'] = instrument_type
    full_stats['Lot Size'] = lot_size
    full_stats['Initial Capital'] = initial_capital

    # Risk Analysis Factors
    # Pass the specified analysis data and lookback
    risk_factors = {}
    if losing_analysis:
        logger.info(f"Running Risk Analysis with Timeframe={analysis_tf} and Lookback={analysis_lookback}")
        risk_factors = analyze_trade_outcomes(enriched_trades, analysis_data, lookback_period=analysis_lookback)

    if output_path:
        report_path = Path(output_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = Path("reports")
        output_dir.mkdir(exist_ok=True)
        report_path = output_dir / "backtest_report.html"

    # BO Fail indicator analysis – called only when losing_analysis is enabled
    # To remove: delete bo_fail_analysis.py and remove its import + this block
    if losing_analysis and risk_factors:
        bo_fail_path = str(report_path).replace(".html", "_bo_fail_analysis.html")
        run_bo_fail_analysis(enriched_trades, analysis_data, risk_factors, bo_fail_path)

    generate_html_report(enriched_trades, full_stats, str(report_path), chart_data, breakdowns, risk_factors, losing_analysis)
    logger.info(f"Backtest report generated at: {report_path}")


def build_trades_from_events(events_df: pd.DataFrame) -> List[Dict]:
    """
    reconstructs trades from flattened event logs.
    Groups by 'Trade No' and pairs Entry/Exit.
    """
    trades = []
    
    grouped = events_df.groupby('Trade No')
    
    for trade_no, group in grouped:
        # We need exactly one entry and one exit
        if len(group) != 2:
            # logger.debug(f"Skipping Trade {trade_no}: Found {len(group)} events, expected 2.")
            continue
            
        # Sort by time to be sure
        group = group.sort_values('Date/Time')
        
        entry_row = None
        exit_row = None
        
        for _, row in group.iterrows():
            evt_type = row['Type']
            if 'Entry' in evt_type:
                entry_row = row
            elif 'Exit' in evt_type:
                exit_row = row
                
        if entry_row is None or exit_row is None:
            # logger.debug(f"Skipping Trade {trade_no}: Missing Entry or Exit.")
            continue
            
        # Determine Direction
        direction = 'LONG' if 'Long' in entry_row['Type'] else 'SHORT'
        
        # Validation: check timestamps
        if exit_row['Date/Time'] <= entry_row['Date/Time']:
            logger.warning(f"Skipping Trade {trade_no}: Exit time <= Entry time.")
            continue
            
        trades.append({
            'Trade No': trade_no,
            'Type': direction,
            'Entry Date/Time': entry_row['Date/Time'],
            'Exit Date/Time': exit_row['Date/Time']
        })
        
    return trades


def get_price_at_time(timestamp: pd.Timestamp, ohlc_data: pd.DataFrame, price_col: str) -> float:
    """
    Finds the Open price at the specific timestamp.
    If exact timestamp missing, uses next available timestamp.
    """
    # Use searchsorted to find the index of the timestamp or the next one
    idx = ohlc_data.index.searchsorted(timestamp)
    
    if idx < len(ohlc_data):
        # We found a valid index (either exact match or next future candle)
        return ohlc_data.iloc[idx][price_col]
    else:
        # Timestamp is beyond the data range
        return None


def calculate_trade_metrics(trades: List[Dict], ohlc_data: pd.DataFrame, price_col: str = 'Open', instrument_type: str = "Spot", lot_size: int = 1) -> Tuple[List[Dict], Dict]:
    """
    Calculates PnL and other metrics for each trade.
    """
    processed_trades = []
    
    # Determine quantity
    quantity = lot_size if instrument_type == "Future" else 1

    # Pre-sort index for searchsorted if not already
    ohlc_data = ohlc_data.sort_index()

    for trade in trades:
        entry_time = trade['Entry Date/Time']
        exit_time = trade['Exit Date/Time']
        
        entry_price = get_price_at_time(entry_time, ohlc_data, price_col)
        exit_price = get_price_at_time(exit_time, ohlc_data, price_col)
        
        if entry_price is None or exit_price is None:
            logger.warning(f"Skipping Trade {trade['Trade No']}: Price data missing for {entry_time} or {exit_time}.")
            continue
            
        pnl = 0.0
        if trade['Type'] == 'LONG':
            pnl = (exit_price - entry_price) * quantity
        else: # SHORT
            pnl = (entry_price - exit_price) * quantity
            
        trade['Entry Price'] = entry_price
        trade['Exit Price'] = exit_price
        trade['Quantity'] = quantity
        trade['PnL'] = pnl
        trade['PnL %'] = (pnl / (entry_price * quantity)) * 100
        
        # Duration in minutes
        duration = (exit_time - entry_time).total_seconds() / 60
        trade['Duration (min)'] = duration
        
        processed_trades.append(trade)

    # --- Summary Metrics ---
    if not processed_trades:
        return [], {}
        
    df_trades = pd.DataFrame(processed_trades)
    
    total_trades = len(df_trades)
    winning_trades = df_trades[df_trades['PnL'] > 0]
    losing_trades = df_trades[df_trades['PnL'] <= 0]
    
    win_rate = (len(winning_trades) / total_trades) * 100 if total_trades > 0 else 0
    total_pnl = df_trades['PnL'].sum()
    avg_pnl = df_trades['PnL'].mean()
    
    # Calculate Daily PnL for Max Profit/Loss (per Day)
    df_trades['Exit Date'] = df_trades['Exit Date/Time'].dt.date
    daily_pnl = df_trades.groupby('Exit Date')['PnL'].sum()
    
    max_profit = daily_pnl.max()
    max_loss = daily_pnl.min()
    
    avg_duration = df_trades['Duration (min)'].mean()
    
    # Date Format for Max P/L
    fmt_d = '%d-%b-%y'
    date_style = 'font-size: 0.75rem; color: #58a6ff; font-weight: normal; display: block; margin-top: 4px;'
    
    max_profit_str = f"{round(max_profit, 2)}"
    if not daily_pnl.empty:
        try:
             # Find the date where daily_pnl is max
             date_max = daily_pnl.idxmax().strftime(fmt_d)
             max_profit_str += f'<span style="{date_style}">({date_max})</span>'
        except: pass

    max_loss_str = f"{round(max_loss, 2)}"
    if not daily_pnl.empty:
        try:
             date_min = daily_pnl.idxmin().strftime(fmt_d)
             max_loss_str += f'<span style="{date_style}">({date_min})</span>'
        except: pass

    summary = {
        'Total Trades': total_trades,
        'Winning Trades': len(winning_trades),
        'Losing Trades': len(losing_trades),
        'Win Rate (%)': round(win_rate, 2),
        'Total PnL': round(total_pnl, 2),
        'Average PnL': round(avg_pnl, 2),
        'Max Profit': max_profit_str,
        'Max Loss': max_loss_str,
        'Avg Duration (min)': round(avg_duration, 2)
    }
    
    return processed_trades, summary



def calculate_periodic_breakdowns(trades: List[Dict]) -> Dict[str, Any]:
    """
    Calculates PnL breakdowns by Month/Year and DayOfWeek/Year.
    Now includes Drawdown for each period.
    Returns: { 'monthly': { Year: { Month: {'pnl': x, 'dd': y}, ... } }, ... }
    """
    if not trades:
        return {'monthly': {}, 'weekly': {}}

    df = pd.DataFrame(trades)
    if 'Exit Date/Time' not in df.columns:
        return {'monthly': {}, 'weekly': {}}
        
    df['Exit Date/Time'] = pd.to_datetime(df['Exit Date/Time'])
    df['Year'] = df['Exit Date/Time'].dt.year
    df['Month'] = df['Exit Date/Time'].dt.month
    df['DayOfWeek'] = df['Exit Date/Time'].dt.dayofweek # 0=Mon, 6=Sun

    def get_stats(sub_df):
        if sub_df.empty: 
            return {'pnl': 0.0, 'dd': 0.0}
        
        # PnL
        pnl = sub_df['PnL'].sum()
        
        # Drawdown (Intra-period based on trade sequence)
        # Sort by actual exit time for correct sequence
        sub_df = sub_df.sort_values('Exit Date/Time')
        # Cumulative PnL relative to period start
        cum_pnl = sub_df['PnL'].cumsum()
        peak = cum_pnl.cummax()
        # Ensure peak does not drop below 0 (if starting equity is baseline)
        # But here we look at PnL curve starting at 0. Peak must be >= 0? 
        # Actually standard DD is Peak - Current. Peak is max(cum_pnl) seen so far.
        # Initial state is 0.
        peak = peak.apply(lambda x: max(0, x)) 
        
        dd = cum_pnl - peak
        mdd = dd.min()
        
        return {'pnl': float(pnl), 'dd': float(mdd if mdd < 0 else 0.0)}

    breakdowns = {'monthly': {}, 'weekly': {}}
    
    # --- Monthly Breakdown ---
    years = sorted(df['Year'].unique())
    for y in years:
        breakdowns['monthly'][int(y)] = {}
        yr_df = df[df['Year'] == y]
        
        # Months 1-12
        for m in range(1, 13):
            m_df = yr_df[yr_df['Month'] == m]
            breakdowns['monthly'][int(y)][m] = get_stats(m_df)
            
        # Total Year
        breakdowns['monthly'][int(y)]['Total'] = get_stats(yr_df)

    # --- Weekly Breakdown (Day of Week) ---
    for y in years:
        breakdowns['weekly'][int(y)] = {}
        yr_df = df[df['Year'] == y]
        
        # Days 0-4
        for d in range(5):
            d_df = yr_df[yr_df['DayOfWeek'] == d]
            breakdowns['weekly'][int(y)][d] = get_stats(d_df)
            
        breakdowns['weekly'][int(y)]['Total'] = get_stats(yr_df)
    
    return breakdowns


def calculate_advanced_metrics(trades: List[Dict], initial_capital: float = 100000.0) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Calculates advanced quantitative metrics based on processed trades.
    Includes daily PnL analysis, Drawdown, Ratios, etc.
    """
    if not trades:
        return {}, {'dates': [], 'cumulative_pnl': [], 'drawdown': []}, {'monthly': {}, 'weekly': {}}
        
    df_trades = pd.DataFrame(trades)
    
    # --- 1. Daily Aggregation ---
    # Based on Exit Date/Time
    df_trades['Exit Date'] = df_trades['Exit Date/Time'].dt.date
    daily_pnl = df_trades.groupby('Exit Date')['PnL'].sum()
    daily_pnl.index = pd.to_datetime(daily_pnl.index)

    # Calculate Daily Trade Counts (Win/Loss)
    daily_counts = df_trades.groupby('Exit Date')['PnL'].agg(
        wins=lambda x: (x > 0).sum(),
        losses=lambda x: (x <= 0).sum()
    )
    daily_counts.index = pd.to_datetime(daily_counts.index)
    # Ensure alignment with daily_pnl
    daily_counts = daily_counts.reindex(daily_pnl.index).fillna(0)
    
    # Fill gaps for calendar day analysis? 
    # Usually standard backtests analyze 'Trading Days' only.
    # We will proceed with Trading Days series.
    
    total_days = len(daily_pnl)
    winning_days = daily_pnl[daily_pnl > 0]
    losing_days = daily_pnl[daily_pnl < 0] # strictly less than 0
    
    # --- 2. Averages ---
    avg_day_pnl = daily_pnl.mean() if total_days > 0 else 0
    avg_profit_win_days = winning_days.mean() if not winning_days.empty else 0
    avg_loss_loss_days = losing_days.mean() if not losing_days.empty else 0
    
    # Reward to Risk Ratio (Daily)
    # Avoid div by zero
    rr_ratio = 0
    if abs(avg_loss_loss_days) > 1e-9:
        rr_ratio = avg_profit_win_days / abs(avg_loss_loss_days)
        
    # --- 3. Probability ---
    win_pct_days = (len(winning_days) / total_days * 100) if total_days > 0 else 0
    loss_pct_days = (len(losing_days) / total_days * 100) if total_days > 0 else 0

    # --- 4. Streaks ---
    def get_streak_details(series, condition_bool):
        # condition_bool is the boolean series matching the index of series
        if series.empty or not condition_bool.any():
            return 0, ""
            
        # 1 where condition is True, 0 otherwise
        s_int = condition_bool.astype(int)
        
        # Identify blocks of consecutive 1s
        # (s_int != s_int.shift()).cumsum() increments group ID on changes
        groups = (s_int != s_int.shift()).cumsum()
        
        # Filter for only groups where condition is True
        # We perform sum() by group. Groups of 0s sum to 0. Groups of 1s sum to length.
        streak_sums = s_int.groupby(groups).sum()
        
        # Also need to know if the group corresponds to 1 or 0
        # Check first value of each group
        is_true_group = condition_bool.groupby(groups).first()
        
        # Valid streaks are those where group is True
        valid_streaks = streak_sums[is_true_group]
        
        if valid_streaks.empty:
            return 0, ""
            
        max_streak_len = valid_streaks.max()
        if max_streak_len == 0: return 0, ""
        
        # Find which group ID had this max streak
        # Use valid_streaks.idxmax() - gets the first occurrence
        best_group_id = valid_streaks.idxmax()
        
        # Get start and end dates from the original series index
        group_indices = series.index[groups == best_group_id]
        
        # Format: 16-Dec-25
        fmt = '%d-%b-%y'
        start_date = group_indices[0].strftime(fmt)
        end_date = group_indices[-1].strftime(fmt)
        
        # Font style for date: small, blue, block display to put it on new line
        date_style = 'font-size: 0.75rem; color: #58a6ff; font-weight: normal; display: block; margin-top: 4px;'
        
        # Format: (Start to End)
        # If same day: (Date)
        if start_date == end_date:
            date_str = f'<span style="{date_style}">({start_date})</span>'
        else:
            date_str = f'<span style="{date_style}">({start_date} to {end_date})</span>'
            
        return int(max_streak_len), date_str

    # Warning: daily_pnl index is datetime
    is_win = daily_pnl > 0
    is_loss = daily_pnl < 0
    
    max_win_streak, max_win_dates = get_streak_details(daily_pnl, is_win)
    max_loss_streak, max_loss_dates = get_streak_details(daily_pnl, is_loss)
    
    # --- 5. Extremes ---
    max_profit_day = daily_pnl.max()
    max_loss_day = daily_pnl.min()
    
    # Format: 16-Dec-25
    fmt = '%d-%b-%y'
    # Same blue block style
    date_style = 'font-size: 0.75rem; color: #58a6ff; font-weight: normal; display: block; margin-top: 4px;'
    
    max_profit_date = ""
    max_loss_date = ""
    
    if not daily_pnl.empty:
        d_p = daily_pnl.idxmax().strftime(fmt)
        max_profit_date = f'<span style="{date_style}">({d_p})</span>'
        
        d_l = daily_pnl.idxmin().strftime(fmt)
        max_loss_date = f'<span style="{date_style}">({d_l})</span>'
    
    # --- 6. Equity & Drawdown ---
    # Construct Equity Curve (Start at 0 for PnL curve)
    equity_curve = daily_pnl.cumsum()
    peak = equity_curve.max()
    trough = equity_curve.min() # Min Equity (might be negative if start 0)
    
    # Running Max
    running_max = equity_curve.cummax()
    drawdown = equity_curve - running_max
    
    # MDD Stats
    highest_mdd = drawdown.min() # Typically negative number
    current_mdd = drawdown.iloc[-1] if not drawdown.empty else 0
    avg_drawdown = drawdown.mean()
    
    # Time in Drawdown (Days)
    # Consecutive days where drawdown < 0 (or <= if usually exact match? float drift suggests < -1e-9)
    is_in_dd = drawdown < -1e-9
    max_time_dd_days, max_dd_dates = get_streak_details(drawdown, is_in_dd)
    
    # --- 7. Ratios & Risk ---
    # Annualization Factor
    ANNUAL_FACTOR = 252 
    
    std_dev_daily = daily_pnl.std()
    
    # Sharpe (Zero Risk Free Rate)
    # Need annualized Avg PnL / Annualized Std Dev
    # Sharpe = (Mean_Daily * 252) / (Std_Daily * sqrt(252)) = (Mean/Std) * sqrt(252)
    sharpe_ratio = 0
    if std_dev_daily > 1e-9:
        sharpe_ratio = (daily_pnl.mean() / std_dev_daily) * np.sqrt(ANNUAL_FACTOR)
        
    # Sortino
    # Downside Deviation
    negative_returns = daily_pnl[daily_pnl < 0]
    downside_std = negative_returns.std() # Std dev of only negative returns? 
    # More precise definition: Std dev of (Returns where < Target), Target usually 0. 
    # Typically calculating root mean squared of negative deviation.
    # Let's perform standard calculation: sqrt(mean(min(0, r)^2))
    downside_squared = np.square(np.minimum(daily_pnl, 0))
    downside_deviation = np.sqrt(downside_squared.mean())
    
    sortino_ratio = 0
    if downside_deviation > 1e-9:
        sortino_ratio = (daily_pnl.mean() / downside_deviation) * np.sqrt(ANNUAL_FACTOR)
        
    # Calmar: Annualized Return / Max Drawdown (Absolute)
    # Annualized Return = Avg Daily PnL * 252
    annualized_return = daily_pnl.mean() * ANNUAL_FACTOR
    calmar_ratio = 0
    if abs(highest_mdd) > 1e-9:
        calmar_ratio = annualized_return / abs(highest_mdd)
        
    # Sterling: Annualized Return / Avg DD (or MaxDD + 10%)
    # User requested "Annualized return divided by average drawdown"
    sterling_ratio = 0
    if abs(avg_drawdown) > 1e-9:
        sterling_ratio = annualized_return / abs(avg_drawdown)

    # Omega Ratio: Sum(Pos) / Abs(Sum(Neg))
    sum_pos = daily_pnl[daily_pnl > 0].sum()
    sum_neg = daily_pnl[daily_pnl < 0].sum()
    omega_ratio = 0
    if abs(sum_neg) > 1e-9:
        omega_ratio = sum_pos / abs(sum_neg)
        
    # Recovery Factor: Total Net Profit / Max DD
    total_net_profit = daily_pnl.sum()
    recovery_factor = 0
    if abs(highest_mdd) > 1e-9:
        recovery_factor = total_net_profit / abs(highest_mdd)

    # Expectancy (Per Trade as common standard, though user allowed per day)
    # Re-calculate as Average PnL to align with standard definition in context of PnL reporting
    # Expectancy = Total PnL / Total Trades
    expectancy = df_trades['PnL'].mean() if not df_trades.empty else 0
    
    # Return on Investment %
    return_on_capital_pct = 0.0
    if initial_capital > 0:
        return_on_capital_pct = (total_net_profit / initial_capital) * 100

    # VaR & CVaR (Daily)
    # 95% Confidence VaR = 5th percentile of returns
    var_95 = np.percentile(daily_pnl, 5)
    var_99 = np.percentile(daily_pnl, 1)
    
    # CVaR (Expected Shortfall) = Mean of losses beyond VaR
    cvar_95 = daily_pnl[daily_pnl <= var_95].mean() if not daily_pnl[daily_pnl <= var_95].empty else 0 # Should use <=

    # Time in Profit %
    # Days Equity > 0 (assuming 0 start)
    days_in_profit = len(equity_curve[equity_curve > 0])
    time_in_profit_pct = (days_in_profit / total_days * 100) if total_days > 0 else 0
    
    # Assemble Dictionary
    # Note: Adding dates to streaks/max values as strings. JS charts handled separately.
    metrics = {
        'Overall Profit and Loss': round(total_net_profit, 2),
        'Return on Capital %': round(return_on_capital_pct, 2),
        'Avg Day PNL': round(avg_day_pnl, 2),
        'Avg Profit On Win Days': round(avg_profit_win_days, 2),
        'Avg Loss On Loss Days': round(avg_loss_loss_days, 2),
        'Reward To Risk Ratio (Daily)': round(rr_ratio, 2),
        'Total Days': total_days,
        'Win% (Days)': round(win_pct_days, 2),
        'Loss% (Days)': round(loss_pct_days, 2),
        'Max Winning Streak': f"{max_win_streak} {max_win_dates}",
        'Max Losing Streak': f"{max_loss_streak} {max_loss_dates}",
        'Max Profit (Day)': f"{round(max_profit_day, 2)} {max_profit_date}",
        'Max Loss (Day)': f"{round(max_loss_day, 2)} {max_loss_date}",
        'Current MDD': round(current_mdd, 2),
        'Highest MDD': round(highest_mdd, 2),
        'Avg Drawdown': round(avg_drawdown, 2),
        'Expectancy (Per Trade)': round(expectancy, 2),
        'Peak Equity': round(peak, 2),
        'Trough Equity': round(trough, 2),
        'Time DD (Max Days)': f"{max_time_dd_days} {max_dd_dates}",
        'Standard Deviation (Daily)': round(std_dev_daily, 2),
        'Sharpe Ratio': round(sharpe_ratio, 2),
        'Sortino Ratio': round(sortino_ratio, 2),
        'Calmar Ratio': round(calmar_ratio, 2),
        'Sterling Ratio': round(sterling_ratio, 2),
        'Omega Ratio': round(omega_ratio, 2),
        'Recovery Factor': round(recovery_factor, 2),
        'VAR 95%': round(var_95, 2),
        'VAR 99%': round(var_99, 2),
        'CVaR (Expected Tail)': round(cvar_95, 2),
        'Time in Profit %': round(time_in_profit_pct, 2)
    }
    
    chart_data = {
        'dates': daily_pnl.index.strftime('%Y-%m-%d').tolist(),
        'cumulative_pnl': equity_curve.fillna(0).tolist(),
        'daily_pnl': daily_pnl.fillna(0).tolist(),
        'drawdown': drawdown.fillna(0).tolist(),
        'daily_wins': daily_counts['wins'].tolist(),
        'daily_losses': (-1 * daily_counts['losses']).tolist() # Negative for downward plotting
    }
    
    breakdowns = calculate_periodic_breakdowns(trades)

    return metrics, chart_data, breakdowns


def generate_html_report(trades: List[Dict], summary: Dict, output_path: str, chart_data: Dict = None, breakdowns: Dict = None, risk_factors: Union[Dict, Any] = None, losing_analysis: bool = False):
    """
    Generates a self-contained HTML report with a split-view dashboard layout.
    """
    
    # CSS Styles
    css = """
    <style>
        :root {
            --bg-color: #0d1117; 
            --sidebar-bg: #010409;
            --container-bg: #0d1117;
            --card-bg: #161b22;
            --card-hover: #1f2428;
            --border-color: #30363d;
            --text-primary: #e6edf3; 
            --text-secondary: #8b949e;
            --accent-primary: #2f81f7;
            --accent-pos: #3fb950;
            --accent-neg: #f85149;
            --nav-hover: #21262d;
            --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
        }

        body, html {
            height: 100%;
            margin: 0;
            padding: 0;
            font-family: var(--font-family);
            background-color: var(--bg-color);
            color: var(--text-primary);
            overflow: hidden; 
            -webkit-font-smoothing: antialiased;
        }

        /* Layout Container */
        .app-container {
            display: flex;
            height: 100vh;
            width: 100%;
        }

        /* Sidebar */
        .sidebar {
            width: 280px;
            background-color: rgba(31, 111, 235, 0.08); /* Transparent Blue */
            border: 1px solid rgba(56, 139, 253, 0.15);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
            margin: 12px; /* Gap around the panel */
            border-radius: 16px; /* Round edges */
            height: calc(100vh - 24px); /* Adjust height for margins */
            backdrop-filter: blur(10px);
        }

        .sidebar-header {
            padding: 24px;
            border-bottom: 1px solid rgba(56, 139, 253, 0.1);
            background: transparent;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .brand-logo {
            width: 38px; 
            height: 38px;
            color: #58a6ff;
            background: rgba(88, 166, 255, 0.15);
            padding: 8px;
            border-radius: 8px;
            flex-shrink: 0;
        }

        .sidebar-title {
            font-size: 1.25rem;
            font-weight: 700;
            background: linear-gradient(90deg, #58a6ff, #a5d6ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 0;
            letter-spacing: -0.5px;
        }

        .sidebar-subtitle {
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-top: 6px;
            font-weight: 500;
        }

        .nav-links {
            list-style: none;
            padding: 16px 12px;
            margin: 0;
            flex: 1;
            overflow-y: auto;
        }

        .nav-item {
            padding: 10px 16px;
            margin-bottom: 4px;
            cursor: pointer;
            color: var(--text-secondary);
            font-size: 0.95rem;
            font-weight: 500;
            transition: all 0.2s ease;
            border-radius: 6px;
            display: flex;
            align-items: center;
        }

        .nav-icon {
            margin-right: 12px;
            opacity: 0.7;
        }
        .nav-item:hover .nav-icon, .nav-item.active .nav-icon {
            opacity: 1;
        }

        .nav-item:hover {
            background-color: var(--nav-hover);
            color: var(--text-primary);
        }

        .nav-item.active {
            background-color: #1f6feb;
            color: #ffffff;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(31, 111, 235, 0.2);
        }
        
        .nav-footer {
            padding: 24px;
            font-size: 0.75rem;
            color: #8b949e;
            border-top: 1px solid rgba(56, 139, 253, 0.1);
            text-align: center;
            background-color: transparent;
        }

        /* Content Area */
        .content-area {
            flex: 1;
            overflow-y: auto;
            padding: 30px 40px;
            background-color: var(--bg-color);
        }

        /* Header in Content */
        .report-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            margin-bottom: 30px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 20px;
        }

        .page-title h2 {
            margin: 0;
            font-size: 2rem;
            font-weight: 700;
            background: linear-gradient(90deg, #58a6ff, #a5d6ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
            transition: all 0.3s ease;
        }

        .header-meta {
            display: flex;
            gap: 12px;
            align-items: center;
        }
        
        .meta-tag {
            display: flex;
            align-items: center;
            background-color: rgba(56, 139, 253, 0.1);
            border: 1px solid rgba(56, 139, 253, 0.2);
            border-radius: 6px;
            padding: 6px 14px;
            font-size: 0.85rem;
            color: var(--text-secondary);
        }
        
        .meta-tag strong {
            color: var(--text-primary);
            margin-left: 6px;
            font-weight: 600;
        }

        /* Tabs Logic */
        .tab-content { display: none; animation: fadeIn 0.3s ease; }
        .tab-content.active { display: block; }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(5px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Metrics & Cards (Reused) */
        .section-header {
            margin-bottom: 20px;
            margin-top: 10px;
        }

        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        /* Chart Container */
        .chart-wrapper {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
            margin-top: 30px;
            height: 400px;
            position: relative;
        }

        /* Periodic Matrix Tables */
        .matrix-table-container {
            margin-top: 30px;
            overflow-x: auto;
        }
        .matrix-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }
        .matrix-table th, .matrix-table td {
            text-align: center;
            padding: 10px;
            border: 1px solid var(--border-color);
        }
        .matrix-table th {
            background-color: var(--card-bg);
            font-weight: 600;
        }
        .matrix-table .year-col {
            text-align: left;
            font-weight: 600;
            background-color: var(--card-bg);
            position: sticky; 
            left: 0;
        }
        .cell-pos { background-color: rgba(63, 185, 80, 0.15); color: #3fb950; }
        .cell-neg { background-color: rgba(248, 81, 73, 0.15); color: #f85149; }
        .cell-neu { color: var(--text-secondary); }
        .matrix-title {
            font-size: 1rem;
            font-weight: 600;
            color: var(--text-primary);
        }
        
        .section-header-flex {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .view-toggle {
            display: flex;
            background: #21262d;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 2px;
        }
        
        .view-btn {
            background: transparent;
            border: none;
            color: var(--text-secondary);
            padding: 4px 12px;
            font-size: 0.8rem;
            cursor: pointer;
            border-radius: 4px;
            font-weight: 500;
        }
        
        .view-btn.active {
            background: #1f6feb;
            color: #fff;
        }

        .view-content { display: none; }
        .view-content.active { display: block; }
        
        .breakdown-chart-wrapper {
            height: 350px;
            width: 100%;
        }

        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 20px;
            margin-bottom: 30px;
        }

        .metric-card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 24px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            align-items: center;
            text-align: center;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .metric-card:hover {
            transform: translateY(-4px);
            border-color: #8b949e;
            box-shadow: 0 12px 24px rgba(0,0,0,0.2);
            background-color: #1c2128;
        }

        .metric-label {
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 12px;
        }

        .metric-value {
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--text-primary);
            letter-spacing: -0.5px;
        }
        
        /* KPI Cards */
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 24px;
            margin-bottom: 48px;
        }
        
        .kpi-card {
            background: #161b22;
            border: 1px solid var(--border-color);
            position: relative;
            padding: 32px;
            border-radius: 10px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
            overflow: hidden;
            transition: transform 0.2s;
        }
        .kpi-card:hover { transform: translateY(-2px); }
        .kpi-card::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0; height: 4px;
            background: var(--accent-primary); 
        }
        
        .kpi-card .metric-label { font-size: 0.85rem; margin-bottom: 16px;}
        .kpi-card .metric-value { font-size: 2.8rem; line-height: 1.1; }

        /* Typography Colors */
        .text-pos { color: var(--accent-pos) !important; }
        .text-neg { color: var(--accent-neg) !important; }

        /* Table */
        .table-container {
            width: 100%;
            overflow-x: auto;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            background: var(--card-bg);
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
            white-space: nowrap;
        }

        th, td {
            padding: 16px 20px;
            text-align: right;
            border-bottom: 1px solid var(--border-color);
        }

        th {
            background: #1c2128;
            color: var(--text-secondary);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.75rem;
            position: sticky;
            top: 0;
            z-index: 10;
        }
        
        th:first-child, td:first-child { text-align: left; }
        th:nth-child(2), td:nth-child(2) { text-align: center; } 
        tr:hover { background-color: var(--card-hover); }

        .badge {
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.5px;
        }
        .badge-long { background: rgba(56, 139, 253, 0.15); color: #58a6ff; border: 1px solid rgba(56, 139, 253, 0.3); }
        .badge-short { background: rgba(210, 153, 34, 0.15); color: #e3b341; border: 1px solid rgba(210, 153, 34, 0.3); }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #30363d; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #58a6ff; }
    </style>
    """
    
    # ------------------
    # Data Preparation
    # ------------------
    
    # Section Maps
    sections_map = {
        'dashboard': {
            'title': 'Performance',
            'items': [
                ('Overall Profit and Loss', 'Overall Profit and Loss'),
                ('Avg Day PNL', 'Avg Day PNL'),
                ('Average PnL', 'Avg Portfolio PNL'),
                ('Max Profit', 'Max Profit'),
                ('Max Loss', 'Max Loss'),
                ('Total Days', 'Total Days'),
                ('Win% (Days)', 'Win% (Days)'),
                ('Loss% (Days)', 'Loss% (Days)'),
                ('Max Winning Streak', 'Max Winning Streak'),
                ('Max Losing Streak', 'Max Losing Streak'),
                ('Avg Profit On Win Days', 'Avg Profit On Win Days'),
                ('Avg Loss On Loss Days', 'Avg Loss On Loss Days'),
                ('Reward To Risk Ratio (Daily)', 'Reward To Risk Ratio'),
                ('Expectancy (Per Trade)', 'Expectancy'),
                ('Time DD (Max Days)', 'Max Drawdown (Days)')
            ]
        },
        'risk': {
            'title': 'Risk Analysis',
            'items': [
                ('Winning Trades', 'Winning Trades'),
                ('Losing Trades', 'Losing Trades'),
                ('Avg Duration (min)', 'Avg Duration (min)'),
                ('Win Rate (%)', 'Win Rate (%)'),
                ('Total Trades', 'Total Trades'),
                ('Current MDD', 'Current MDD'),
                ('Avg Drawdown', 'Avg Drawdown'),
                ('Peak Equity', 'Peak Equity'),
                ('Trough Equity', 'Trough Equity'),
                ('Standard Deviation (Daily)', 'Standard Deviation (Daily)'),
                ('Sortino Ratio', 'Sortino Ratio'),
                ('Calmar Ratio', 'Calmar Ratio'),
                ('Sterling Ratio', 'Sterling Ratio'),
                ('Omega Ratio', 'Omega Ratio'),
                ('VAR 95%', 'VAR 95%'),
                ('VAR 99%', 'VAR 99%'),
                ('CVaR (Expected Tail)', 'CVaR (Expected Tail)')
            ]
        }
    }

    def format_value(k, val):
        val_str = str(val)
        css_class = ""
        # Always run formatting logic even if val is not int/float directly (e.g. formatted string)
        # But we need basic classification
        
        # If val is float, format first
        if isinstance(val, float): 
            val_str = f"{val:.2f}"
            
        k_lower = k.lower()
        
        # 1. Negative override for "losing streak" or "max loss" etc.
        if 'losing streak' in k_lower:
            css_class = "text-neg"
            
        # 2. PnL / Profit logic 
        # (Exclude "Profit and Loss" from falling into Loss logic below if it is positive)
        # Using separate if/elif structure to ensure PnL takes precedence unless it's strictly a Loss metric
        elif any(x in k_lower for x in ['pnl', 'profit', 'sharpe', 'sortino', 'return', 'win', 'expectancy']): 
             try:
                 # Clean HTML if present for parsing
                 clean_val = val_str.split('<')[0].strip()
                 v_float = float(clean_val.split(' ')[0] if ' ' in clean_val else clean_val)
                 if v_float > 0: css_class = "text-pos"
                 elif v_float < 0: css_class = "text-neg"
             except: pass

        # 3. Loss / Drawdown logic
        elif any(x in k_lower for x in ['loss', 'drawdown', 'dd']):
             # If it wasn't caught by the Profit block above (e.g. "Overall Profit and Loss" is handled above)
             css_class = "text-neg"

        # Format Rupee symbol with Indian Numbering System
        rupee_keys = [
            'Overall Profit and Loss', 'Avg Day PNL', 'Average PnL', 
            'Max Profit', 'Max Loss', 'Avg Profit On Win Days', 'Avg Loss On Loss Days',
            'Peak Equity', 'Standard Deviation (Daily)', 'VAR 95%', 'VAR 99%', 
            'CVaR (Expected Tail)', 'Avg Drawdown', 'Current MDD', 
            'Expectancy (Per Trade)'
        ]
        
        if k in rupee_keys:
             # Extract number vs HTML suffix (for Max Profit/Loss dates)
             parts = val_str.split('<')
             number_str = parts[0].strip()
             suffix = ""
             if len(parts) > 1:
                 suffix = " <" + "<".join(parts[1:])
             
             if '₹' not in number_str:
                 try:
                     f_val = float(number_str.replace(',', ''))
                     is_neg = f_val < 0
                     f_val = abs(f_val)
                     
                     s_val, d_val = f"{f_val:.2f}".split('.')
                     
                     if len(s_val) > 3:
                        last3 = s_val[-3:]
                        rest = s_val[:-3]
                        
                        # Indian commatization for the rest
                        rest_parts = []
                        while len(rest) > 2:
                            rest_parts.insert(0, rest[-2:])
                            rest = rest[:-2]
                        rest_parts.insert(0, rest)
                        
                        s_val = ",".join(rest_parts) + "," + last3
                     
                     formatted = f"₹ {s_val}.{d_val}"
                     if is_neg:
                        formatted = "-" + formatted
                        
                     val_str = formatted + suffix
                 except:
                     # Fallback
                     pass

        return val_str, css_class

    def render_grid_html(items, is_kpi=False, section_id=None):
        if is_kpi:
            grid_class = "kpi-grid"
            card_class = "kpi-card"
        elif section_id == 'dashboard':
            grid_class = "dashboard-grid"
            card_class = "metric-card"
        else:
            grid_class = "metrics-grid"
            card_class = "metric-card"
        
        html = f'<div class="{grid_class}">'
        for key, label in items:
            if key in summary:
                val = summary[key]
                val_str, css_class = format_value(key, val)
                
                style_attr = ""
                if is_kpi and key == 'Overall Profit and Loss':
                    if val > 0: style_attr = "border-top-color: var(--accent-pos);"
                    else: style_attr = "border-top-color: var(--accent-neg);"
                
                html += f"""
                <div class="{card_class}" style="{style_attr}">
                    <div class="metric-label">{label}</div>
                    <div class="metric-value {css_class}">{val_str}</div>
                </div>
                """
        html += '</div>'
        return html

    # Generate Grids
    # kpi_html = render_grid_html(kpi_keys, is_kpi=True) # Disabled as merged
    
    sections_html = {}
    for sec_id, info in sections_map.items():
        sections_html[sec_id] = render_grid_html(info['items'], section_id=sec_id)

    # Trade Table
    table_rows = ""
    for t in trades:
        type_badge = "badge badge-long" if t['Type'] == 'LONG' else "badge badge-short"
        pnl_val, pnl_class = format_value('PnL', t['PnL'])
        pnl_pct_val, pnl_pct_class = format_value('PnL %', t['PnL %'])
        
        table_rows += f"""
        <tr>
            <td class="text-left">{t['Trade No']}</td>
            <td><span class="{type_badge}">{t['Type']}</span></td>
            <td>{t['Entry Date/Time']}</td>
            <td>{t['Exit Date/Time']}</td>
            <td>{t['Entry Price']:.2f}</td>
            <td>{t['Exit Price']:.2f}</td>
            <td class="{pnl_class}">{pnl_val}</td>
            <td class="{pnl_pct_class}">{pnl_pct_val}%</td>
            <td>{t['Quantity']}</td>
            <td>{(t['Duration (min)'] / 60):.2f}</td>
        </tr>
        """
        
    table_html = f"""
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th class="text-left">Trade #</th>
                    <th class="text-center">Type</th>
                    <th>Entry Time</th>
                    <th>Exit Time</th>
                    <th>Entry Price</th>
                    <th>Exit Price</th>
                    <th>PnL</th>
                    <th>PnL %</th>
                    <th>Qty</th>
                    <th>Duration (Hrs)</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </div>
    """

    # Chart Data Serialization
    c_dates = json.dumps(chart_data.get('dates', [])) if chart_data else "[]"
    c_equity = json.dumps(chart_data.get('cumulative_pnl', [])) if chart_data else "[]"
    c_daily_pnl = json.dumps(chart_data.get('daily_pnl', [])) if chart_data else "[]"
    c_drawdown = json.dumps(chart_data.get('drawdown', [])) if chart_data else "[]"
    c_daily_wins = json.dumps(chart_data.get('daily_wins', [])) if chart_data else "[]"
    c_daily_losses = json.dumps(chart_data.get('daily_losses', [])) if chart_data else "[]"
    
    # Breakdown Data Serialization
    c_breakdowns = json.dumps(breakdowns) if breakdowns else "{}"

    # ------------------
    # Breakdown Tables HTML
    # ------------------
    monthly_html = ""
    weekly_html = ""
    
    def render_breakdown_section(data, columns_map, title, section_id):
        if not data: return ""
        
        # Header
        thead = '<tr><th class="year-col">Year</th>'
        for _, lbl in columns_map:
            thead += f'<th>{lbl}</th>'
        thead += '<th>Total</th></tr>'
        
        # Body
        tbody = ""
        years = sorted(data.keys()) # Ascending years
        for year in years:
            row_html = f'<tr><td class="year-col">{year}</td>'
            
            # Data cells
            for col_key, _ in columns_map:
                try:
                    cell_data = data[year].get(col_key, {'pnl': 0, 'dd': 0})
                    # Handle if data structure is mixed (migration safety, though not needed for clean run)
                    if isinstance(cell_data, (int, float)): 
                        val = cell_data
                        dd = 0
                    else:
                        val = cell_data.get('pnl', 0)
                        dd = cell_data.get('dd', 0)
                except:
                    val = 0
                    dd = 0
                
                css_class = "cell-neu"
                if val > 0: css_class = "cell-pos"
                elif val < 0: css_class = "cell-neg"
                
                # Format PnL
                val_str = f"{val:.2f}"
                if summary.get('Instrument Type') == 'Future': val_str = f"₹ {val_str}"
                
                # Format DD
                dd_html = ""
                if dd < 0:
                    dd_str = f"{dd:.2f}"
                    # No Rupee symbol asked for DD, but good to have if PnL has it? 
                    # User request: "DD shall be red font and add it in(), just below the monthly PNL"
                    if summary.get('Instrument Type') == 'Future': dd_str = f"₹ {dd_str}"
                    dd_html = f'<div style="color: #f85149; font-size: 0.75rem; margin-top: 2px;">({dd_str})</div>'
                
                row_html += f'<td class="{css_class}"><div>{val_str}</div>{dd_html}</td>'

            # Total cell
            try:
                t_data = data[year].get('Total', {'pnl': 0, 'dd': 0})
                if isinstance(t_data, (int, float)):
                    total_val = t_data
                    total_dd = 0
                else:
                    total_val = t_data.get('pnl', 0)
                    total_dd = t_data.get('dd', 0)
            except:
                total_val = 0
                total_dd = 0

            t_css = "cell-neu"
            if total_val > 0: t_css = "cell-pos"
            elif total_val < 0: t_css = "cell-neg"
            
            t_str = f"{total_val:.2f}"
            if summary.get('Instrument Type') == 'Future': t_str = f"₹ {t_str}"
            
            t_dd_html = ""
            if total_dd < 0:
                t_dd_str = f"{total_dd:.2f}"
                if summary.get('Instrument Type') == 'Future': t_dd_str = f"₹ {t_dd_str}"
                t_dd_html = f'<div style="color: #f85149; font-size: 0.75rem; margin-top: 2px;">({t_dd_str})</div>'
            
            row_html += f'<td class="{t_css}"><strong>{t_str}</strong>{t_dd_html}</td></tr>'
            tbody += row_html
            
        return f"""
        <div class="matrix-table-container">
            <div class="section-header-flex">
                <div class="matrix-title">{title}</div>
                <div class="view-toggle">
                    <button class="view-btn active" onclick="switchView('{section_id}', 'table', this)">Table</button>
                    <button class="view-btn" onclick="switchView('{section_id}', 'bar', this)">Bar View</button>
                </div>
            </div>
            
            <div id="{section_id}-table" class="view-content active">
                <table class="matrix-table">
                    <thead>{thead}</thead>
                    <tbody>{tbody}</tbody>
                </table>
            </div>
            
            <div id="{section_id}-bar" class="view-content">
                <div class="breakdown-chart-wrapper">
                    <canvas id="{section_id}Chart"></canvas>
                </div>
            </div>
        </div>
        """

    if breakdowns:
        # Monthly: 1-12
        months_map = [(i, pd.to_datetime(f"2000-{i}-01").strftime('%b')) for i in range(1, 13)]
        monthly_html = render_breakdown_section(breakdowns.get('monthly'), months_map, "Monthly Breakdown", "monthly")
        
        # Weekly: 0-4
        days_map = [(0, 'Mon'), (1, 'Tue'), (2, 'Wed'), (3, 'Thu'), (4, 'Fri')]
        weekly_html = render_breakdown_section(breakdowns.get('weekly'), days_map, "Weekly Breakdown", "weekly")

    # Risk Factors HTML
    # Check if risk_factors has the 'metrics' key (new format) or is just a dict (old format, fallback)
    metrics_data = risk_factors.get('metrics', risk_factors) if risk_factors else {}
    total_analyzed = risk_factors.get('total_analyzed', 0) if risk_factors else 0
    
    losing_factors_content = ""
    if metrics_data:
        # Sort based on 'pct' if it's a dict, or value if it's a float (compat)
        # item is (name, value)
        # value is {'count': X, 'pct': Y} OR float Y
        
        def get_pct(item):
            val = item[1]
            if isinstance(val, dict): return val['pct']
            return val
            
        sorted_factors = sorted(metrics_data.items(), key=get_pct, reverse=True)
        
        # Mapping for Short Names
        short_name_map = {
            'Opposite Move > 0.25%': 'Opp > 0.25%',
            'Opposite Move > 0.50%': 'Opp > 0.50%',
            'Favorable Move > 0.25%': 'Fav > 0.25%',
            'Favorable Move > 0.50%': 'Fav > 0.50%',
            'Recent Low Broken': 'Low Broken',
            'Entry Candle High Never Broken': 'Entry Unbroken',
            'Breakout Failure': 'BO Fail',
            'Range Re-Entry Failure': 'Range Re-Entry',
            'Immediate Reversal (5 candles)': 'Imm. Rev',
            'Lower High Formation': 'LH Form'
        }

        rows = ""
        for name, val in sorted_factors:
            pct = 0
            count_str = ""
            
            # Add Short Name
            short = short_name_map.get(name, "")
            display_name = f"{name} <span style='color: #8b949e;'>({short})</span>" if short else name

            if isinstance(val, dict):
                pct = val['pct']
                count = val.get('count', 0)
                count_str = f"({count})"
            else:
                pct = val
                
            rows += f"""
            <div style="display: flex; align-items: center; font-size: 0.85rem;">
                <div style="width: 250px; color: var(--text-secondary); flex-shrink: 0;">{display_name}</div>
                <div style="flex: 1; background: #21262d; height: 8px; border-radius: 4px; overflow: hidden; margin: 0 15px;">
                    <div style="width: {pct}%; background: #f85149; height: 100%;"></div>
                </div>
                <div style="width: 80px; text-align: right; font-weight: 600; color: #f85149;">
                    {pct:.1f}% <span style="font-weight: normal; color: #8b949e; font-size: 0.75rem;">{count_str}</span>
                </div>
            </div>
            """
            
        losing_factors_content = f"""
        <div class="metric-card" style="align-items: stretch; text-align: left; margin-top: 20px;">
            <div style="font-size: 1rem; font-weight: 600; color: var(--text-primary); margin-bottom: 20px;">
                Losing Trade Factors 
                <span style="font-size:0.8rem; color:var(--text-secondary); font-weight:normal; margin-left: 10px;">
                    (Total Trades Analyzed: {total_analyzed})
                </span>
            </div>
            <div style="display: flex; flex-direction: column; gap: 12px; max-height: 400px; overflow-y: auto;">
                {rows}
            </div>
        </div>
        """


    # Losing Trades Detailed Table
    losing_trades_content = ""
    risk_trades = risk_factors.get('trades', []) if risk_factors else []
    
    if risk_trades:
        risk_rows = ""
        # Sort keys to ensure column alignment
        keys = ['Opp > 0.25%', 'Opp > 0.50%', 'Fav > 0.25%', 'Fav > 0.50%', 
                'Low Broken', 'Entry Unbroken', 'BO Fail', 'Range Re-Entry', 
                'Imm. Rev', 'LH Form']
        
        for rt in risk_trades:
            # Type badge
            type_badge = "badge badge-long" if rt['Type'] == 'LONG' else "badge badge-short"
            
            # Build parameter cells
            param_cells = ""
            for k in keys:
                val = rt.get(k, 0)
                # Style for 1/0
                cell_style = 'color: #f85149; font-weight: bold;' if val == 1 else 'color: #30363d;'
                param_cells += f'<td style="text-align: center; {cell_style}">{val}</td>'
                
            risk_rows += f"""
            <tr>
                <td class="text-left">{rt['Trade No']}</td>
                <td>{rt['Entry Time']}</td>
                <td>{rt['Exit Time']}</td>
                <td style="text-align: center;"><span class="{type_badge}">{rt['Type']}</span></td>
                {param_cells}
            </tr>
            """
            
        losing_trades_content = f"""
        <div style="margin-top: 30px;">
            <h3 style="font-size: 1.1rem; font-weight: 600; color: var(--text-primary); margin-bottom: 15px;">
                Losing Trades Detailed Analysis
            </h3>
            <div class="table-container" style="max-height: 600px; overflow-y: auto;">
                <table>
                    <thead>
                        <tr>
                            <th class="text-left" style="position: sticky; left: 0; background: #1c2128; z-index: 20;">Trade #</th>
                            <th>Entry Time</th>
                            <th>Exit Time</th>
                            <th style="text-align: center;">Type</th>
                            <th style="text-align: center;" title="Opposite Move > 0.25%">Opp > 0.25%</th>
                            <th style="text-align: center;" title="Opposite Move > 0.50%">Opp > 0.50%</th>
                            <th style="text-align: center;" title="Favorable Move > 0.25%">Fav > 0.25%</th>
                            <th style="text-align: center;" title="Favorable Move > 0.50%">Fav > 0.50%</th>
                            <th style="text-align: center;" title="Recent Low Broken">Low Broken</th>
                            <th style="text-align: center;" title="Entry Candle High Never Broken">Entry Unbroken</th>
                            <th style="text-align: center;" title="Breakout Failure">BO Fail</th>
                            <th style="text-align: center;" title="Range Re-Entry Failure">Range Re-Entry</th>
                            <th style="text-align: center;" title="Immediate Reversal">Imm. Rev</th>
                            <th style="text-align: center;" title="Lower High Formation">LH Form</th>
                        </tr>
                    </thead>
                    <tbody>
                        {risk_rows}
                    </tbody>
                </table>
            </div>
        </div>
        """
        
    # Generate Separate HTML if requested
    if losing_analysis and (losing_factors_content or losing_trades_content):
        if output_path:
             losing_report_path = str(output_path).replace('.html', '_losing_analysis.html')
             
             losing_html = f"""
             <!DOCTYPE html>
             <html lang="en">
             <head>
                <title>Losing Trade Analysis</title>
                <meta charset="utf-8">
                {css}
                <style>
                    body {{ background-color: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; padding: 20px; }}
                    /* Ensure containers fit separate page */
                    .app-container {{ max-width: 1400px; margin: 0 auto; }}
                </style>
             </head>
             <body>
                <h1 style="color:white;">Losing Trade Analysis</h1>
                <p>Derived from {summary.get('Instrument Type', '')} Backtest</p>
                {losing_factors_content}
                {losing_trades_content}
             </body>
             </html>
             """
             try:
                 with open(losing_report_path, 'w', encoding='utf-8') as f:
                     f.write(losing_html)
                 logger.info(f"Generated losing trade analysis at: {losing_report_path}")
             except Exception as e:
                 logger.error(f"Failed to write losing trade analysis: {e}")

    # Set main variables to empty to exclude from main report
    risk_factors_html = ""
    risk_trades_html = ""

    # ------------------
    # HTML Layout
    # ------------------
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Backtest Report - {summary.get('Instrument Type', '')}</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {css}
    </head>
    <body>
        <div class="app-container">
            <!-- LEFT PANEL: Sidebar -->
            <nav class="sidebar">
                <div class="sidebar-header">
                    <svg class="brand-logo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                    </svg>
                    <div>
                        <div class="sidebar-title">Indexmisbn Analytics</div>
                        <div class="sidebar-subtitle">Backtest Strategy Report</div>
                    </div>
                </div>
                <ul class="nav-links">
                    <li class="nav-item active" onclick="showTab('dashboard', this)">
                        <svg class="nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
                        Performance
                    </li>
                    <li class="nav-item" onclick="showTab('risk', this)">
                        <svg class="nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                        Risk Analysis
                    </li>
                    <li class="nav-item" onclick="showTab('log', this)">
                         <svg class="nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                        Trade Log
                    </li>
                </ul>
                <div class="nav-footer">
                   Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}
                </div>
            </nav>

            <!-- RIGHT PANEL: Content -->
            <main class="content-area">
                
                <!-- Common Header for Context -->
                <div class="report-header">
                    <div class="page-title">
                        <h2 id="page-title">Performance</h2>
                    </div>
                    <div class="header-meta">
                        <div class="meta-tag">
                            Instrument: <strong>{summary.get('Instrument Type', 'N/A')}</strong>
                        </div>
                        <div class="meta-tag">
                            Initial Capital: <strong>{summary.get('Initial Capital', 'N/A')}</strong>
                        </div>
                        <div class="meta-tag">
                            Lot Size: <strong>{summary.get('Lot Size', 1)}</strong>
                        </div>
                    </div>
                </div>

                <!-- Tab: Performance Overview (Dashboard) -->
                <div id="dashboard" class="tab-content active">
                     {sections_html['dashboard']}
                     <div class="chart-wrapper">
                        <canvas id="performanceChart"></canvas>
                     </div>

                     <div class="chart-wrapper">
                        <canvas id="dailyPnLChart"></canvas>
                     </div>
                     
                     {monthly_html}
                     {weekly_html}
                </div>

                <!-- Tab: Risk Analysis -->
                <div id="risk" class="tab-content">
                     {sections_html['risk']}
                     {risk_factors_html}
                     {risk_trades_html}
                </div>

                <!-- Tab: Trade Log -->
                <div id="log" class="tab-content">
                    <div class="chart-wrapper" style="height: 300px; margin-bottom: 20px;">
                        <canvas id="tradeCountChart"></canvas>
                    </div>
                    {table_html}
                </div>
                
            </main>
        </div>

        <script>
            function showTab(tabId, element) {{
                // Update Sidebar
                const navItems = document.querySelectorAll('.nav-item');
                navItems.forEach(item => item.classList.remove('active'));
                element.classList.add('active');

                // Update Content
                const contents = document.querySelectorAll('.tab-content');
                contents.forEach(content => content.classList.remove('active'));
                document.getElementById(tabId).classList.add('active');
                
                // Update Title
                const titleMap = {{
                    'dashboard': 'Performance',
                    'risk': 'Risk Analysis',
                    'log': 'Trade Log'
                }};
                
                const titleEl = document.getElementById('page-title');
                titleEl.style.opacity = '0';
                titleEl.style.transform = 'translateY(-10px)';
                
                setTimeout(() => {{
                    titleEl.innerText = titleMap[tabId];
                    titleEl.style.opacity = '1';
                    titleEl.style.transform = 'translateY(0)';
                }}, 200);
            }}
            
            function switchView(sectionId, viewType, btn) {{
                // Toggle Content
                document.getElementById(sectionId + '-table').classList.remove('active');
                document.getElementById(sectionId + '-bar').classList.remove('active');
                document.getElementById(sectionId + '-' + viewType).classList.add('active');
                
                // Toggle Buttons
                const parent = btn.parentElement;
                parent.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            }}

            // Chart Initialization
            document.addEventListener('DOMContentLoaded', function() {{
                const ctx = document.getElementById('performanceChart').getContext('2d');
                const ctxDaily = document.getElementById('dailyPnLChart').getContext('2d');
                const dates = {c_dates};
                const equity = {c_equity};
                const dailyPnL = {c_daily_pnl};
                const drawdown = {c_drawdown};
                const breakdowns = {c_breakdowns};
                const dailyWins = {c_daily_wins};
                const dailyLosses = {c_daily_losses};
                
                // Performance Chart
                if (dates.length > 0) {{
                    new Chart(ctx, {{
                        type: 'line',
                        data: {{
                            labels: dates,
                            datasets: [
                                {{
                                    label: 'Cumulative PnL',
                                    data: equity,
                                    borderColor: '#3fb950',
                                    backgroundColor: 'rgba(63, 185, 80, 0.1)',
                                    borderWidth: 2,
                                    tension: 0.1,
                                    fill: true,
                                    yAxisID: 'y'
                                }},
                                {{
                                    label: 'Drawdown',
                                    data: drawdown,
                                    borderColor: '#f85149',
                                    backgroundColor: 'rgba(248, 81, 73, 0.1)',
                                    borderWidth: 1,
                                    tension: 0.1,
                                    fill: true,
                                    yAxisID: 'y1'
                                }}
                            ]
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            interaction: {{
                                mode: 'index',
                                intersect: false,
                            }},
                            scales: {{
                                x: {{
                                    grid: {{ color: '#30363d' }},
                                    ticks: {{ color: '#8b949e' }}
                                }},
                                y: {{
                                    type: 'linear',
                                    display: true,
                                    position: 'left',
                                    grid: {{ color: '#30363d' }},
                                    ticks: {{ color: '#8b949e' }},
                                    title: {{ display: true, text: 'PnL', color: '#8b949e' }}
                                }},
                                y1: {{
                                    type: 'linear',
                                    display: true,
                                    position: 'right',
                                    grid: {{ drawOnChartArea: false }},
                                    ticks: {{ color: '#8b949e' }},
                                    title: {{ display: true, text: 'Drawdown', color: '#8b949e' }}
                                }}
                            }},
                            plugins: {{
                                legend: {{ labels: {{ color: '#e6edf3' }} }},
                                tooltip: {{ mode: 'index', intersect: false }}
                            }}
                        }}
                    }});

                    // Daily PnL Chart
                    const bgColors = dailyPnL.map(v => v >= 0 ? '#3fb950' : '#f85149');
                    new Chart(ctxDaily, {{
                        type: 'bar',
                        data: {{
                            labels: dates,
                            datasets: [
                                {{
                                    label: 'Daily PnL',
                                    data: dailyPnL,
                                    backgroundColor: bgColors,
                                    borderRadius: 2
                                }}
                            ]
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            scales: {{
                                x: {{
                                    grid: {{ display: false }},
                                    ticks: {{ maxTicksLimit: 20, color: '#8b949e' }}
                                }},
                                y: {{
                                    grid: {{ color: '#30363d' }},
                                    ticks: {{ color: '#8b949e' }}
                                }}
                            }},
                            plugins: {{
                                legend: {{ display: false }},
                                title: {{ display: true, text: 'Daily Profit & Loss', color: '#e6edf3', font: {{ size: 14, weight: 'normal' }} }}
                            }}
                        }}
                    }});

                    // Trade Count Chart
                    const ctxCount = document.getElementById('tradeCountChart').getContext('2d');
                    new Chart(ctxCount, {{
                        type: 'bar',
                        data: {{
                            labels: dates,
                            datasets: [
                                {{
                                    label: 'Winning Trades',
                                    data: dailyWins,
                                    backgroundColor: '#3fb950',
                                    stack: 'Stack 0'
                                }},
                                {{
                                    label: 'Losing Trades',
                                    data: dailyLosses,
                                    backgroundColor: '#f85149',
                                    stack: 'Stack 0'
                                }}
                            ]
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            scales: {{
                                x: {{
                                    stacked: true,
                                    grid: {{ display: false }},
                                    ticks: {{ maxTicksLimit: 20, color: '#8b949e' }}
                                }},
                                y: {{
                                    stacked: true,
                                    grid: {{ color: '#30363d' }},
                                    ticks: {{ 
                                        color: '#8b949e', 
                                        stepSize: 1,
                                        callback: function(value) {{ return Math.abs(value); }}
                                    }},
                                    title: {{ display: true, text: 'Trade Count', color: '#8b949e' }}
                                }}
                            }},
                            plugins: {{
                                legend: {{ labels: {{ color: '#e6edf3' }} }},
                                tooltip: {{
                                    callbacks: {{
                                        label: function(context) {{
                                            let label = context.dataset.label || '';
                                            if (label) {{
                                                label += ': ';
                                            }}
                                            if (context.parsed.y !== null) {{
                                                label += Math.abs(context.parsed.y);
                                            }}
                                            return label;
                                        }}
                                    }}
                                }},
                                title: {{ display: true, text: 'Daily Trade Frequency (Win vs Loss)', color: '#e6edf3', font: {{ size: 14, weight: 'normal' }} }}
                            }}
                        }}
                    }});
                }}
                
                // Helper to render Breakdown Chart
                function renderBreakdownChart(canvasId, data, labelsMap, title) {{
                    if (!data || Object.keys(data).length === 0) return;
                    
                    const ctxB = document.getElementById(canvasId).getContext('2d');
                    const years = Object.keys(data).sort();
                    const datasets = [];
                    const colors = ['#2f81f7', '#3fb950', '#a371f7', '#f1e05a', '#f85149', '#d29922', '#db6d28'];
                    
                    years.forEach((year, index) => {{
                        const yearData = [];
                        // Iterate through labelsMap keys (1..12 or 0..4)
                        for (let i = 0; i < labelsMap.length; i++) {{
                            const key = labelsMap[i].key; 
                            const cell = data[year][key];
                            // Handle both old (number) and new (object) format
                            let val = 0;
                            if (typeof cell === 'number') {{
                                val = cell;
                            }} else if (cell && typeof cell === 'object') {{
                                val = cell.pnl || 0;
                            }}
                            yearData.push(val);
                        }}
                        
                        datasets.push({{
                            label: year,
                            data: yearData,
                            backgroundColor: colors[index % colors.length],
                            borderWidth: 0,
                            barPercentage: 0.6,
                            categoryPercentage: 0.8
                        }});
                    }});
                    
                    new Chart(ctxB, {{
                        type: 'bar',
                        data: {{
                            labels: labelsMap.map(x => x.label),
                            datasets: datasets
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            scales: {{
                                x: {{ 
                                    grid: {{ display: false }},
                                    ticks: {{ color: '#8b949e' }}
                                }},
                                y: {{
                                    grid: {{ color: '#30363d' }},
                                    ticks: {{ color: '#8b949e' }}
                                }}
                            }},
                            plugins: {{
                                legend: {{ labels: {{ color: '#e6edf3' }} }},
                                title: {{ display: false }}
                            }}
                        }}
                    }});
                }}
                
                if (breakdowns.monthly) {{
                   const mLabels = [
                       {{key: '1', label: 'Jan'}}, {{key: '2', label: 'Feb'}}, {{key: '3', label: 'Mar'}}, 
                       {{key: '4', label: 'Apr'}}, {{key: '5', label: 'May'}}, {{key: '6', label: 'Jun'}},
                       {{key: '7', label: 'Jul'}}, {{key: '8', label: 'Aug'}}, {{key: '9', label: 'Sep'}}, 
                       {{key: '10', label: 'Oct'}}, {{key: '11', label: 'Nov'}}, {{key: '12', label: 'Dec'}}
                   ];
                   renderBreakdownChart('monthlyChart', breakdowns.monthly, mLabels, 'Monthly PnL');
                }}
                
                if (breakdowns.weekly) {{
                   const wLabels = [
                       {{key: '0', label: 'Mon'}}, {{key: '1', label: 'Tue'}}, {{key: '2', label: 'Wed'}}, 
                       {{key: '3', label: 'Thu'}}, {{key: '4', label: 'Fri'}}
                   ];
                   renderBreakdownChart('weeklyChart', breakdowns.weekly, wLabels, 'Weekly PnL');
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
    except Exception as e:
        logger.error(f"Failed to write HTML report: {e}")
