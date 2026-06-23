# data/

Place your `.feather` OHLC files here. The GUI auto-discovers them; the CLI
auto-picks the first one if `--input` is omitted.

## Included sample

`sample_NIFTY.feather` — a small NIFTY sample (all timeframes: 1m, 3m, 5m, 15m,
1h, 1d) so you can run the engine out of the box. It is a slice of Indian index
OHLC for demo/testing only.

Run a backtest on it:

```
python -m ai_engine.run_backtest --probe                       # show data info
python -m ai_engine.run_backtest --strategy-file mt_quant_system/strategies/supertrend_strategy.py
```

Or the full app (GUI):

```
python -m mt_quant_system.main
```

## File format

Each `.feather` is a single DataFrame with one row per bar per timeframe:

| column | type | notes |
|---|---|---|
| `timeframe` | str | `1m`, `3m`, `5m`, `15m`, `1h`, `1d` |
| `name` | str | symbol, e.g. `NIFTY` (or supply `token` and let DataLoader resolve it) |
| `token` | str | optional; instrument token, resolved to `name` via the Angel Broking master |
| `timestamp` | datetime | bar time |
| `open` / `high` / `low` / `close` | float | OHLC |
| `volume` | int | 0 is fine for index data |

To use your own data, drop a feather with these columns into this folder. Large
data files you add here are git-ignored (only `sample_NIFTY.feather` is tracked).
