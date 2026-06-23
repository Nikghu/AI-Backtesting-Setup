"""
BO Fail Trade Indicator Analysis
---------------------------------
Temporary analysis module. Can be removed by deleting this file and
removing the call in report_generator.py (search: "bo_fail_analysis").

For each BO Fail losing trade, computes RSI, ADX, Choppiness Index,
and EMA 50 / EMA 200 delta vs LTP at the entry candle.
Outputs averages + optional KMeans cluster breakdown to a standalone HTML file.
"""

import pandas as pd
import numpy as np
import pandas_ta as ta
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_bo_fail_analysis(
    enriched_trades: List[Dict],
    analysis_data: pd.DataFrame,
    risk_factors: Dict[str, Any],
    output_path: str,
) -> None:
    """
    Main entry point called from report_generator.py.

    Args:
        enriched_trades : list of enriched trade dicts (from calculate_trade_metrics)
        analysis_data   : OHLC DataFrame with DatetimeIndex (same TF used for trade analysis)
        risk_factors    : output of analyze_trade_outcomes – contains 'trades' with 'BO Fail' flag
        output_path     : full path for the output HTML file (e.g. "...._bo_fail_analysis.html")
    """
    if not risk_factors or "trades" not in risk_factors:
        logger.info("BO Fail Analysis: no risk_factors data available, skipping.")
        return

    # 1. Collect trade numbers flagged as BO Fail
    bo_fail_nos = {
        t["Trade No"]
        for t in risk_factors["trades"]
        if t.get("BO Fail", 0) == 1
    }

    if not bo_fail_nos:
        logger.info("BO Fail Analysis: no BO Fail trades found, skipping.")
        return

    bo_fail_trades = [t for t in enriched_trades if t.get("Trade No") in bo_fail_nos]

    if not bo_fail_trades:
        logger.info("BO Fail Analysis: could not match BO Fail trades in enriched list, skipping.")
        return

    logger.info(f"BO Fail Analysis: analysing {len(bo_fail_trades)} BO Fail trades …")

    # 2. Compute indicators on the analysis OHLC frame
    df = _compute_indicators(analysis_data)

    if df is None:
        logger.warning("BO Fail Analysis: indicator computation failed, skipping.")
        return

    # 3. Extract per-trade indicator snapshot at entry candle
    rows = _extract_entry_snapshots(bo_fail_trades, df)

    if not rows:
        logger.warning("BO Fail Analysis: could not extract entry snapshots, skipping.")
        return

    df_snap = pd.DataFrame(rows)

    # 4. Aggregate statistics
    ind_cols = ["RSI", "ADX", "Choppiness", "EMA50_Delta%", "EMA200_Delta%"]
    agg_stats = _aggregate_stats(df_snap, ind_cols)

    # 5. Optional KMeans clustering
    cluster_html = _try_cluster(df_snap, ind_cols)

    # 6. Render & save HTML
    _save_html(df_snap, agg_stats, cluster_html, output_path)
    logger.info(f"BO Fail Analysis report saved → {output_path}")


# ---------------------------------------------------------------------------
# Indicator computation
# ---------------------------------------------------------------------------

