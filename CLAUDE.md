# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python backtesting framework for Indian Market. It loads multi-timeframe OHLC data from `.feather` files, runs user-defined strategies that emit buy/sell signals, and exports trade events as CSV + HTML reports consumed by the mtQuant platform.

## Running the Application

**GUI mode** (opens PyQt5 configuration dialog):
```
python -m mt_quant_system.main
```

**CLI mode** (no GUI, uses defaults):
```
python -m mt_quant_system.main --strategy StrategyClassName
python -m mt_quant_system.main --input data/my_data.feather --strategy StrategyClassName
```

Place `.feather` data files in the `data/` directory. The GUI auto-discovers them; CLI auto-picks the first one if `--input` is omitted.

## Installing Dependencies

```
pip install -r requirements.txt
```

Core deps: `pandas`, `numpy`, `PyQt5`, `pandas-ta`, `pyarrow`.

## Architecture & Data Flow

```
DataLoader → Dict[(symbol, tf), DataFrame]
    ↓  filter & group by symbol
strategy.generate_signals(Dict[tf, DataFrame]) → DataFrame with 'signal' column
    ↓
SignalGenerator.generate_trade_events() → List[{Trade No, Type, Date/Time}]
    ↓
MtQuantExporter.export_csv()   → output/signals_<strategy>_<symbol>_<ts>.csv
report_generator.generate_backtest_report() → output/signals_<...>.html
```

**DataLoader** (`core/data_loader.py`): reads `.feather` files; if the file contains `token` instead of `name` columns, it fetches the Angel Broking instrument master to resolve tokens to names (`NIFTY`, `BANKNIFTY`). Returns `Dict[(symbol, timeframe), DataFrame]` where each DataFrame has columns `[timeframe, symbol, timestamp, open, high, low, close]`.

**Strategy auto-discovery** (`strategies/__init__.py`): `load_strategies()` scans every module in `mt_quant_system/strategies/` and returns all classes that subclass `BaseStrategy`. A new strategy file is picked up automatically — no registration needed.

**SignalGenerator** (`core/signal_generator.py`): detects state changes in the `signal` column (`0→1` = Entry Long, `1→0` = Exit Long, `0→-1` = Entry Short, `-1→0` = Exit Short). In intraday mode, open positions are force-exited at `stop_time`.

**Report generation** requires `tf_data['1m']` to be present; trades are priced using 1-minute OHLC.

## Adding a New Strategy

1. Create `mt_quant_system/strategies/my_strategy.py`.
2. Subclass `BaseStrategy` and implement `generate_signals`:

```python
from mt_quant_system.core.strategy import BaseStrategy
import pandas_ta as ta
import pandas as pd
from typing import Dict

class MyStrategy(BaseStrategy):
    def __init__(self, **kwargs):
        super().__init__("MyStrategy", params=kwargs)

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        df = data['1m'].copy()          # use desired base timeframe
        # compute indicators with pandas_ta
        df['signal'] = 0
        # ... set 1 / -1 / 0 ...
        df['signal'] = df['signal'].shift(1)  # avoid lookahead bias
        return df
```

Signal semantics: `1` = Target Long, `-1` = Target Short, `0` = Flat.

## Key Conventions

- **Python environment**: use the project venv — `venv\Scripts\python.exe` (3.9.7, has pandas_ta + talib + all deps; the VS Code "Recommended" interpreter). Fallback: `py -3.9` (global 3.9, same packages). Plain `python` = 3.11 and has NO pandas_ta — old strategies fail there. Note: `pandas_ta 0.3.14b0` is no longer on PyPI for 3.9; if ever lost, copy the folder from `Python39\Lib\site-packages`.
- **Indicators**: prefer `talib` in new strategy files (works on both interpreters). `pandas_ta` works only under `py -3.9`.
- **Multi-timeframe merge**: use `pd.merge_asof(..., direction='backward')` to align higher-TF data onto the base TF without lookahead bias (see `template_strategy.py` for the commented example).
- **Signal shift**: always `df['signal'] = df['signal'].shift(1)` before returning so signals are based on completed candles.
- **Output directory**: `output/` is created automatically at runtime.
- **Timeframe labels**: `1m`, `3m`, `5m`, `15m`, `30m`, `60m`, `1d` (seconds-based integers in raw data are mapped by DataLoader).

## AI Backtest Engine (Claude Code workflow)

The `/ai-backtest` skill (`.claude/skills/ai-backtest/SKILL.md`) runs an
evaluator-optimizer loop inside Claude Code: generate a strategy → backtest →
evaluate against the user's criteria → iterate until pass.

Usage: `/ai-backtest multi-timeframe intraday strategy, win rate > 70%, price action + indicators`

Work modes (auto-detected from the prompt): NEW (create), UPDATE (apply a
requested change), IMPROVE (beat baseline), TUNE (sweep one parameter via
`--params` JSON), VARIANT (port/correlate an existing strategy). Cross-session
learnings live in `ai_engine/KNOWLEDGE.md`; reusable analysis tools in
`ai_engine/tools/` (see its README.md index).

The loop uses the headless CLI runner:

```
python -m ai_engine.run_backtest --probe                          # data info as JSON
python -m ai_engine.run_backtest --strategy-file path/to/strat.py # backtest, metrics as JSON
python -m ai_engine.run_backtest --strategy-file s.py --report --outdir <dir>  # + CSV & HTML report
```

Useful flags: `--symbols NIFTY,BANKNIFTY`, `--no-intraday`, `--start-time 09:16`,
`--stop-time 15:15`, `--instrument Spot|Future`, `--lot-size` (default per symbol: NIFTY=65, BANKNIFTY=35, else 75), `--capital 100000`,
`--class-name` (auto-detected if omitted). The JSON result is printed between
`===BACKTEST_RESULT===` and `===END_RESULT===` markers.

Session artifacts live in `ai_engine/sessions/<slug>/` (attempts/, passed/,
attempts_log.csv). Passing strategies get their CSV + HTML report in `passed/`.
