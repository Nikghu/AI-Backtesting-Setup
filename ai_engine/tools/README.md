# ai_engine/tools — reusable analysis tool library

Rule for the /ai-backtest loop: **read this index FIRST. Reuse an existing
tool if it answers your question. Only create a new tool if nothing fits.**

All tools live in `ai_tools.py`. `BaseTool` owns the common machinery —
mode dispatch (`at` -> point, `start`/`end` -> series), the four token levers,
run-length compression, compact formatting helpers, and JSON errors. Each tool
is a subclass that inherits all of that.

A new tool is a `BaseTool` subclass that:
- declares `name`, `all_fields`, `step_fields`
- implements `_build` (load + annotate the per-bar frame), `_render_point`,
  `_fmt_field`, `_summary`, `_series_legend`
- is generic and parameterized (`symbol`, `tf`, `data` at minimum — never
  hardcode a symbol or session path)
- is registered in `TOOLS` + a CLI subcommand in `main()`
  (`python -m ai_engine.tools <name>`), and listed here

    from ai_engine.tools import Indicators
    Indicators().analyze(symbol="NIFTY", tf="5m", at="2022-01-03 09:45", indicators=["rsi:14"])

## Tool index

| Tool | Answers | Usage |
|---|---|---|
| `indicators` | Technical indicators (pandas_ta) at a bar or across a window: rsi, ema, sma, atr, adx, macd(hist), supertrend(dir). Series is columnar (per-bar). `--indicators` is `;`-separated | `python -m ai_engine.tools indicators --symbol NIFTY --tf 5m --at "2022-01-03 09:45" --indicators "rsi:14;adx:14;atr:14"` |
| `patterns` | Candlestick patterns from plain OHLC: doji, hammer, star, engulf, harami, inside (+bull/-bear). Series lists only bars where a pattern fired. `--patterns` is comma-separated | `python -m ai_engine.tools patterns --symbol NIFTY --tf 5m --start "2022-01-03 09:15" --end "2022-01-03 15:25"` |
| `statistics` | Math market behaviour: per-bar ret/zscore/mom/rng + SUMMARY of vol, skew, up%, avg range, lag-1 autocorr (ac1>0 trending, <0 mean-reverting). `--window` sets z/mom lookback | `python -m ai_engine.tools statistics --symbol NIFTY --tf 5m --start "2022-01-03 09:15" --end "2022-01-03 15:25" --summary-only` |
| `mtf` | Multi-timeframe trend confluence: trend per tf (EMA fast/slow) aligned onto the base tf (merge_asof, no lookahead) + CONFLUENCE score (-1..+1) and ALIGNED flag. `--htf` comma list, `--fast/--slow` | `python -m ai_engine.tools mtf --symbol NIFTY --tf 5m --at "2022-01-03 09:45" --htf "15m,1h"` |

Shared helper (not a tool): `_data.py` — `load_symbol()` / `resolve_data_file()`, used to load `.feather` data.
