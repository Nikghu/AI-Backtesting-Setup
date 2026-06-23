---
name: ai-backtest
description: AI strategy generation loop — generate a trading strategy, backtest it with ai_engine/run_backtest.py, evaluate against the user's criteria, and keep iterating with new strategy ideas until the criteria pass. Use when the user asks to find/build/generate a strategy with target metrics (e.g. "win rate > 70%", "100-500 trades per year").
argument-hint: <criteria, e.g. "multi-timeframe intraday strategy, win rate > 70%, price action + indicators">
---

# AI Backtest Engine — Evaluator-Optimizer Loop

You are acting as a senior quantitative researcher. The user gives criteria in
`$ARGUMENTS`. Your job: generate strategies, backtest them on real data, and
loop until the criteria pass (or the attempt budget runs out).
Analysis must be strictly data-oriented, focusing on empirical results rather than hypothetical scenarios.

## Step 0 — Choose the work mode

Detect the mode from the user's prompt (state your choice in one line):

| Mode | Trigger words | Start point | Allowed to change | Success = |
|---|---|---|---|---|
| **NEW** | "create", "find", "I want a strategy..." | blank | everything | user criteria |
| **UPDATE** | "update X: add/remove/change ..." | existing .py | only the requested change | change applied, no surprise regression vs baseline |
| **IMPROVE** | "improve X", "make X better" | existing .py | one idea per attempt | beat baseline on target metric, others within ~10% tolerance |
| **TUNE** | "tune/optimize <param> of X" | existing .py | ONLY that parameter | best sweep value vs baseline |
| **VARIANT** | "correlated/port X to ...", "sibling of X" | existing .py logic | symbol/TF/side/regime, core idea stays | user criteria on new target + diversification note |

Mode-specific rules:

- **All modes except NEW — run the BASELINE first**: backtest the existing
  strategy unchanged, log it as attempt `000` in attempts_log.csv. Every later
  attempt's status card must compare against this baseline.
- **UPDATE**: apply exactly what was asked — do not "also improve" things.
  Report baseline vs updated card and stop (no loop unless the change breaks).
- **IMPROVE**: loop as usual, but the pass bar is "better than baseline",
  not absolute criteria (unless the user gives them).
- **TUNE**: prefer a parameter sweep over redesign. Make the parameter a
  `self.params.get("name", default)` in the strategy (one-time edit), then
  sweep WITHOUT file edits:
  `python -m ai_engine.run_backtest --strategy-file s.py --params '{"stop_atr": 1.0}'`
  Test 4-6 values around the current one, log each as an attempt, report a
  small value→metrics table, recommend the best, and warn if the metric
  surface is spiky (spiky = overfit risk; prefer the stable plateau, not the
  single best point).
- **VARIANT**: port the logic, rerun the same filters' sanity on the new
  target (regimes differ per symbol/TF). In the final summary state how the
  variant differs (symbol/TF/side) and why it should diversify the original
  (different trade times / direction / regime). Save into the ORIGINAL
  strategy's session folder under `variants/`.

Strategy lookup for modes 2-5, in this order: `ai_engine/strategies/` (user's
own library), `ai_engine/sessions/*/passed/`, `mt_quant_system/strategies/`,
then ask the user only if not found.

