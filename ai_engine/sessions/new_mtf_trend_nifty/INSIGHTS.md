# Session insights — new_mtf_trend_nifty

Goal: one simple intraday NIFTY strategy, positive PnL (demo of the workflow).

- #001 MtfTrendAlign — PASS. 5m has no bar-level edge (ac1~0), but requiring
  5m EMA(9/21) alignment WITH the 15m trend (and going flat when they disagree)
  filters chop and yields positive PnL. WR 57%, daily WR 70%, +72.5k on 1 lot.
- Caveat: the bundled sample is only ~1 month (2026-05-25 → 06-22), so the
  Sharpe (7.88) is inflated by the short window — treat absolute numbers as a
  demo, not a validated edge. Re-run on a longer dataset before trusting it.
