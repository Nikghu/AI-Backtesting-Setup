"""
ai_tools — compact, token-cheap analysis tools for strategy research.

Structure (OOP with inheritance):
  BaseTool          common machinery, inherited by every tool:
                      - mode dispatch (`at` -> point, `start`/`end` -> series,
                        neither -> last bar)
                      - the four token levers (fields, detail, max_events,
                        summary_only)
                      - run-length compression of step (piecewise-constant) fields
                      - compact formatting helpers + JSON errors (never raised)
  Indicators        one tool = one subclass; implements only its own logic.

Each tool reports FACTS, never decides trades.

    from ai_engine.tools import Indicators
    Indicators().analyze(symbol="NIFTY", tf="5m", at="2022-01-03 09:45", indicators=["rsi:14"])
"""
import json
import argparse

import numpy as np
import pandas as pd

from ai_engine.tools._data import load_symbol


# ===========================================================================
# base class — inherited by every tool
# ===========================================================================

class BaseTool:
    name = "TOOL"          # header tag, e.g. "MSTRUCT"
    all_fields = []        # every column a caller may request in series mode
    step_fields = []       # subset that is piecewise-constant -> run-length groupable

    def __init__(self, data=None):
        self.data_path = data

    # ---- compact formatting helpers (inherited) ----

    @staticmethod
    def fmt_num(x):
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return "-"
        return f"{x:g}"

    @staticmethod
    def fmt_pct(x):
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return "-"
        return f"{x:.2f}"

    @staticmethod
    def t_full(ts):
        return pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def t_hhmm(ts):
        return pd.Timestamp(ts).strftime("%H%M")

    @staticmethod
    def t_rel(ts, ref):
        """HHMM if same day as ref, else MMDD-HHMM (prior-day levels stay unambiguous)."""
        ts = pd.Timestamp(ts)
        if ts.date() == pd.Timestamp(ref).date():
            return ts.strftime("%H%M")
        return ts.strftime("%m%d-%H%M")

    # ---- public API ----

    def analyze(self, symbol, tf="5m", at=None, start=None, end=None,
                fields=None, detail="changes", max_events=None,
                summary_only=False, **build_kw):
        """Returns a compact report (str). Errors return JSON (str), never raised."""
        try:
            df, err = self._build(symbol, tf, **build_kw)
            if err:
                return self._error("bad_request", err)
            if at is not None:
                return self._render_point(df, symbol, tf, pd.to_datetime(at))
            if start is not None or end is not None:
                s = pd.to_datetime(start) if start else df["timestamp"].iloc[0]
                e = pd.to_datetime(end) if end else df["timestamp"].iloc[-1]
                return self._render_series(df, symbol, tf, s, e,
                                           fields, detail, max_events, summary_only)
            # stingy default: point at the last bar
            return self._render_point(df, symbol, tf, df["timestamp"].iloc[-1])
        except Exception as exc:
            return self._error("internal", f"{type(exc).__name__}: {exc}")

    # ---- shared helpers ----

    def _load(self, symbol, tf):
        """Load one symbol/timeframe, sorted. Returns (df, err)."""
        data = load_symbol(symbol, self.data_path)
        if tf not in data:
            return None, f"tf '{tf}' not in data; have {sorted(data)}"
        df = data[tf].copy().sort_values("timestamp").reset_index(drop=True)
        return df, None

    @staticmethod
    def _error(code, message):
        return json.dumps({"error": code, "message": message})

    def _header(self, symbol, tf, span):
        return f"=== {self.name} {symbol} {tf} {span} ==="

    def _render_series(self, df, symbol, tf, start, end,
                       fields, detail, max_events, summary_only):
        sub = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy()
        if sub.empty:
            return self._error("no_data", f"no bars in {start}..{end}")

        single_day = sub["timestamp"].dt.date.nunique() == 1
        tfmt = self.t_hhmm if single_day else (lambda ts: pd.Timestamp(ts).strftime("%m%d-%H%M"))
        span = (f"{tfmt(sub['timestamp'].iloc[0])}.."
                f"{tfmt(sub['timestamp'].iloc[-1])} {len(sub)}bars")
        head = self._header(symbol, tf, span)
        summ = self._summary(sub)
        if summary_only:
            return "\n".join([head, summ])

        fields = [f for f in (fields or self.all_fields) if f in self.all_fields] or self.all_fields
        step_keys = [f for f in fields if f in self.step_fields]
        disp = self._series_select(sub)   # tools may show only some rows (e.g. event bars)

        rows = []
        # run-length only when the tool has step fields AND the caller wants it;
        # otherwise (e.g. continuous indicators) emit one columnar row per bar.
        if detail != "changes" or not step_keys:
            cols = "TIME|" + "|".join(f.upper() for f in fields)
            for _, r in disp.iterrows():
                rows.append(tfmt(r["timestamp"]) + "|" +
                            "|".join(self._fmt_field(r, f) for f in fields))
        else:
            key = disp[step_keys].astype(str).agg("|".join, axis=1)
            grp = (key != key.shift()).cumsum()
            cols = "FROM|TO|" + "|".join(f.upper() for f in fields)
            for _, g in disp.groupby(grp):
                first = g.iloc[0]
                cells = [tfmt(first["timestamp"]), tfmt(g.iloc[-1]["timestamp"])]
                cells += [self._fmt_field(first, f) for f in fields]
                rows.append("|".join(cells))

        if max_events and len(rows) > max_events:
            rows = rows[-max_events:]
        return "\n".join([head, self._series_legend(cols)] + rows + [summ])

    def _series_select(self, sub):
        """Rows to display in series mode (summary still uses the full window).
        Default: every bar. Event tools (e.g. patterns) override to filter."""
        return sub

    # ---- abstract: each tool implements these ----

    def _build(self, symbol, tf, **build_kw):
        """Return (per-bar DataFrame with a 'timestamp' column, err_str_or_None)."""
        raise NotImplementedError

    def _render_point(self, df, symbol, tf, at):
        """Return the compact block for the single bar at/before `at`."""
        raise NotImplementedError

    def _fmt_field(self, row, field):
        """Format one field's value for a series row."""
        raise NotImplementedError

    def _summary(self, sub):
        """Return the one-line SUMMARY for a series window."""
        raise NotImplementedError

    def _series_legend(self, cols):
        """Return the Legend line for series output (includes `cols=...`)."""
        raise NotImplementedError


