import argparse
import sys
import logging
import traceback
from pathlib import Path
from typing import List, Tuple, Dict, Any
import pandas as pd
# Add project root to sys.path if running as script
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mt_quant_system.core.data_loader import DataLoader
from mt_quant_system.core.signal_generator import SignalGenerator
from mt_quant_system.core.exporter import MtQuantExporter
from mt_quant_system import strategies
from mt_quant_system.core.gui import get_user_selection
from mt_quant_system.core.report_generator import generate_backtest_report

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    """
    Main entry point for the IndexMisBn Backtesting.
    """
    parser = argparse.ArgumentParser(description="IndexMisBn Backtesting")
    parser.add_argument("--input", help="Path to input feather file (optional if file exists in data folder)")
    parser.add_argument("--output", help="Path to output CSV file (optional, auto-generated with timestamp)")
    parser.add_argument("--strategy", help="Name of the strategy class to run (optional, prompts user if not provided)")
    
    args = parser.parse_args()

    # 1. Strategy & Configuration Selection
    available_strategies = strategies.load_strategies()
    
    # Initialize variables
    input_path = None
    strategy_name = args.strategy
    
    if args.strategy:
        # CLI Mode: Input defaults or argument
        input_path = resolve_input_path(args.input)
        logger.info(f"CLI Mode: Using input file {input_path}")
        
        # Load Data explicitly for CLI mode to get metadata for validation (optional, or just run)
        # For simplicity, we load data here, then define defaults.
    else:
        # GUI Mode
        logger.info("Opening Configuration Dialog...")
        try:
            # GUI returns input_path as first element
            input_path, strategy_name, selected_symbols, selected_timeframes, start_date, end_date, intraday_enabled, start_time, stop_time, instrument_type, lot_size, initial_capital, analysis_tf, analysis_lookback, losing_analysis, debug_mode = get_run_configuration(
                None, available_strategies, args.input
            )
            
            if not input_path:
                logger.warning("Operation cancelled by user.")
                sys.exit(0)
                
        except Exception as e:
            logger.error(f"GUI Error: {e}")
            traceback.print_exc()
            sys.exit(1)

    logger.info("--- Starting IndexMisBn Backtesting ---")
    logger.info(f"Target Data File: {input_path}")
    
    # 2. Load Data
    try:
        loader = DataLoader(input_path)
        data = loader.load_data()
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        sys.exit(1)

    # 3. Analyze Data Metadata (needed for CLI defaults if strict, or filtering)
    available_symbols, tf_ranges = extract_data_metadata(data)

    # 4. Finalize Configuration (for CLI mode)
    if args.strategy:
        # If we are in CLI mode, we need to populate the variables that GUI would have
        selected_symbols = available_symbols
        selected_timeframes = list(tf_ranges.keys())
        
        # Calc global min/max across all TFs
        all_dates = []
        for r in tf_ranges.values():
            all_dates.extend(r)
        if all_dates:
            start_date = min(all_dates).date()
            end_date = max(all_dates).date()
            
        intraday_enabled = False
        start_time = None
        stop_time = None
        instrument_type = "Spot"
        lot_size = 1
        initial_capital = 100000.0
        analysis_tf = "3m"
        analysis_lookback = 10
        losing_analysis = False
        debug_mode = False

        logger.info(f"CLI Defaults: All Symbols, All Timeframes, Full Date Range")
    
    if strategy_name not in available_strategies:
        logger.error(f"Strategy '{strategy_name}' not found. Available: {list(available_strategies.keys())}")
        sys.exit(1)
        
    # 5. Filter Data
    symbol_groups = filter_and_group_data(data, selected_symbols, selected_timeframes, start_date, end_date)
    
    if not symbol_groups:
        logger.warning("No data found matching the selected criteria (Date/Symbol/Timeframe).")
        sys.exit(0)

    # 6. Process & Export
    process_and_export(symbol_groups, available_strategies[strategy_name], strategy_name, intraday_enabled, start_time, stop_time, instrument_type, lot_size, initial_capital, analysis_tf, analysis_lookback, losing_analysis, debug_mode)

    logger.info("--- Processing Complete ---")


def resolve_input_path(args_input: str) -> str:
    """Determines the input file path from arguments or auto-detection (No GUI)."""
    if args_input:
        return args_input
    
    # Fallback: Auto-detect from data/ folder
    data_dir = Path("data")
    if not data_dir.exists():
            pass
    
    files = list(data_dir.glob("*.feather"))
    if not files:
        logger.error(f"No .feather files found in {data_dir.absolute()}")
        sys.exit(1)
    
    input_path = str(files[0]) # Take the first one
    return input_path


