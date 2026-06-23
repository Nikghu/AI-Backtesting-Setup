# AI Backtesting Setup

A Python backtesting framework for the Indian market. It loads multi-timeframe
OHLC data from `.feather` files, runs user-defined strategies that emit buy/sell
signals, and exports trade events as a **CSV + HTML report**.

It ships with a small NIFTY sample so you can run it right away, plus an
AI-assisted strategy generation loop for use inside Claude Code.

## Requirements

- **Python 3.9** (3.9.7 tested; 3.10 also works). `pandas-ta` does **not** work on
  Python 3.11+ — see [`requirements.txt`](requirements.txt) for details.

```
py -3.9 -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Quick start

A sample data file is included at `data/sample_NIFTY.feather` (NIFTY, all
timeframes). To confirm everything works:

```
# 1. Show what's in the data file (symbols, timeframes, date range)
python -m ai_engine.run_backtest --probe

# 2. Run a backtest on the included demo strategy (prints metrics as JSON)
python -m ai_engine.run_backtest --strategy-file mt_quant_system/strategies/ema_crossover.py
```

## Generating the CSV + HTML report

Add the `--report` flag. CSV and HTML are written to `--outdir` (default
`output/`, created automatically):

```
python -m ai_engine.run_backtest \
    --strategy-file mt_quant_system/strategies/ema_crossover.py \
    --report --outdir output
```

This produces, per symbol:

```
output/signals_<Strategy>_<Symbol>_<times>_<timestamp>.csv    # trade events
output/signals_<Strategy>_<Symbol>_<times>_<timestamp>.html   # full report
```

Open the `.html` file in any browser to see the trade log, equity curve, and
performance stats.

### Useful flags

| Flag | Purpose |
|---|---|
| `--strategy-file PATH` | strategy `.py` file to run |
| `--class-name NAME` | strategy class (auto-detected if omitted) |
| `--data PATH` | `.feather` file (auto-picked from `data/` if omitted) |
| `--symbols NIFTY,BANKNIFTY` | filter symbols |
| `--report` / `--outdir DIR` | also export CSV + HTML (default dir `output/`) |
| `--no-intraday` | keep positions overnight (default is intraday) |
| `--start-time` / `--stop-time` | intraday window (default `09:16` / `15:15`) |
| `--instrument Spot\|Future` | pricing mode (default `Future`) |
| `--capital` | starting capital (default `100000`) |
| `--params '{"fast": 9}'` | JSON kwargs passed to the strategy |

## GUI mode

A PyQt5 dialog to pick strategy, symbols, timeframes and date range. It also
generates the HTML report:

```
python -m mt_quant_system.main
```

## Adding your own strategy

Create a file in `mt_quant_system/strategies/`, subclass `BaseStrategy`, and
implement `generate_signals`. New files are auto-discovered — no registration
needed.

```python
from mt_quant_system.core.strategy import BaseStrategy
import pandas_ta as ta
import pandas as pd
from typing import Dict

class MyStrategy(BaseStrategy):
    def __init__(self, **kwargs):
        super().__init__("MyStrategy", params=kwargs)

    def generate_signals(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        df = data['5m'].copy()
        df['ema'] = ta.ema(df['close'], length=20)
        df['signal'] = 0
        df.loc[df['close'] > df['ema'], 'signal'] = 1     # long
        df.loc[df['close'] < df['ema'], 'signal'] = -1    # short
        df['signal'] = df['signal'].shift(1)              # avoid lookahead
        return df
```

Signal values: `1` = long, `-1` = short, `0` = flat. See
[`mt_quant_system/strategies/template_strategy.py`](mt_quant_system/strategies/template_strategy.py)
and `ema_crossover.py` for working examples.

## Using your own data

Drop a `.feather` file into `data/` with these columns: `timeframe`, `name`
(symbol), `timestamp`, `open`, `high`, `low`, `close` (and optionally `token`,
`volume`). See [`data/README.md`](data/README.md) for the full schema. Large
data files you add are git-ignored — only the sample is tracked.

## AI strategy generation (optional, Claude Code)

The `/ai-backtest` skill (`.claude/skills/ai-backtest/SKILL.md`) runs a
generate → backtest → evaluate loop until your criteria pass. Research helpers
live in `ai_engine/tools/` (see its `README.md`).

## Project layout

```
ai_engine/            headless runner (run_backtest.py), tools, templates
mt_quant_system/      core engine, GUI, strategies
  core/               data loader, signal generator, exporter, report generator
  strategies/         your strategies (+ template & demos)
data/                 .feather data (sample included)
output/               generated CSV/HTML (git-ignored)
```

## License

MIT — see [LICENSE](LICENSE).
