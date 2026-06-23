# /ai-backtest — prompt cheat sheet

General shape:

```
/ai-backtest <mode word> <strategy name if existing> : <what you want> , <criteria>
```

Criteria you can give (any, in plain English): win rate, trades per year,
total PnL, max drawdown, symbol (NIFTY/BANKNIFTY), timeframes, long/short only,
intraday window, number of strategies, max attempts.

## 1. NEW — create from scratch

```
/ai-backtest I want a multi-timeframe intraday strategy, win rate > 70%, 100-500 trades per year, NIFTY only
/ai-backtest create 2 strategies using price action + indicators, win rate > 65%, max drawdown < 50000
```

## 2. UPDATE — apply my exact change (no creativity)

```
/ai-backtest update MyStrategy: no entries before 09:45
/ai-backtest update MyStrategy: exit all positions by 15:00 instead of 15:15
```

## 3. IMPROVE — beat the current baseline

```
/ai-backtest improve MyStrategy
/ai-backtest improve MyStrategy: focus on reducing drawdown, keep win rate above 70%
```

## 4. TUNE — sweep one parameter

```
/ai-backtest tune stop_atr of MyStrategy
/ai-backtest tune adx_min of MyStrategy, try values 15 to 30
```

## 5. VARIANT — port / correlated sibling

```
/ai-backtest port MyStrategy to BANKNIFTY, lot size 35
/ai-backtest create a long-side sibling of MyStrategy with a different exit structure
```

## Tips

- Put YOUR strategies in `ai_engine/strategies/` before update/improve/tune.
- Always give a win rate AND a PnL/drawdown expectation — high win rate and
  high PnL pull in opposite directions on this data (see KNOWLEDGE.md).
- Add "max N attempts" to cap the loop (default 25).
- You can interrupt anytime — progress is saved in attempts_log.csv + INSIGHTS.md.