def extract_data_metadata(data: Dict[Tuple[str, str], pd.DataFrame]) -> Tuple[List[str], Dict[str, Tuple[Any, Any]]]:
    """Analyzes loaded data to find available symbols and date ranges per timeframe."""
    # Identify unique symbols
    available_symbols = sorted(list(set(k[0] for k in data.keys())))
    
    # Calculate date range per timeframe (Global Union)
    tf_ranges = {} # tf_name -> (global_min, global_max)
    
    for (sym, tf), df in data.items():
        if df.empty: continue
        d_min = df['timestamp'].min().to_pydatetime()
        d_max = df['timestamp'].max().to_pydatetime()
        
        if tf not in tf_ranges:
            tf_ranges[tf] = (d_min, d_max)
        else:
            current_min, current_max = tf_ranges[tf]
            tf_ranges[tf] = (min(current_min, d_min), max(current_max, d_max))

    return available_symbols, tf_ranges


def get_run_configuration(strategy_name: str, available_strategies: Dict[str, Any], input_path: str = None) -> Tuple:
    """Determines run configuration via GUI."""
    # Only called for GUI mode in new flow
    
    logger.info("Opening Strategy Selection Dialog...")
    return get_user_selection(
        list(available_strategies.keys()), input_path
    )


def filter_and_group_data(data: Dict[Tuple[str, str], pd.DataFrame], 
                         selected_symbols: List[str], selected_timeframes: List[str], 
                         start_date: Any, end_date: Any) -> Dict[str, Dict[str, pd.DataFrame]]:
    """Filters data based on selection and groups by symbol."""
    symbol_groups = {}
    
    ts_start = pd.Timestamp(start_date)
    ts_end = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1) # End of day

    for (symbol, timeframe), df in data.items():
        # Filter Criteria
        if symbol not in selected_symbols:
            continue
        if timeframe not in selected_timeframes:
            continue
            
        mask = (df['timestamp'] >= ts_start) & (df['timestamp'] <= ts_end)
        filtered_df = df.loc[mask].copy()
        
        if filtered_df.empty:
            continue
            
        if symbol not in symbol_groups:
            symbol_groups[symbol] = {}
        symbol_groups[symbol][timeframe] = filtered_df
        
    return symbol_groups


def process_and_export(symbol_groups: Dict[str, Dict[str, pd.DataFrame]], strategy_class: Any, strategy_name: str, 
                       intraday_enabled: bool = False, start_time: Any = None, stop_time: Any = None,
                       instrument_type: str = "Spot", lot_size: int = 1, initial_capital: float = 100000.0,
                       analysis_tf: str = "3m", analysis_lookback: int = 10, losing_analysis: bool = False, debug_mode: bool = False):
    """Runs strategy for each symbol and exports results."""
    strategy = strategy_class()
    logger.info(f"Initialized Strategy: {strategy.name}")
    
    timestamp_str = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    # Construct filename suffix based on intraday settings
    file_suffix = ""
    if intraday_enabled and start_time and stop_time:
        # Format times as strings (assuming start_time/stop_time are time objects or strings)
        t_start = str(start_time).replace(":", "")
        t_stop = str(stop_time).replace(":", "")
        file_suffix = f"_{t_start}_{t_stop}"

    # Process each symbol independently
    for symbol in symbol_groups:
        tf_data = symbol_groups[symbol]
        logger.info(f"Processing Symbol: {symbol} (Timeframes: {list(tf_data.keys())})...")
        
        try:
            # Generate Signals
            df_with_signals = strategy.generate_signals(tf_data)
            
            # Save Debug CSV for Verification (Only if requested)
            if debug_mode:
                debug_path = output_dir / f"debug_{strategy_name}_{symbol}{file_suffix}_{timestamp_str}.csv"
                df_with_signals.to_csv(debug_path)
                logger.info(f"Saved full DataFrame with signals to {debug_path}")
            else:
                logger.info("Debug CSV generation skipped (Debug Mode disabled).")

            # Generate Trade Events
            events = SignalGenerator.generate_trade_events(df_with_signals, intraday_enabled, start_time, stop_time)
            
            # Create Unique Output File
            symbol_output_path = output_dir / f"signals_{strategy_name}_{symbol}{file_suffix}_{timestamp_str}.csv"
            
            if events:
                logger.info(f"  > Generated {len(events)} trades for {symbol}")
                MtQuantExporter.export_csv(events, str(symbol_output_path))
                
                # HTML Report (Same name as CSV but .html extension)
                symbol_html_path = output_dir / f"signals_{strategy_name}_{symbol}{file_suffix}_{timestamp_str}.html"
                generate_backtest_report(events, tf_data, str(symbol_html_path), initial_capital, instrument_type, lot_size, analysis_tf, analysis_lookback, losing_analysis)
            else:
                logger.info(f"  > No trades generated for {symbol}")
                
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            traceback.print_exc()
            continue


if __name__ == "__main__":
    main()