# ===========================================================================
# tool: indicators
# ===========================================================================

class Indicators(BaseTool):
    """Technical indicators (pandas_ta) at a bar or across a window.

    `indicators` is a spec list, e.g.
        ["rsi:14", "ema:20", "atr:14", "adx:14", "macd:12,26,9", "supertrend:10,3"]
    Values change every bar, so series mode is columnar (one row per bar).
    Volume-based indicators (vwap/vwma) are omitted — the index feather data
    carries no volume.
    """
    name = "IND"
    step_fields = []                                  # continuous -> always columnar
    DEFAULT = ["rsi:14", "adx:14", "atr:14", "ema:20"]

    def _build(self, symbol, tf, indicators=None):
        df, err = self._load(symbol, tf)
        if err:
            return None, err
        cols = []
        for spec in (indicators or self.DEFAULT):
            cols.extend(self._compute(df, spec))
        self.all_fields = ["close"] + cols            # per-call: drives field filter
        return df, None

    @staticmethod
    def _compute(df, spec):
        """Add one indicator's column(s) to df; return the produced column names."""
        import pandas_ta as ta                        # lazy: only Indicators needs it

        name, _, raw = spec.partition(":")
        name = name.strip().lower()
        ps = [p for p in raw.split(",") if p != ""]
        c, h, l = df["close"], df["high"], df["low"]

        if name in ("ema", "sma", "rsi", "atr", "adx"):
            p = int(ps[0]) if ps else 14
            col = f"{name}_{p}"
            if name == "ema":
                df[col] = ta.ema(c, length=p)
            elif name == "sma":
                df[col] = ta.sma(c, length=p)
            elif name == "rsi":
                df[col] = ta.rsi(c, length=p)
            elif name == "atr":
                df[col] = ta.atr(h, l, c, length=p)
            elif name == "adx":
                df[col] = ta.adx(h, l, c, length=p)[f"ADX_{p}"]
            return [col]

        if name == "macd":
            f, s, sig = (int(ps[0]), int(ps[1]), int(ps[2])) if len(ps) == 3 else (12, 26, 9)
            col = f"macdh_{f}_{s}_{sig}"
            df[col] = ta.macd(c, fast=f, slow=s, signal=sig)[f"MACDh_{f}_{s}_{sig}"]
            return [col]                              # histogram = line - signal (cross state)

        if name in ("supertrend", "st"):
            length = int(ps[0]) if ps else 10
            mult = float(ps[1]) if len(ps) > 1 else 3.0
            st = ta.supertrend(h, l, c, length=length, multiplier=mult)
            col = f"st_dir_{length}_{int(mult)}"
            df[col] = st[f"SUPERTd_{length}_{mult}"]   # +1 up / -1 down
            return [col]

        raise ValueError(f"unknown indicator '{name}'")

    def _render_point(self, df, symbol, tf, at):
        sub = df[df["timestamp"] <= at]
        if sub.empty:
            return self._error("no_data", f"no bars at/before {at}")
        row = sub.iloc[-1]
        parts = " ".join(f"{f.upper()}={self._fmt_field(row, f)}" for f in self.all_fields)
        return "\n".join([
            self._header(symbol, tf, f"@{self.t_full(row['timestamp'])}"),
            "Legend: indicator values at the bar (NaN=-)",
            parts,
        ])

    def _fmt_field(self, row, field):
        v = row[field]
        if field.startswith(("rsi", "adx")):
            return "-" if pd.isna(v) else f"{v:.1f}"
        if field.startswith("st_dir"):
            return "-" if pd.isna(v) else f"{int(v):+d}"
        if field.startswith(("atr", "macdh")):
            return self.fmt_pct(v)
        return self.fmt_num(v)                         # close, ema, sma, supertrend value

    def _summary(self, sub):
        out = [f"n={len(sub)}"]
        for f in self.all_fields:
            if f == "close":
                continue
            s = sub[f].dropna()
            out.append(f"{f}[na]" if s.empty
                       else f"{f}[avg={s.mean():.1f} min={s.min():.1f} max={s.max():.1f}]")
        return "SUMMARY " + " ".join(out)

    def _series_legend(self, cols):
        return f"Legend: cols={cols}"


