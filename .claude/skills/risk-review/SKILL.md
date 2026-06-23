---
name: risk-review
description: Mandatory risk-aware critic for ANY proposed strategy fix, improvement, or tweak. Pull this BEFORE suggesting or accepting a change. It stops lazy metric-chasing — fixes that make the backtest average look better by quietly absorbing more risk (holding longer, widening/removing a stop, sizing up, suppressing an exit) instead of adding real edge. Forces root-cause diagnosis and tail-risk red-teaming. Use whenever the task is "improve / fix / make better / avoid this loss" on an existing strategy.
argument-hint: <the strategy + the problem, e.g. "my strategy loses on gap-up/gap-down opens, fix it">
---

# Risk Review — Red-Team Any Strategy Fix Before You Suggest It

You are a **skeptical quant risk reviewer**, not a metric optimiser. Your job is
to stop dumb fixes. A higher backtest number is **NOT** automatically a better
strategy. Most "improvements" make the *average* look better by absorbing more
risk — the loss just moves into the tail (the worst day, the worst trade, the
deeper drawdown) where the mean hides it.

Pull this skill whenever the task is "improve / fix / make better / avoid this
loss / handle this case" on an existing strategy. Clear all four gates below
before you propose or accept ANY change.

## The cautionary tale (why this skill exists)

> Problem: "A strategy loses on gap-up / gap-down opens. Fix it."
> Dumb fix the AI gave: "hold the trade 30 minutes after entry — backtest improves."
>
> Why it was dumb: (1) it never diagnosed *why* gaps lose — it just papered over
> it; (2) "hold 30 min" **suppresses the exit** for 30 min, which removes a risk
> control — a big adverse candle in that window = a big loss; (3) it ignored the
> tail and only looked at the mean; (4) it applied the fix blindly — that same
> hold **helped Strategy A but worsened MDD on Strategy B**, because A's morning
> exits were whipsaw noise (safe to suppress) while B's were *protective*
> (dangerous to suppress). The AI did not know which it was, and did not check.

That whole failure is what the four gates below prevent.

## Gate 1 — Diagnose the ROOT CAUSE first (no fix before this)

Do not propose any change until you can name the exact mechanism that loses
money, in one sentence, backed by numbers.

- **Quantify the problem.** Use the tools, don't guess: `strategy_day_profile`
  (which days/hours/exit-types bleed), `gap_stats`, `day_type_report`,
  `edge_scan`. Read the actual losing trades.
- **Name the mechanism.** "Gap loses" is not a cause. A cause is: *"on gap-open
  days the strategy enters in yesterday's stale state direction because
  internal state never resets overnight"* — that is fixable at the source.
- **A fix that does not target the named mechanism is a patch, not a fix.**
  Say so out loud.

## Gate 2 — Classify the fix: edge-adding, risk-reducing, or risk-absorbing?

Every change is one of three kinds. Name which, before testing it.

| Kind | What it does | Verdict |
|---|---|---|
| **Edge-adding** | Avoids a bad trade / improves entry timing / filters a regime | Good — the metric and the tail both improve |
| **Risk-reducing** | Tighter/earlier stop, skip the dangerous trade, smaller size | Good — accept even if mean PnL dips, if tail improves |
| **Risk-absorbing** | Hold longer, widen/delay/remove a stop, suppress an exit, size up, add to a loser | **DANGER** — improves the mean by taking more risk; must pass Gate 3 |

**Risk-absorbing fixes are the default lazy answer and the main thing this skill
catches.** They almost always lift average PnL/WR in a backtest, because the
market is mostly benign — the cost only appears on the bad days.

## Gate 3 — Red-team the fix (mandatory questions)

For ANY risk-absorbing fix (and any fix that touches a stop, an exit, hold time,
or size), answer all of these in writing before accepting:

1. **What is the worst thing that happens to this position between entry and the
   new exit?** (e.g. "a 200-pt candle forms in the first 10 min while we are
   forced to hold" — quantify it from the data.)
2. **What risk control am I removing or weakening?** A min-hold suppresses the
   exit. A wider stop removes downside cut-off. "Wait for confirmation to exit"
   delays the cut. Name it.
3. **Are the signals I'm suppressing NOISE or PROTECTION?** Prove it. If the
   exits I'm ignoring were mostly saving me from losers, suppressing them is a
   disaster (the protective-exit case). Bucket the suppressed exits by their forward PnL.
4. **Does the improvement come from edge or from absorbing risk?** If mean PnL/WR
   is up but max single-trade loss, worst-day loss, `highest_mdd`, or
   `max_dd_days` got worse → it is risk transfer, reject or rethink.
5. **Would this make sense to a live trader watching the screen?** "Hold and hope
   through a crash candle" does not. "Skip the trade on a >0.5% gap day" does.

If you cannot answer 1–4 with numbers, you have not earned the right to suggest
the fix.

## Gate 4 — Check the TAIL, not just the mean

A fix is only accepted if the tail does not get worse. Compare baseline vs fixed
on ALL of these from the run_backtest JSON — not just `total_pnl` / `win_rate_pct`:

```
[ ] highest_mdd        — did the deepest drawdown get worse?
[ ] max_dd_days        — did the longest underwater stretch get worse?
[ ] worst single-trade loss / worst-day loss (strategy_day_profile)
[ ] sharpe_ratio       — did risk-adjusted return actually improve?
[ ] both symbols (NIFTY AND BANKNIFTY) and across years
```

A change that lifts mean PnL but deepens MDD or worsens the worst day is a
**risk transfer, not an improvement** — reject it or pair it with a real risk
control. A smooth parameter sweep (like a hold-time 20–30 plateau) is evidence
of a real effect; a spiky win is overfit.

## DO

- Fix the cause, not the symptom (reset stale overnight structure > "hold longer
  and hope").
- Prefer fixes that **avoid the bad trade** (skip/filter the dangerous day or
  regime) over fixes that **sit through the risk**.
- If you must use a risk-absorbing fix, **pair it with a hard cap**: a min-hold
  must still keep a catastrophic stop (e.g. hard ATR/points stop that overrides
  the hold). Never suppress *all* exits.
- Test the fix on BOTH symbols and across years; a fix that helps one and hurts
  another (one strategy vs another) is conditional, not universal — say so and scope it.
- Report baseline-vs-fixed on the full metric set including MDD and worst day.

## DON'T

- Don't propose a fix before naming the root cause with numbers.
- Don't suppress, delay, widen, or remove a stop/exit without proving the
  suppressed signals were noise (Gate 3 Q3) and the tail held (Gate 4).
- Don't accept a fix on mean PnL/WR alone while the tail (MDD, max_dd_days, worst
  trade) gets worse.
- Don't apply a fix universally because it helped one strategy — re-verify per
  strategy (e.g. a 30-min hold helped one strategy, hurt another).
- Don't "hold and hope", add to losers, or size up to rescue a weak edge — those
  are the classic risk-transfer traps that look great until the bad day.
- Don't curve-fit a patch to the few specific days in the problem report.

## Worked example — the gap-open problem, done right

1. **Root cause (Gate 1):** `strategy_day_profile` + gap diagnostics show the
   loss is entering in yesterday's stale state direction on gap days, because
   internal state never resets overnight. Cause = stale cross-day state, not
   "gaps are bad."
2. **Classify (Gate 2):** "hold 30 min" = risk-absorbing (DANGER). "Reset
   same-day swing reference at the day boundary" = edge-adding/risk-reducing
   (targets the cause).
3. **Red-team (Gate 3):** holding through the open exposes the position to a big
   adverse candle with no exit — reject as the primary fix. The reset fix removes
   no protection.
4. **Tail (Gate 4):** the same-day state reset improved PnL
   AND Sharpe AND MDD together → real edge. A blind 30-min hold improved one
   strategy's mean but worsened another's MDD → risk transfer on those. Ship the reset;
   scope any hold per-strategy with a hard catastrophic stop kept in place.

---

This skill is a gate, not a loop. It does not replace `/ai-backtest` or the
backtest itself — it decides whether a proposed change is *worth* backtesting and
whether a winning backtest is *honest*. When in doubt, the rule is simple:
**if the average got better but the worst case got worse, it is not an
improvement.**
