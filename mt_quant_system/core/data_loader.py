import pandas as pd
import requests
from pathlib import Path
from typing import Dict, Tuple, List, Optional
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DataLoader:
    """
    Responsible for loading and preprocessing market data from Feather files.
    """

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"File not found: {self.file_path}")

    def _fetch_instrument_data(self) -> pd.DataFrame:
        """
        Fetches instrument data from valid source or cache.
        Checks for angel_tokens_{dd}_{mm}_{yy}.csv in the same directory.
        If present, loads it. If not, fetches from URL, cleans old cache, and saves new one.
        """
        today_str = datetime.now().strftime("%d_%m_%y")
        cache_file_name = f"angel_tokens_{today_str}.csv"
        current_dir = Path(__file__).parent
        cache_file_path = current_dir / cache_file_name

        if cache_file_path.exists():
            logger.info(f"Loading instrument data from cache: {cache_file_path}")
            # Specify low_memory=False to ensure mixed types are handled if any, 
            # though token should ideally be read as str.
            return pd.read_csv(cache_file_path, dtype={'token': str})

        logger.info("Fetching instrument data from Angel Broking...")
        INTRUMENT_URL = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
        
        # Clean up old files
        for old_file in current_dir.glob("angel_tokens_*.csv"):
             try:
                 old_file.unlink()
                 logger.info(f"Deleted old cache file: {old_file}")
             except Exception as e:
                 logger.warning(f"Failed to delete old cache file {old_file}: {e}")

        try:
            response = requests.get(INTRUMENT_URL)
            response.raise_for_status()
            data = response.json()
            df = pd.DataFrame(data)
            
            # Save to cache
            df.to_csv(cache_file_path, index=False)
            logger.info(f"Cached instrument data to {cache_file_path}")
            
            return df
        except Exception as e:
            logger.error(f"Failed to fetch instrument master: {e}")
            raise e

    def _resolve_token_names(self, df: pd.DataFrame, instrument_data: pd.DataFrame) -> pd.DataFrame:
        """
        Maps tokens to names using the provided instrument data.
        """
        # Only proceed if we have 'token' but missing 'name'
        if 'token' not in df.columns:
            return df
            
        logger.info("Resolving tokens to names using provided Instrument Master...")
        
        try:
            # Ensure token column in instrument_data is string for matching
            if 'token' in instrument_data.columns:
                instrument_data = instrument_data.copy() # Avoid SettingWithCopy warning if it's a slice
                instrument_data['token'] = instrument_data['token'].astype(str)
            
            # Filter for 'AMXIDX' (Indices) only
            if 'instrumenttype' in instrument_data.columns:
                original_count = len(instrument_data)
                instrument_data = instrument_data[instrument_data['instrumenttype'] == 'AMXIDX']
                logger.info(f"Filtered Instrument Master: {original_count} -> {len(instrument_data)} rows (AMXIDX only)")
            
            # map token -> name (using 'name' field from JSON as requested, which corresponds to symbol like 'NIFTY')
            # JSON structure example: {'token': '99926000', 'symbol': 'Nifty 50', 'name': 'NIFTY', ...}
            # We map 'token' to 'name' (e.g. 'NIFTY')
            
            full_token_map = dict(zip(instrument_data['token'], instrument_data['name']))
            
            # Map column. Convert tokens in df to string just in case they are read as int/columns
            df['token'] = df['token'].astype(str)
            unique_df_tokens = df['token'].unique()
            
            # Create a special list/map for tokens present in our data
            # And strictly filter for requested names ('NIFTY', 'BANKNIFTY')
            allowed_names = {'NIFTY', 'BANKNIFTY'}
            
            relevant_token_map = {
                t: full_token_map[t] 
                for t in unique_df_tokens 
                if t in full_token_map and full_token_map[t] in allowed_names
            }
            
            logger.info(f"Token to Name mapping generated (Filtered): {relevant_token_map}")
            
            df['name'] = df['token'].map(relevant_token_map)
            
            # Remove rows that didn't map to our allowed names
            original_len = len(df)
            df.dropna(subset=['name'], inplace=True)
            dropped = original_len - len(df)
            if dropped > 0:
                logger.info(f"Filtered out {dropped} rows not matching {allowed_names}")

            # Handle duplicates: If multiple tokens map to the same name (e.g. multiple expiry contracts),
            # we might have duplicate timestamps for the same (name, timeframe).
            # We keep the first one encountered (or could sort by open interest if available, but we lack that).
            # Sorting by existing index or just dropping duplicates.
            
            before_dedup = len(df)
            # drop_duplicates keys: name, timeframe, timestamp. 
            df.drop_duplicates(subset=['name', 'timeframe', 'timestamp'], keep='first', inplace=True)
            dedup_count = before_dedup - len(df)
            
            if dedup_count > 0:
                logger.warning(f"Removed {dedup_count} duplicate rows (same timestamp/name/timeframe).")
            
            # -----------------------------------------------------
            # Timeframe Mapping & formatting
            # -----------------------------------------------------
            TIMEFRAME_MAP = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1d": 86400}
            # Invert map to convert integer seconds (60) to labels ('1m')
            seconds_to_label = {v: k for k, v in TIMEFRAME_MAP.items()}
            
            # Map timeframe column
            df['timeframe'] = df['timeframe'].map(seconds_to_label)
            
            # Drop rows where timeframe is not in our map
            unmapped_tf = df['timeframe'].isnull().sum()
            if unmapped_tf > 0:
                logger.info(f"Dropping {unmapped_tf} rows with unsupported timeframes.")
                df.dropna(subset=['timeframe'], inplace=True)
            
            # Select and reorder specific columns as requested
            target_cols = ['timeframe', 'name', 'timestamp', 'open', 'high', 'low', 'close']
            
            # Ensure all exist (except maybe they are already there)
            available_cols = [c for c in target_cols if c in df.columns]
            if len(available_cols) < len(target_cols):
                missing = set(target_cols) - set(available_cols)
                logger.warning(f"Missing columns for strict format: {missing}")
            
            # Return strict subset/order
            df = df[available_cols]
                
            return df
            
        except Exception as e:
            logger.error(f"Failed to fetch or process instrument master: {e}")
            raise e

    def load_data(self) -> Dict[Tuple[str, str], pd.DataFrame]:
        """
        Loads the feather file and returns a dictionary of DataFrames,
        keyed by (Symbol, Timeframe).

        Returns:
            Dict[Tuple[str, str], pd.DataFrame]: Key is (symbol, timeframe), Value is DataFrame
        """
        logger.info(f"Loading data from {self.file_path}...")
        try:
            df = pd.read_feather(self.file_path)
        except Exception as e:
            logger.error(f"Failed to read feather file: {e}")
            raise e

        # Check if 'name' is missing but 'token' is present, and resolve if so
        if 'name' not in df.columns and 'token' in df.columns:
            instrument_data = self._fetch_instrument_data()
            df = self._resolve_token_names(df, instrument_data)

        # Validate required columns based on initial analysis
        required_columns = ['timeframe', 'name', 'timestamp', 'open', 'high', 'low', 'close']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            # Check for potential aliases if exact match fails, based on standard variations
            # For now, strictly enforcing what we saw in the sample, but this can be aliased later
            raise ValueError(f"Missing required columns: {missing_columns}")

        # Rename 'name' to 'symbol' for internal consistency if needed, or keep as is.
        # Let's standardize to 'symbol' internally for the strategy engine.
        df.rename(columns={'name': 'symbol'}, inplace=True)

        # Ensure timestamp is datetime
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'])

        # Group by Symbol and Timeframe
        grouped_data = {}
        grouped = df.groupby(['symbol', 'timeframe'])

        for (symbol, timeframe), group in grouped:
            # Sort by timestamp to ensure chronological order for backtesting
            # Reset index to have a clean integer index
            group_sorted = group.sort_values('timestamp').reset_index(drop=True)
            grouped_data[(symbol, timeframe)] = group_sorted
            logger.debug(f"Loaded {symbol} {timeframe}: {len(group_sorted)} rows")

        logger.info(f"Successfully loaded {len(grouped_data)} symbol-timeframe pairs.")
        return grouped_data


if __name__ == "__main__":
    # Test stub
    loader = DataLoader("f:/BackTesting_Setup/historical_data_sample.feather")
    data = loader.load_data()
    first_key = next(iter(data))
    print(f"Sample data for {first_key}:")
    print(data[first_key].head())