# ===========================================================================
# tool: patterns
# ===========================================================================

class Patterns(BaseTool):
    """Candlestick patterns from plain OHLC (no talib / pandas_ta).

    Detects: doji, hammer (+), star/shooting-star (-), engulf (+/-),
    harami (+/-), inside. Token suffix +bull / -bear; doji & inside neutral.
    Patterns are sparse, so series mode lists only the bars where one fired;
    the SUMMARY counts over the whole window.
    """
    name = "PAT"
    all_fields = ["pat"]
    step_fields = []
    KNOWN = ["doji", "hammer", "star", "engulf", "harami", "inside"]

    def _build(self, symbol, tf, patterns=None):
        df, err = self._load(symbol, tf)
        if err:
            return None, err
        pats = patterns or self.KNOWN
        bad = [p for p in pats if p not in self.KNOWN]
        if bad:
            return None, f"unknown pattern(s) {bad}; known: {self.KNOWN}"
        self._detect(df, pats)
        return df, None

    @staticmethod
    def _detect(df, pats):
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        body = (c - o).abs()
        rng = (h - l).replace(0, np.nan)
        upper = h - np.maximum(o, c)
        lower = np.minimum(o, c) - l
        green, red = c > o, c < o
        po, pc, ph, pl = o.shift(), c.shift(), h.shift(), l.shift()
        pbody = (pc - po).abs()
        pgreen, pred = pc > po, pc < po

        toks = {}
        if "doji" in pats:
            toks["doji"] = np.where(body <= 0.1 * rng, "doji", "")
        if "hammer" in pats:
            m = (lower >= 2 * body) & (upper <= 0.3 * rng) & (body > 0)
            toks["hammer"] = np.where(m, "hammer+", "")
        if "star" in pats:
            m = (upper >= 2 * body) & (lower <= 0.3 * rng) & (body > 0)
            toks["star"] = np.where(m, "star-", "")
        if "engulf" in pats:
            bull = pred & green & (o <= pc) & (c >= po)
            bear = pgreen & red & (o >= pc) & (c <= po)
            toks["engulf"] = np.where(bull, "engulf+", np.where(bear, "engulf-", ""))
        if "harami" in pats:
            inside_body = (np.maximum(o, c) <= np.maximum(po, pc)) & (np.minimum(o, c) >= np.minimum(po, pc))
            bull = pred & green & inside_body & (pbody > body)
            bear = pgreen & red & inside_body & (pbody > body)
            toks["harami"] = np.where(bull, "harami+", np.where(bear, "harami-", ""))
        if "inside" in pats:
            toks["inside"] = np.where((h < ph) & (l > pl), "inside", "")

        pat = np.array([""] * len(df), dtype=object)
        for s in toks.values():
            s = np.asarray(s, dtype=object)
            both = (pat != "") & (s != "")
            pat = np.where(both, pat + "," + s, pat + s)
        df["pat"] = pat
        return df

    def _series_select(self, sub):
        return sub[sub["pat"] != ""]

    def _render_point(self, df, symbol, tf, at):
        sub = df[df["timestamp"] <= at]
        if sub.empty:
            return self._error("no_data", f"no bars at/before {at}")
        row = sub.iloc[-1]
        return "\n".join([
            self._header(symbol, tf, f"@{self.t_full(row['timestamp'])}"),
            "Legend: patterns at the bar; +bull -bear (doji/inside neutral)",
            f"PAT={row['pat'] or 'none'} CLOSE={self.fmt_num(row['close'])}",
        ])

    def _fmt_field(self, row, field):
        return row["pat"] or "-"

    def _summary(self, sub):
        from collections import Counter
        ctr = Counter()
        for p in sub["pat"]:
            if p:
                ctr.update(p.split(","))
        fired = int((sub["pat"] != "").sum())
        parts = " ".join(f"{k}={v}" for k, v in sorted(ctr.items()))
        return f"SUMMARY bars={len(sub)} fired={fired} {parts}".rstrip()

    def _series_legend(self, cols):
        return f"Legend: cols={cols} (+bull -bear); patterns: {','.join(self.KNOWN)}"


