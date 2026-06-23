# ai_engine/templates — strategy templates

Reference templates for the /ai-backtest loop and for hand-written strategies.
Copy one, rename the class, edit the marked sections. Do NOT edit the
templates themselves.

| Template | Use when | Note |
|---|---|---|
| `vectorized_template.py` | signal is a direct condition (in position whenever condition true) | simplest, fastest |
| `trigger_latch_template.py` | entry/exit are separate condition TRIGGERS; position latched between them | conditions vectorized, small latch loop |
| `stateful_template.py` | exits depend on entry price (target / ATR stop / timeout / first-profitable-close) | tunable via `--params` JSON; structure of the first passing strategy |

Hard rules in both: talib only (no pandas_ta), `merge_asof(..., direction="backward")`
for higher TFs, `df["signal"] = df["signal"].shift(1)` as last line, signals 1/-1/0.