def _compute_indicators(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Computes RSI, ADX, Choppiness, EMA50, EMA200 on the supplied OHLC frame."""
    try:
        df = ohlc.copy()

        # Normalise column names to lower-case keys for look-up
        col_map = {c.lower(): c for c in df.columns}
        high  = col_map.get("high",  "High")
        low   = col_map.get("low",   "Low")
        close = col_map.get("close", "Close")

        if not all(c in df.columns for c in [high, low, close]):
            logger.error("BO Fail Analysis: OHLC frame missing high/low/close columns.")
            return None

        # RSI
        df["_rsi"] = ta.rsi(df[close], length=14)

        # ADX  (pandas-ta returns a DataFrame; grab the ADX column)
        adx_result = ta.adx(df[high], df[low], df[close], length=14)
        if adx_result is not None and not adx_result.empty:
            adx_col = [c for c in adx_result.columns if c.upper().startswith("ADX_")]
            df["_adx"] = adx_result[adx_col[0]] if adx_col else np.nan
        else:
            df["_adx"] = np.nan

        # Choppiness Index (pandas-ta)
        chop_result = ta.chop(df[high], df[low], df[close], length=14)
        df["_chop"] = chop_result if chop_result is not None else np.nan

        # EMA 50 / 200 and delta vs close  (positive = price ABOVE ema)
        df["_ema50"]  = ta.ema(df[close], length=50)
        df["_ema200"] = ta.ema(df[close], length=200)
        df["_ema50_delta"]  = (df[close] - df["_ema50"])  / df[close] * 100
        df["_ema200_delta"] = (df[close] - df["_ema200"]) / df[close] * 100

        return df

    except Exception as e:
        logger.error(f"BO Fail Analysis: _compute_indicators error – {e}")
        return None


# ---------------------------------------------------------------------------
# Entry snapshot extraction
# ---------------------------------------------------------------------------

def _extract_entry_snapshots(bo_fail_trades: List[Dict], df: pd.DataFrame) -> List[Dict]:
    """For each BO Fail trade, finds the indicator values at the entry bar."""
    rows = []
    for trade in bo_fail_trades:
        try:
            entry_time = pd.to_datetime(trade["Entry Date/Time"])
            # searchsorted finds the last bar whose timestamp <= entry_time
            idx = df.index.searchsorted(entry_time, side="right") - 1
            if idx < 0 or idx >= len(df):
                continue
            bar = df.iloc[idx]

            def _safe(col):
                v = bar.get(col, np.nan)
                return round(float(v), 3) if pd.notna(v) else np.nan

            rows.append({
                "Trade No"    : trade.get("Trade No"),
                "Entry Time"  : entry_time,
                "Direction"   : trade.get("Type", ""),
                "Entry Price" : trade.get("Entry Price", np.nan),
                "PnL"         : trade.get("PnL", np.nan),
                "RSI"         : _safe("_rsi"),
                "ADX"         : _safe("_adx"),
                "Choppiness"  : _safe("_chop"),
                "EMA50_Delta%": _safe("_ema50_delta"),
                "EMA200_Delta%": _safe("_ema200_delta"),
            })
        except Exception as e:
            logger.debug(f"BO Fail Analysis: snapshot error for trade {trade.get('Trade No')}: {e}")
            continue
    return rows


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _aggregate_stats(df: pd.DataFrame, cols: List[str]) -> Dict[str, Dict]:
    stats = {}
    for col in cols:
        s = df[col].dropna()
        if s.empty:
            continue
        stats[col] = {
            "Count" : int(s.count()),
            "Mean"  : round(s.mean(),   2),
            "Median": round(s.median(), 2),
            "Std"   : round(s.std(),    2),
            "Min"   : round(s.min(),    2),
            "Max"   : round(s.max(),    2),
        }
    return stats


# ---------------------------------------------------------------------------
# KMeans clustering
# ---------------------------------------------------------------------------

def _try_cluster(df: pd.DataFrame, feature_cols: List[str]) -> str:
    """Returns an HTML snippet for the cluster table, or empty string on failure."""
    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler

        df_feat = df[feature_cols].dropna()
        n = len(df_feat)
        if n < 3:
            return ""

        n_clusters = min(3, n)
        scaler = StandardScaler()
        X = scaler.fit_transform(df_feat)
        km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = km.fit_predict(X)

        # Cluster centres in original scale
        centers = pd.DataFrame(
            scaler.inverse_transform(km.cluster_centers_),
            columns=feature_cols,
        ).round(2)

        counts = pd.Series(labels).value_counts().sort_index()
        centers.insert(0, "Trades", [counts.get(i, 0) for i in range(n_clusters)])

        # Assign simple market-regime label heuristic
        def _label(row):
            rsi  = row.get("RSI", 50)
            adx  = row.get("ADX", 20)
            chop = row.get("Choppiness", 50)
            if adx < 20 or chop > 61.8:
                return "Choppy / Low Trend"
            if rsi > 65:
                return "Overbought Breakout"
            if rsi < 35:
                return "Oversold Breakout"
            return "Moderate Trend"

        centers["Regime Label"] = [_label(row) for _, row in centers.iterrows()]

        return _render_cluster_table(centers, n_clusters)

    except ImportError:
        logger.info("BO Fail Analysis: sklearn not installed – ML clustering skipped.")
        return "<p style='color:#8b949e;font-size:13px;'>sklearn not installed – ML clustering unavailable.</p>"
    except Exception as e:
        logger.warning(f"BO Fail Analysis: clustering error – {e}")
        return ""


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_DARK_CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0d1117; color: #c9d1d9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    padding: 28px 32px; font-size: 14px;
  }
  h1 { color: #f0f6fc; font-size: 22px; margin-bottom: 4px; }
  h2 { color: #e6edf3; font-size: 16px; margin: 28px 0 12px; border-bottom: 1px solid #21262d; padding-bottom: 6px; }
  p.sub { color: #8b949e; margin-bottom: 20px; font-size: 13px; }
  .card {
    background: #161b22; border: 1px solid #21262d; border-radius: 8px;
    padding: 20px; margin-bottom: 24px; overflow-x: auto;
  }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th {
    background: #1f2937; color: #8b949e; font-weight: 600;
    text-align: right; padding: 8px 12px; white-space: nowrap;
    border-bottom: 2px solid #21262d;
  }
  th:first-child { text-align: left; }
  td { padding: 7px 12px; border-bottom: 1px solid #21262d; text-align: right; }
  td:first-child { text-align: left; color: #e6edf3; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #1c2128; }
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 11px; font-weight: 600;
  }
  .long  { background: #0d4429; color: #3fb950; }
  .short { background: #4a0404; color: #f85149; }
  .neg   { color: #f85149; }
  .pos   { color: #3fb950; }
  .neutral { color: #d29922; }
</style>
"""


def _val_class(val, col: str) -> str:
    """Returns a CSS class based on value context."""
    if pd.isna(val):
        return ""
    if col == "RSI":
        if val > 65: return "neg"
        if val < 35: return "pos"
        return "neutral"
    if col == "ADX":
        return "pos" if val > 25 else "neutral"
    if col == "Choppiness":
        return "neg" if val > 61.8 else ("neutral" if val > 38.2 else "pos")
    if "Delta" in col:
        return "pos" if val > 0 else "neg"
    if col == "PnL":
        return "pos" if val >= 0 else "neg"
    return ""


def _fmt(val) -> str:
    if pd.isna(val): return "–"
    if isinstance(val, float): return f"{val:.2f}"
    return str(val)


def _render_summary_table(stats: Dict[str, Dict]) -> str:
    rows_html = ""
    for ind, s in stats.items():
        rows_html += f"""
        <tr>
          <td>{ind}</td>
          <td>{s['Count']}</td>
          <td class="{_val_class(s['Mean'], ind)}">{s['Mean']}</td>
          <td class="{_val_class(s['Median'], ind)}">{s['Median']}</td>
          <td>{s['Std']}</td>
          <td>{s['Min']}</td>
          <td>{s['Max']}</td>
        </tr>"""

    return f"""
    <table>
      <thead><tr>
        <th>Indicator</th><th>Count</th><th>Mean</th><th>Median</th>
        <th>Std Dev</th><th>Min</th><th>Max</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>"""


def _render_trades_table(df: pd.DataFrame) -> str:
    ind_cols = ["RSI", "ADX", "Choppiness", "EMA50_Delta%", "EMA200_Delta%"]
    rows_html = ""
    for _, r in df.iterrows():
        dir_badge = f'<span class="badge {"long" if r["Direction"]=="LONG" else "short"}">{r["Direction"]}</span>'
        pnl_cls = "pos" if r["PnL"] >= 0 else "neg"
        cells = "".join(
            f'<td class="{_val_class(r[c], c)}">{_fmt(r[c])}</td>'
            for c in ind_cols
        )
        rows_html += f"""
        <tr>
          <td>{r['Trade No']}</td>
          <td>{pd.to_datetime(r['Entry Time']).strftime('%Y-%m-%d %H:%M')}</td>
          <td>{dir_badge}</td>
          <td>{_fmt(r['Entry Price'])}</td>
          <td class="{pnl_cls}">{_fmt(r['PnL'])}</td>
          {cells}
        </tr>"""

    headers = "".join(f"<th>{c}</th>" for c in ind_cols)
    return f"""
    <table>
      <thead><tr>
        <th>Trade #</th><th>Entry Time</th><th>Dir</th>
        <th>Entry Price</th><th>PnL</th>
        {headers}
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>"""


def _render_cluster_table(centers: pd.DataFrame, n_clusters: int) -> str:
    ind_cols = list(centers.columns)
    rows_html = ""
    for i, row in centers.iterrows():
        cells = "".join(f"<td>{_fmt(row[c])}</td>" for c in ind_cols)
        rows_html += f"<tr><td>Cluster {i}</td>{cells}</tr>"

    headers = "".join(f"<th>{c}</th>" for c in ind_cols)
    return f"""
    <table>
      <thead><tr><th>Cluster</th>{headers}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>"""


def _save_html(
    df_snap: pd.DataFrame,
    agg_stats: Dict,
    cluster_html: str,
    output_path: str,
) -> None:
    total = len(df_snap)
    long_cnt  = int((df_snap["Direction"] == "LONG").sum())
    short_cnt = int((df_snap["Direction"] == "SHORT").sum())

    ml_section = ""
    if cluster_html:
        ml_section = f"""
        <h2>ML Clustering – KMeans (Market Regime at Entry)</h2>
        <p class="sub">
          Indicator values at entry are normalised and grouped into clusters.
          The <em>Regime Label</em> is a heuristic based on ADX / RSI / Choppiness.
          Use this to understand what market conditions dominate BO Fail entries.
        </p>
        <div class="card">{cluster_html}</div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BO Fail Trade Analysis</title>
  {_DARK_CSS}
</head>
<body>
  <h1>BO Fail Trade — Indicator Analysis</h1>
  <p class="sub">
    Total BO Fail trades: <strong>{total}</strong>
    &nbsp;|&nbsp; Long: {long_cnt} &nbsp;|&nbsp; Short: {short_cnt}
    &nbsp;|&nbsp; Indicators measured at entry candle on the analysis timeframe.
  </p>

  <h2>Average Indicator Values at Entry</h2>
  <p class="sub">
    RSI: momentum (overbought &gt;65 / oversold &lt;35) &nbsp;|&nbsp;
    ADX: trend strength (&gt;25 = trending) &nbsp;|&nbsp;
    Choppiness: &gt;61.8 choppy, &lt;38.2 trending &nbsp;|&nbsp;
    EMA Delta%: (Close − EMA) / Close × 100 — positive = price above EMA
  </p>
  <div class="card">{_render_summary_table(agg_stats)}</div>

  {ml_section}

  <h2>Per-Trade Detail</h2>
  <div class="card">{_render_trades_table(df_snap)}</div>

</body>
</html>"""

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        logger.error(f"BO Fail Analysis: failed to write HTML – {e}")