# ===========================================================================
# tool: statistics
# ===========================================================================

class Statistics(BaseTool):
    """Mathematical market behaviour for one symbol/timeframe.

    Per-bar fields: ret (bar % change), zscore (close z over `window`),
    mom (`window`-bar % change), rng (bar range %). Series is columnar.
    The SUMMARY gives the distribution over the window: mean, volatility
    (ret std), skew, up%, avg range, and lag-1 autocorrelation (ac1 > 0 =>
    momentum/trending, ac1 < 0 => mean-reverting).

    (Cross-symbol correlation is not in v1 — it needs two symbols and does not
    fit the single-symbol point/series shape.)
    """
    name = "STAT"
    all_fields = ["ret", "zscore", "mom", "rng"]
    step_fields = []

    def _build(self, symbol, tf, window=20):
        df, err = self._load(symbol, tf)
        if err:
            return None, err
        c = df["close"]
        df["ret"] = c.pct_change() * 100
        roll = c.rolling(window)
        df["zscore"] = (c - roll.mean()) / roll.std()
        df["mom"] = (c / c.shift(window) - 1) * 100
        df["rng"] = (df["high"] - df["low"]) / c * 100
        self._window = window
        return df, None

    def _render_point(self, df, symbol, tf, at):
        sub = df[df["timestamp"] <= at]
        if sub.empty:
            return self._error("no_data", f"no bars at/before {at}")
        row = sub.iloc[-1]
        return "\n".join([
            self._header(symbol, tf, f"@{self.t_full(row['timestamp'])}"),
            f"Legend: ret=bar%chg zscore=close z({self._window}) "
            f"mom={self._window}-bar%chg rng=bar range%",
            f"RET={self.fmt_pct(row['ret'])} ZSCORE={self.fmt_pct(row['zscore'])} "
            f"MOM={self.fmt_pct(row['mom'])} RNG={self.fmt_pct(row['rng'])} "
            f"CLOSE={self.fmt_num(row['close'])}",
        ])

    def _fmt_field(self, row, field):
        return self.fmt_pct(row[field])

    def _summary(self, sub):
        r = sub["ret"].dropna()
        if r.empty:
            return f"SUMMARY n={len(sub)} (no returns)"
        ac1 = r.autocorr(1) if len(r) > 2 else float("nan")
        return (f"SUMMARY n={len(sub)} "
                f"ret[avg={r.mean():.3f} vol={r.std():.3f} skew={r.skew():.2f}] "
                f"up%={(r > 0).mean() * 100:.1f} rng_avg={sub['rng'].mean():.2f} "
                f"ac1={ac1:.2f}")

    def _series_legend(self, cols):
        return f"Legend: cols={cols}"


