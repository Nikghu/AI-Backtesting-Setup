# Session insights — new_supertrend_nifty

Goal: one sample NIFTY intraday strategy built on Supertrend (demo of the workflow).

- #001 SupertrendMtf — PASS. Supertrend direction on 5m, filtered by 15m
  Supertrend agreement (flat when they disagree). WR 54%, 37 trades, +39.5k on
  1 lot. Fewer, higher-conviction trades than the EMA version.
- Caveat: the bundled sample is only ~1 month (2026-05-25 → 06-22), so absolute
  numbers (incl. Sharpe) are inflated by the short window — a demo, not a
  validated edge. Re-run on a longer dataset before trusting it.