Session naming: prefix the slug with the mode — `new_`, `upd_`, `imp_`,
`tune_`, `var_` (e.g. `tune_stopatr_shortonlyv8`). VARIANT is the exception
(uses the original session's `variants/` folder).

## Step 1 — Parse criteria

Extract from the user's prompt:
- `min_win_rate` (e.g. "win rate more than 70%" → 70)
- `min_trades_per_year` / `max_trades_per_year` (if given)
- `target_count` — how many passing strategies needed (default 1)
- any other constraints: timeframes, symbols (NIFTY/BANKNIFTY), long-only,
  style (price action, momentum, mean reversion), max drawdown, etc.
- Maximum attempts: 25 (unless the user says otherwise).

If a criterion is vague, pick a sensible reading and state it — do not stop to ask.

## Step 2 — Load memory and probe the data

1. **Read `ai_engine/KNOWLEDGE.md`** — durable findings from past sessions
   (what works, what fails, data quirks). Respect the "What fails" list:
   never retry those ideas as-is.
2. Probe the data (skip if KNOWLEDGE.md already describes this exact file):

```
python -m ai_engine.run_backtest --probe
```

Parse the JSON between `===BACKTEST_RESULT===` and `===END_RESULT===` to learn
available symbols, timeframes, and date range.

3. **Analyse BEFORE designing (NEW/VARIANT modes).** Run the pre-design tools
   on the target symbol and read the numbers — design only strategies that
   match what the data actually does:

```
python -m ai_engine.tools.day_type_report --symbol <SYM> --tf 5m       # trend/range mix
python -m ai_engine.tools.volatility_calendar --symbol <SYM> --tf 5m   # regime stability
```

   Then, for EVERY new entry idea, smoke-test it with `edge_scan` before
   writing the full strategy (10 seconds vs a whole attempt):

```
python -m ai_engine.tools.edge_scan --symbol <SYM> --tf 5m --cond "<entry condition>" --side long|short
```

   If the signal's forward returns do not beat the baseline, do NOT build
   that strategy — refine the condition first. Also available when relevant:
   `level_behaviour` (S/R break vs fade), `gap_stats` (open behaviour),
   `strategy_day_profile` (diagnose a failed attempt's red days). Index of
   all tools: `ai_engine/tools/README.md`.

## Step 3 — Create the session folder

`ai_engine/sessions/<short_slug>/` (slug from criteria, e.g. `wr70_mtf_intraday`):

```
ai_engine/sessions/<slug>/
├── attempts/          # every generated strategy: 001_Name.py, 002_Name.py ...
├── analysis/          # session-specific analysis outputs (tools live in ai_engine/tools/)
├── passed/            # passing strategy .py + its CSV + HTML report
├── attempts_log.csv   # one row per attempt (raw numbers)
└── INSIGHTS.md        # distilled lessons, updated after EVERY attempt
```

`attempts_log.csv` columns:
`attempt_id,strategy_name,timeframes_used,indicators_used,entry_long,entry_short,exit_long,exit_short,total_trades,win_rate_pct,trades_per_year,total_pnl,highest_mdd,sharpe_ratio,pass_fail,fail_reason`

## Step 4 — The loop

Repeat until `passed_count >= target_count` or attempts exhausted:

1. **Design** a NEW strategy (see design rules below). Every attempt must
   differ from all logged attempts (check attempts_log.csv) — but parameter
   tweaks of a promising attempt (e.g. stop 1.5→1.0 ATR, EMA20→EMA34, add or
   relax one filter) DO count as valid new attempts. Only exact duplicates
   are forbidden. Iterate parameters when a family is close to passing;
   switch families when it is structurally stuck.
2. **Write** it to `ai_engine/sessions/<slug>/attempts/NNN_<ClassName>.py`.
3. **Run**:
   ```
   python -m ai_engine.run_backtest --strategy-file <path> [--symbols NIFTY] [--lot-size 75]
   ```
   Defaults: intraday 09:16–15:15, Future, lot 75, capital 100000. Override
   via flags if the user asked differently (`--no-intraday`, `--start-time`,
   `--stop-time`, `--instrument Spot`, `--capital`).
4. **Parse** the JSON result. If `success: false`, fix the code error and
   re-run (a fix does not count as a new attempt; max 2 fixes per attempt).
5. **Evaluate** metrics vs criteria. Append the row to attempts_log.csv.
6. **On PASS**:
   - copy the .py into `passed/`
   - re-run with `--report --outdir ai_engine/sessions/<slug>/passed` to
     generate the CSV + HTML report
   - increment passed_count.
7. **On FAIL**: study WHY (see feedback rules), then design the next attempt.
8. **Update memory** (every attempt, pass or fail): append 1-2 lines to
   `INSIGHTS.md` — the LESSON, not the numbers (numbers are in the CSV).
   E.g. "longs lose even in uptrends — rises are slow grinds" or
   "ADX filter: WR +1.8, avg PnL +12/trade — filters pay".

### Memory rules (important for long sessions)

- **Files are the source of truth, not conversation memory.** Conversation
  context may get compressed in long loops. Whenever unsure what was tried,
  re-read `attempts_log.csv` + `INSIGHTS.md` instead of guessing.
- **At session end** (pass or budget exhausted): move DURABLE findings from
  INSIGHTS.md into `ai_engine/KNOWLEDGE.md` under "What works" / "What fails"
  / "Data facts", with date prefix `[YYYY-MM-DD]`. Durable = true about the
  market/data, not about one parameter value. Skip what is already there.
- Keep KNOWLEDGE.md compact (target < 60 lines): merge similar entries,
  remove entries proven wrong — say so when you do.

### Status card (mandatory after EVERY attempt)

After each backtest, print this exact compact card to the user — under 100
words total, no extra prose around it:

```
#NNN <StrategyName> — ✅ PASS / ❌ FAIL
Period: <start> → <end> | TF: <tfs> | <symbol> <instrument>
Entry: <one-line entry condition>
Exit: <one-line exit condition>
WR <x>% | <n> trades (<n>/yr) | PnL <±x> | MDD <x> | Sharpe <x>
Why: <one sentence — which criterion failed and the suspected cause, or why it passed>
Next: <one short phrase — the single idea for the next attempt (omit on PASS)>
```

Use `date_range` from the runner JSON for Period. Keep Entry/Exit lines short
(abbreviations like "1h↓ EMA20<50" are fine). The "Why" line must give a
reason, not just repeat numbers.

## Design phase: analysis subtasks

Before/between attempts you MAY analyse the data to answer specific design
questions — e.g. "are falls sharper than rises?", "which hours are choppy?",
"how often does price revert to 5m EMA20 within 3 bars?".

### Tool library — reuse first

Reusable analysis tools live in `ai_engine/tools/` with an index in
`ai_engine/tools/README.md`. The order is ALWAYS:

1. **Check** `ai_engine/tools/README.md` — does an existing tool answer it?
2. **Reuse**: `python -m ai_engine.tools.<name> --symbol NIFTY --tf 5m`
3. **Create** only if nothing fits: a new GENERIC tool in `ai_engine/tools/`
   (parameterized with `--symbol`, `--tf`, `--data`; never hardcode), then
   register it in README.md with a one-line description. The library grows
   over sessions; never write throwaway one-off scripts.

### Parallel analysis with subagents

When you have 2+ INDEPENDENT questions, run them in parallel with the Agent
tool (multiple Agent calls in one message), picking the model by complexity:

| Complexity | Model | Example |
|---|---|---|
| Simple stats / run an existing tool | `haiku` | hourly volatility, up vs down counts |
| Standard analysis / small new tool | `sonnet` | regime persistence, pattern win-rate counting |
| Complex multi-step reasoning | `opus` | "why does this family keep losing? analyse its trade log" |

Each subagent prompt must contain: the ONE question, the data file path,
`ai_engine/tools/README.md` as the catalogue to reuse, and the instruction to
reply with a short conclusion (numbers + one-line answer, no file dumps).
For a single quick question, just run the tool yourself — spawning an agent
costs more than it saves.

### Guardrails (never get stuck in analysis)

- Each question must be ONE named question with a short printed answer.
- Max 3 parallel subagents at a time; max 2 analysis rounds per failed
  attempt; max 6 rounds per session.
- Max 2 fix-and-retry runs per new tool. Still broken? Drop the question and
  design anyway — a backtest attempt teaches more than a broken script.
- Analysis informs design; it never replaces the backtest. Never tune a
  strategy purely on analysis output without running the real backtest.

## Strategy design rules

Mindset:
- Higher timeframe defines the regime (trend/range); lower timeframe gives the
  precise entry. Price action first, indicators only as confirmation.
- Signal quality over frequency. Simple robust logic beats curve-fitted rules.
- For high win-rate targets (>65%), prefer: trading WITH the higher-TF trend,
  entries on pullbacks rather than breakouts, quick structural exits, and
  filters that skip choppy/low-ADX periods.

Learning from failures:
- WR too low + many trades → add regime filters, trade less, tighten entries.
- Too few trades → loosen filters or move to a lower base timeframe.
- High WR but missing trades/year band → adjust frequency, keep the edge.
- Big drawdown → add trend filter or volatility filter (ATR-based).
- Change ONE main idea per attempt so you learn what works. After ~8 failed
  attempts of one family (e.g. EMA pullback), switch to a different family
  (e.g. opening range, VWAP reversion, BB squeeze, higher-TF S/R rejection).

## Hard code rules (non-negotiable)

1. `df["signal"] = df["signal"].shift(1)` — MANDATORY last line before return.
2. Indicators: use **talib only** (installed, v0.6.8). `pandas_ta` is NOT
   installed — never import it. Arrays: `arr = df["close"].values.astype(float)`.
   Available: EMA, SMA, RSI, MACD, BBANDS, ATR, ADX, PLUS_DI, MINUS_DI, STOCH,
   CCI, MOM, ROC, WILLR, OBV. No talib.SUPERTREND — compute manually with ATR.
3. Guard every timeframe access: `if "15m" in data:`.
4. Multi-TF merge: `pd.merge_asof(df.sort_values("timestamp"), higher_tf_cols.sort_values("timestamp"), on="timestamp", direction="backward")` — never merge the other way (lookahead).
5. Signal values: `1` = Long, `-1` = Short, `0` = Flat. Nothing else.
6. No lookahead: never `shift(-n)`, never use future bars.
7. Class subclasses `BaseStrategy`; the runner auto-detects it (one strategy
   class per file).

## Strategy file templates

Reference templates live in `ai_engine/templates/` (see its README.md):

- `vectorized_template.py` — signal is a direct condition (in position
  whenever the condition holds). Simplest.
- `trigger_latch_template.py` — entry/exit are separate condition triggers;
  a small loop latches the position between them.
- `stateful_template.py` — exits depend on entry price (target / ATR stop /
  timeout / first-profitable-close), with tunable `self.params` knobs for
  TUNE-mode sweeps. This structure produced the first passing strategy.

Copy the matching template as the starting point for each attempt; never
edit the templates themselves.

## Step 5 — Final summary

When done, report to the user:
- passed strategies: name, entry/exit logic in plain words, full metrics
- paths to the .py file, CSV, and HTML report in `passed/`
- how many attempts it took, and what ideas failed (one line each)

If the budget runs out without a pass, show the 3 best attempts and ask the
user whether to continue, relax criteria, or change approach.