# ===========================================================================
# tool: mtf (multi-timeframe context)
# ===========================================================================

class MTF(BaseTool):
    """Align trend across timeframes and score their agreement.

    For the base tf and each higher tf, trend = sign(EMA(fast) - EMA(slow)),
    +1 up / -1 down. Higher-tf trends are merged onto the base bars with
    merge_asof(backward) so there is no lookahead. CONFLUENCE is the mean of
    the per-tf signs (-1 all-down .. +1 all-up; 0 = mixed). Trends are
    step-wise, so series mode uses run-length compression.
    """
    name = "MTF"
    HTF_DEFAULT = ["15m", "1h"]

    def _build(self, symbol, tf, htf=None, fast=20, slow=50):
        base, err = self._load(symbol, tf)
        if err:
            return None, err
        base[f"trend_{tf}"] = self._trend(base, fast, slow)
        cols = [f"trend_{tf}"]
        for h in (htf or self.HTF_DEFAULT):
            hd, herr = self._load(symbol, h)
            if herr:
                return None, herr
            hd[f"trend_{h}"] = self._trend(hd, fast, slow)
            base = pd.merge_asof(
                base.sort_values("timestamp"),
                hd[["timestamp", f"trend_{h}"]].sort_values("timestamp"),
                on="timestamp", direction="backward",
            )
            base[f"trend_{h}"] = base[f"trend_{h}"].fillna(0).astype(int)
            cols.append(f"trend_{h}")
        base["confluence"] = base[cols].mean(axis=1)
        self._trend_cols = cols
        self.all_fields = cols + ["confluence"]
        self.step_fields = cols                      # confluence is constant within a group
        return base, None

    @staticmethod
    def _trend(df, fast, slow):
        c = df["close"]
        ef = c.ewm(span=fast, adjust=False).mean()
        es = c.ewm(span=slow, adjust=False).mean()
        return np.sign(ef - es).fillna(0).astype(int)

    def _render_point(self, df, symbol, tf, at):
        sub = df[df["timestamp"] <= at]
        if sub.empty:
            return self._error("no_data", f"no bars at/before {at}")
        row = sub.iloc[-1]
        trends = [int(row[c]) for c in self._trend_cols]
        aligned = "yes" if all(t == trends[0] and t != 0 for t in trends) else "no"
        parts = " ".join(f"{c.upper()}={self._fmt_field(row, c)}" for c in self._trend_cols)
        return "\n".join([
            self._header(symbol, tf, f"@{self.t_full(row['timestamp'])}"),
            "Legend: trend per tf (+up/-down); confluence -1..+1 (agreement)",
            f"{parts} CONFLUENCE={self.fmt_pct(row['confluence'])} ALIGNED={aligned}",
        ])

    def _fmt_field(self, row, field):
        if field == "confluence":
            return self.fmt_pct(row[field])
        v = int(row[field])
        return "+" if v > 0 else ("-" if v < 0 else "0")

    def _summary(self, sub):
        cols = self._trend_cols
        up = int((sub[cols] == 1).all(axis=1).sum())
        dn = int((sub[cols] == -1).all(axis=1).sum())
        return (f"SUMMARY bars={len(sub)} up_aligned={up} dn_aligned={dn} "
                f"mixed={len(sub) - up - dn}")

    def _series_legend(self, cols):
        return f"Legend: trend +/-/0; confluence -1..+1; cols={cols}"


# ===========================================================================
# CLI:  python -m ai_engine.tools <tool> [args]
# ===========================================================================

TOOLS = {"indicators": Indicators,
         "patterns": Patterns, "statistics": Statistics, "mtf": MTF}


def _add_common_args(sp):
    sp.add_argument("--symbol", default="NIFTY")
    sp.add_argument("--tf", default="5m")
    sp.add_argument("--at", default=None, help='point mode: "YYYY-MM-DD HH:MM"')
    sp.add_argument("--start", default=None)
    sp.add_argument("--end", default=None)
    sp.add_argument("--fields", default=None, help="comma list of fields")
    sp.add_argument("--detail", choices=["changes", "full"], default="changes")
    sp.add_argument("--max-events", type=int, default=None)
    sp.add_argument("--summary-only", action="store_true")
    sp.add_argument("--data", default=None)


def main(argv=None):
    p = argparse.ArgumentParser(prog="ai_engine.tools", description="Strategy research tools")
    sub = p.add_subparsers(dest="tool", required=True)

    ind = sub.add_parser("indicators", help="technical indicators (pandas_ta)")
    ind.add_argument("--indicators", default=None,
                     help='";"-separated, e.g. "rsi:14;adx:14;macd:12,26,9"')
    _add_common_args(ind)

    pat = sub.add_parser("patterns", help="candlestick patterns (OHLC)")
    pat.add_argument("--patterns", default=None,
                     help="comma list: doji,hammer,star,engulf,harami,inside")
    _add_common_args(pat)

    st = sub.add_parser("statistics", help="vol/returns/skew/zscore/autocorr")
    st.add_argument("--window", type=int, default=20)
    _add_common_args(st)

    mtf = sub.add_parser("mtf", help="multi-timeframe trend confluence")
    mtf.add_argument("--htf", default=None, help="comma list of higher tfs, e.g. 15m,1h")
    mtf.add_argument("--fast", type=int, default=20)
    mtf.add_argument("--slow", type=int, default=50)
    _add_common_args(mtf)

    args = p.parse_args(argv)
    tool = TOOLS[args.tool](data=args.data)
    common = dict(
        symbol=args.symbol, tf=args.tf, at=args.at, start=args.start, end=args.end,
        fields=args.fields.split(",") if args.fields else None,
        detail=args.detail, max_events=args.max_events, summary_only=args.summary_only,
    )

    if args.tool == "indicators":
        print(tool.analyze(
            indicators=args.indicators.split(";") if args.indicators else None, **common))
    elif args.tool == "patterns":
        print(tool.analyze(
            patterns=args.patterns.split(",") if args.patterns else None, **common))
    elif args.tool == "statistics":
        print(tool.analyze(window=args.window, **common))
    elif args.tool == "mtf":
        print(tool.analyze(
            htf=args.htf.split(",") if args.htf else None,
            fast=args.fast, slow=args.slow, **common))


if __name__ == "__main__":
    main()
