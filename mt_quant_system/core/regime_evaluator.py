
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio
import logging
from typing import Dict, Tuple, List, Optional, Any
from datetime import datetime
import os

logger = logging.getLogger(__name__)

class MarketRegimeOracle:
    def __init__(self, symbol: str, data: pd.DataFrame):
        """
        Args:
            symbol: Ticker symbol.
            data: DataFrame with open/high/low/close/volume. 
                  MUST be Intraday (1m prefered) to calculate 'Strong Gap' (1st min logic).
        """
        self.ticker = symbol
        self.data = data.copy()
        
        # Standardize columns
        col_map = {c: c.capitalize() for c in self.data.columns}
        self.data.rename(columns=col_map, inplace=True)
        
        # Ensure DatetimeIndex
        if not isinstance(self.data.index, pd.DatetimeIndex):
            # Try finding the timestamp column
            if 'Timestamp' in self.data.columns:
                self.data.set_index('Timestamp', inplace=True)
            elif 'Date/time' in self.data.columns:
                 self.data.set_index('Date/time', inplace=True)
            elif 'Date' in self.data.columns:
                self.data.set_index('Date', inplace=True)
            else:
                 dt_cols = self.data.select_dtypes(include=['datetime64']).columns
                 if len(dt_cols) > 0:
                     self.data.set_index(dt_cols[0], inplace=True)

        self.data.sort_index(inplace=True)

    def analyze_gaps(self):
        """
        Performs comprehensive Gap Analysis based on specialized definitions.
        Requires Intraday data for 'Strong Gap' logic (1st Minute High/Low).
        """
        # 1. Prepare Daily Data
        # Resample to Daily to get Day Open, High, Low, Close
        # Note: 'Open' of '1D' resample is the Open of the first intraday candle.
        daily_agg = {
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }
        
        # Check if we have volume, if not ignore
        if 'Volume' not in self.data.columns:
            del daily_agg['Volume']
            
        df_daily = self.data.resample('1D').agg(daily_agg).dropna()
        
        # 2. Prepare First Minute Data (For Strong Gap Logic)
        # We need the High and Low of the FIRST candle of the day.
        # df_first = self.data.resample('1D').first() # This gives Open/High/Low of the first candle
        # Logic: .first() on a dataframe returns the first valid value of each column. 
        # For 'High' column, it returns the High of the first minute. correct.
        
        df_first_min = self.data.resample('1D').first().dropna()
        # Rename to avoid confusion
        df_first_min = df_first_min[['High', 'Low']].rename(columns={'High': 'FirstMinHigh', 'Low': 'FirstMinLow'})
        
        # Merge Daily with FirstMin
        df_analysis = df_daily.join(df_first_min)
        
        if len(df_analysis) < 2:
             return {"status": "Insufficient Data", "data": None, "stats": {}}

        # 3. Calculate Previous Day Metrics
        df_analysis['PrevClose'] = df_analysis['Close'].shift(1)
        df_analysis['PrevHigh'] = df_analysis['High'].shift(1)
        df_analysis['PrevLow'] = df_analysis['Low'].shift(1)
        
        df_analysis.dropna(inplace=True)
        
        # 4. Apply Logic Definitions
        
        # Helper: Percent Change
        # Gap Up: > 0.2%
        # Gap Down: < -0.2% (implied magnitude > 0.2% down)
        threshold = 0.002
        
        df_analysis['GapPct'] = (df_analysis['Open'] - df_analysis['PrevClose']) / df_analysis['PrevClose']
        
        # --- Type 1 & 2: Gap Up / Down / Flat ---
        df_analysis['IsGapUp'] = df_analysis['GapPct'] >= threshold
        df_analysis['IsGapDown'] = df_analysis['GapPct'] <= -threshold
        df_analysis['IsFlat'] = df_analysis['GapPct'].abs() < threshold
        
        # --- Type 3: Strong Gap Up ---
        # "open last day high (Assuming > PrevHigh) and did not break the 1st Minute candle low"
        # Logic: Open > PrevHigh AND DayLow >= FirstMinLow
        df_analysis['IsStrongGapUp'] = (df_analysis['Open'] > df_analysis['PrevHigh']) & (df_analysis['Low'] >= df_analysis['FirstMinLow'])
        
        # --- Type 3 (Duplicate numbering in prompt): Strong Gap Down ---
        # "open last day low (Assuming < PrevLow) and did not break the 1st Minute candle high"
        # Logic: Open < PrevLow AND DayHigh <= FirstMinHigh
        df_analysis['IsStrongGapDown'] = (df_analysis['Open'] < df_analysis['PrevLow']) & (df_analysis['High'] <= df_analysis['FirstMinHigh'])
        
        # --- Type 4: Liquidity Grab Up ---
        # "market open gap up and fall back to last close..."
        # Logic: IsGapUp AND DayLow <= PrevClose
        df_analysis['IsLiqGrabUp'] = df_analysis['IsGapUp'] & (df_analysis['Low'] <= df_analysis['PrevClose'])
        
        # --- Type 5: Liquidity Grab Down ---
        # "market open gap down and go back to last close..."
        # Logic: IsGapDown AND DayHigh >= df_analysis['PrevClose']
        df_analysis['IsLiqGrabDown'] = df_analysis['IsGapDown'] & (df_analysis['High'] >= df_analysis['PrevClose'])
        
        # --- Type 6: Gap Up Failed ---
        # "Gap Up Failed: when day close is lesser then previousl day low"
        # Assuming conditioned on IsGapUp? Or just any gap up? Let's use IsGapUp (>0.2%).
        # Logic: IsGapUp AND Close < PrevLow
        df_analysis['IsGapUpFailed'] = df_analysis['IsGapUp'] & (df_analysis['Close'] < df_analysis['PrevLow'])
        
        # --- Type 7: Gap Down Failed ---
        # "Gap Down Failed: when day close is higher then previousl day high"
        # Logic: IsGapDown AND Close > PrevHigh
        df_analysis['IsGapDownFailed'] = df_analysis['IsGapDown'] & (df_analysis['Close'] > df_analysis['PrevHigh'])

        # 5. Statistics Aggregation
        total_days = len(df_analysis)
        
        stats = {
            'Total Days': total_days,
            'Gap Up (> 0.2%)': df_analysis['IsGapUp'].sum(),
            'Gap Down (> 0.2%)': df_analysis['IsGapDown'].sum(),
            'Flat Opening (< 0.2%)': df_analysis['IsFlat'].sum(),
            'Strong Gap Up': df_analysis['IsStrongGapUp'].sum(),
            'Strong Gap Down': df_analysis['IsStrongGapDown'].sum(),
            'Gap Up Liq. Grab Down': df_analysis['IsLiqGrabUp'].sum(),
            'Gap Down Liq. Grab Up': df_analysis['IsLiqGrabDown'].sum(),
            'Gap Up Failed': df_analysis['IsGapUpFailed'].sum(),
            'Gap Down Failed': df_analysis['IsGapDownFailed'].sum()
        }
        
        # Add Percentages
        stats_pct = {k: (v / total_days * 100) for k, v in stats.items() if k != 'Total Days'}
        
        return {"status": "Success", "data": df_analysis, "stats": stats, "stats_pct": stats_pct}

    def run_full_report(self):
        """Executes the Overall analysis."""
        return {"Overall": self.analyze_gaps()}


def generate_regime_html_report(ticker: str, results: Dict[str, Dict], output_path: str):
    """
    Generates a comprehensive HTML report for GAP Analysis matching the system's look & feel.
    """
    
    # Use the same CSS block as report_generator.py
    css = """
    <style>
        :root {
            --bg-color: #0d1117; 
            --sidebar-bg: #010409;
            --container-bg: #0d1117;
            --card-bg: #161b22;
            --card-hover: #1f2428;
            --border-color: #30363d;
            --text-primary: #e6edf3; 
            --text-secondary: #8b949e;
            --accent-primary: #2f81f7;
            --accent-pos: #3fb950;
            --accent-neg: #f85149;
            --nav-hover: #21262d;
            --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
        }

        body, html {
            height: 100%;
            margin: 0;
            padding: 0;
            font-family: var(--font-family);
            background-color: var(--bg-color);
            color: var(--text-primary);
            overflow: hidden; 
            -webkit-font-smoothing: antialiased;
        }

        .app-container {
            display: flex;
            height: 100vh;
            width: 100%;
        }

        /* Sidebar similar to report_generator */
        .sidebar {
            width: 280px;
            background-color: rgba(31, 111, 235, 0.08);
            border: 1px solid rgba(56, 139, 253, 0.15);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
            margin: 12px;
            border-radius: 16px;
            height: calc(100vh - 24px);
            backdrop-filter: blur(10px);
        }

        .sidebar-header {
            padding: 24px;
            border-bottom: 1px solid rgba(56, 139, 253, 0.1);
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .brand-logo {
            width: 38px; height: 38px; color: #58a6ff;
            background: rgba(88, 166, 255, 0.15);
            padding: 8px; border-radius: 8px; flex-shrink: 0;
        }

        .sidebar-title {
            font-size: 1.25rem; font-weight: 700;
            background: linear-gradient(90deg, #58a6ff, #a5d6ff);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            margin: 0;
        }

        .sidebar-subtitle {
            font-size: 0.85rem; color: var(--text-secondary);
            margin-top: 6px; font-weight: 500;
        }
        
        .nav-links {
            list-style: none; padding: 16px 12px; margin: 0; flex: 1;
        }
        .nav-item {
            padding: 10px 16px; margin-bottom: 4px; cursor: default;
            color: var(--text-primary); font-size: 0.95rem; font-weight: 600;
            background-color: #1f6feb; border-radius: 6px;
            box-shadow: 0 4px 12px rgba(31, 111, 235, 0.2);
            display: flex; align-items: center;
        }

        .content-area {
            flex: 1; overflow-y: auto; padding: 30px 40px;
            background-color: var(--bg-color);
        }

        .page-title h2 {
            margin: 0; font-size: 2rem; font-weight: 700;
            background: linear-gradient(90deg, #58a6ff, #a5d6ff);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            margin-bottom: 30px;
        }

        /* Metric Cards */
        .metric-card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 24px;
            display: flex; flex-direction: column;
            justify-content: space-between; align-items: center;
            text-align: center;
            transition: all 0.25s;
        }
        .metric-card:hover {
            transform: translateY(-4px); border-color: #8b949e;
            background-color: #1c2128;
        }
        .metric-title {
            font-size: 0.85rem; font-weight: 600; color: var(--text-secondary);
            text-transform: uppercase; letter-spacing: 0.5px;
            margin-bottom: 12px;
        }
        .metric-value {
            font-size: 1.75rem; font-weight: 700; color: var(--text-primary);
        }
        .metric-sub {
            font-size: 0.85rem; margin-top: 5px; opacity: 0.8;
        }

        .grid-container {
            display: grid; grid-template-columns: repeat(4, 1fr);
            gap: 20px; margin-bottom: 30px;
        }

        /* Tables & Charts */
        .card-panel {
            background: var(--card-bg); 
            border: 1px solid var(--border-color);
            border-radius: 8px; padding: 20px;
            margin-bottom: 24px;
        }
        .panel-title {
            font-size: 1.1rem; font-weight: 600; color: var(--text-primary);
            margin-bottom: 16px; border-bottom: 1px solid var(--border-color);
            padding-bottom: 12px;
        }

        .stat-table {
            width: 100%; border-collapse: collapse; font-size: 0.9rem;
        }
        .stat-table th, .stat-table td {
            padding: 12px; text-align: left;
            border-bottom: 1px solid var(--border-color);
            color: var(--text-primary);
        }
        .stat-table th {
            color: var(--text-secondary); font-weight: 600;
            background-color: var(--card-bg); /* Use solid color to hide scrolled content */
            position: sticky;
            top: 0;
            z-index: 10;
            box-shadow: 0 1px 0 var(--border-color); /* Add border via shadow */
        }
        .stat-table tr:hover td { background-color: rgba(255,255,255,0.03); }

        /* Helpers */
        .color-up { color: var(--accent-pos); }
        .color-down { color: var(--accent-neg); }
        .color-neu { color: var(--text-secondary); }

        /* Tabs */
        .tab {
            overflow: hidden;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 20px;
        }
        .tab button {
            background-color: transparent;
            float: left;
            border: none;
            outline: none;
            cursor: pointer;
            padding: 14px 16px;
            transition: 0.3s;
            color: var(--text-secondary);
            font-weight: 600;
            border-bottom: 2px solid transparent;
        }
        .tab button:hover {
            color: var(--text-primary);
            background-color: rgba(255,255,255,0.02);
        }
        .tab button.active {
            color: var(--accent-primary);
            border-bottom: 2px solid var(--accent-primary);
        }
        .tabcontent {
            display: none;
            animation: fadeEffect 0.5s;
        }
        @keyframes fadeEffect {
            from {opacity: 0;}
            to {opacity: 1;}
        }
        .data-table-container {
            max-height: 500px;
            overflow-y: auto;
        }
        .logic-val { font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 0.85em; opacity: 0.8; }
        .success-val { color: var(--accent-pos); }
        .fail-val { color: var(--accent-neg); }

    </style>
    <script>
    function openTab(evt, tabName) {
      var i, tabcontent, tablinks;
      tabcontent = document.getElementsByClassName("tabcontent");
      for (i = 0; i < tabcontent.length; i++) {
        tabcontent[i].style.display = "none";
      }
      tablinks = document.getElementsByClassName("tablinks");
      for (i = 0; i < tablinks.length; i++) {
        tablinks[i].className = tablinks[i].className.replace(" active", "");
      }
      document.getElementById(tabName).style.display = "block";
      evt.currentTarget.className += " active";
    }
    </script>
    """
    
    # Logic to build content
    res = results.get("Overall", {})
    
    if res.get('status') != "Success":
        content_html = f"<div class='card-panel'><div class='panel-title'>Status</div><p>{res.get('status', 'Unknown Error')}</p></div>"
    else:
        stats = res['stats']
        pct = res['stats_pct']
        df = res['data'] # Access the DataFrame with OHLC and calculations

        # 1. Top Metrics Grid (Highlights)
        metrics_html = f"""
        <div class="grid-container">
            <div class="metric-card">
                <div class="metric-title">Total Days</div>
                <div class="metric-value color-neu">{stats['Total Days']}</div>
                <div class="metric-sub">Analyzed Period</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Gap Ups (> 0.2%)</div>
                <div class="metric-value color-up">{stats['Gap Up (> 0.2%)']}</div>
                <div class="metric-sub">{pct['Gap Up (> 0.2%)']:.1f}% of Days</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Gap Downs (> 0.2%)</div>
                <div class="metric-value color-down">{stats['Gap Down (> 0.2%)']}</div>
                <div class="metric-sub">{pct['Gap Down (> 0.2%)']:.1f}% of Days</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Flat Openings</div>
                <div class="metric-value color-neu">{stats['Flat Opening (< 0.2%)']}</div>
                <div class="metric-sub">{pct['Flat Opening (< 0.2%)']:.1f}% of Days</div>
            </div>
        </div>
        """
        
        # 2. Detailed Tabs with Logic and Data
        
        # Define the categories configurations
        categories = [
             {'id': 'GapUp', 'label': 'Gap Up', 'col': 'IsGapUp', 'logic_cols': ['GapPct'], 'desc': 'Gap > 0.2%'},
             {'id': 'GapDown', 'label': 'Gap Down', 'col': 'IsGapDown', 'logic_cols': ['GapPct'], 'desc': 'Gap < -0.2%'},
             {'id': 'Flat', 'label': 'Flat Opening', 'col': 'IsFlat', 'logic_cols': ['GapPct'], 'desc': 'Abs(Gap) < 0.2%'},
             {'id': 'StrongUp', 'label': 'Strong Gap Up', 'col': 'IsStrongGapUp', 'logic_cols': ['PrevHigh', 'FirstMinLow'], 'desc': 'Open > PrevHigh & Low >= FirstMinLow'},
             {'id': 'StrongDown', 'label': 'Strong Gap Down', 'col': 'IsStrongGapDown', 'logic_cols': ['PrevLow', 'FirstMinHigh'], 'desc': 'Open < PrevLow & High <= FirstMinHigh'},
             {'id': 'LiqGrabUp', 'label': 'Gap Up Liq. Grab Down', 'col': 'IsLiqGrabUp', 'logic_cols': ['PrevClose'], 'desc': 'Gap Up & Low <= Prev Close'},
             {'id': 'LiqGrabDown', 'label': 'Gap Down Liq. Grab Up', 'col': 'IsLiqGrabDown', 'logic_cols': ['PrevClose'], 'desc': 'Gap Down & High >= Prev Close'},
             {'id': 'FailUp', 'label': 'Failed Gap Up', 'col': 'IsGapUpFailed', 'logic_cols': ['PrevLow'], 'desc': 'Gap Up & Close < Prev Low'},
             {'id': 'FailDown', 'label': 'Failed Gap Down', 'col': 'IsGapDownFailed', 'logic_cols': ['PrevHigh'], 'desc': 'Gap Down & Close > Prev High'},
             {'id': 'All', 'label': 'All', 'col': 'All', 'logic_cols': [], 'desc': 'All Dates & Regimes (1=True, 0=False)'},
        ]

        # Build Tabs Navigation
        tabs_nav = '<div class="tab">'
        tabs_content = ''
        
        for i, cat in enumerate(categories):
            is_active = "active" if i == 0 else ""
            display_style = "block" if i == 0 else "none"
            
            # Use 'col' check to be safe
            if cat['col'] == 'All':
                mask = pd.Series([True] * len(df), index=df.index)
            else:
                mask = df[cat['col']]

            count = mask.sum()
            
            tabs_nav += f'<button class="tablinks {is_active}" onclick="openTab(event, \'{cat["id"]}\')">{cat["label"]} ({count})</button>'
            
            # Build Table Content
            rows_html = ""
            subset = df[mask].copy()
            
            if subset.empty:
                rows_html = "<tr><td colspan='10' style='text-align:center; padding:20px; color:var(--text-secondary);'>No events found for this category.</td></tr>"
                if cat['col'] == 'All':
                    thead_html = """
                            <tr>
                                <th>Date</th>
                                <th>GapUp</th>
                                <th>GapDn</th>
                                <th>Flat</th>
                                <th>StrUp</th>
                                <th>StrDn</th>
                                <th>LiqUp</th>
                                <th>LiqDn</th>
                                <th>FailUp</th>
                                <th>FailDn</th>
                            </tr>
                    """
                else:
                    thead_html = """
                            <tr>
                                <th>Date</th>
                                <th>Open</th>
                                <th>High</th>
                                <th>Low</th>
                                <th>Close</th>
                                <th>Logic / Calc Check</th>
                            </tr>
                    """
            else:
                if cat['col'] == 'All':
                    # Special Headers for ALL
                    thead_html = """
                            <tr>
                                <th>Date</th>
                                <th>GapUp</th>
                                <th>GapDn</th>
                                <th>Flat</th>
                                <th>StrUp</th>
                                <th>StrDn</th>
                                <th>LiqUp</th>
                                <th>LiqDn</th>
                                <th>FailUp</th>
                                <th>FailDn</th>
                            </tr>
                    """
                    for date, row in subset.iterrows():
                        date_str = date.strftime('%Y-%m-%d')
                        rows_html += f"""
                        <tr>
                            <td style="font-family:monospace; color:var(--accent-primary);">{date_str}</td>
                            <td style="text-align:center;">{int(row['IsGapUp'])}</td>
                            <td style="text-align:center;">{int(row['IsGapDown'])}</td>
                            <td style="text-align:center;">{int(row['IsFlat'])}</td>
                            <td style="text-align:center;">{int(row['IsStrongGapUp'])}</td>
                            <td style="text-align:center;">{int(row['IsStrongGapDown'])}</td>
                            <td style="text-align:center;">{int(row['IsLiqGrabUp'])}</td>
                            <td style="text-align:center;">{int(row['IsLiqGrabDown'])}</td>
                            <td style="text-align:center;">{int(row['IsGapUpFailed'])}</td>
                            <td style="text-align:center;">{int(row['IsGapDownFailed'])}</td>
                        </tr>
                        """
                else:
                    thead_html = """
                            <tr>
                                <th>Date</th>
                                <th>Open</th>
                                <th>High</th>
                                <th>Low</th>
                                <th>Close</th>
                                <th>Logic / Calc Check</th>
                            </tr>
                    """
                    # Iterate rows to format calculations
                    for date, row in subset.iterrows():
                        date_str = date.strftime('%Y-%m-%d')
                        
                        # Logic Explanation String
                        logic_str = ""
                        if cat['id'] in ['GapUp', 'GapDown', 'Flat']:
                            logic_str = f"Gap: {row['GapPct']*100:.2f}%"
                        elif 'Strong' in cat['id']:
                            ref_h_l = 'PrevHigh' if 'Up' in cat['id'] else 'PrevLow'
                            first_limit = 'FirstMinLow' if 'Up' in cat['id'] else 'FirstMinHigh'
                            logic_str = f"Open vs {ref_h_l}: {row['Open']:.2f} vs {row[ref_h_l]:.2f}<br/>Limit vs 1Min: {row['Low' if 'Up' in cat['id'] else 'High']:.2f} vs {row[first_limit]:.2f}"
                        elif 'LiqGrab' in cat['id']:
                             logic_str = f"Target (PrevClose): {row['PrevClose']:.2f}<br/>Reached: {row['Low' if 'Up' in cat['id'] else 'High']:.2f}"
                        elif 'Fail' in cat['id']:
                             ref = 'PrevLow' if 'Up' in cat['id'] else 'PrevHigh'
                             logic_str = f"Close vs {ref}: {row['Close']:.2f} vs {row[ref]:.2f}"
                             
                        rows_html += f"""
                        <tr>
                            <td style="font-family:monospace; color:var(--accent-primary);">{date_str}</td>
                            <td style="font-family:monospace;">{row['Open']:.2f}</td>
                            <td style="font-family:monospace;">{row['High']:.2f}</td>
                            <td style="font-family:monospace;">{row['Low']:.2f}</td>
                            <td style="font-family:monospace;">{row['Close']:.2f}</td>
                            <td style="font-size:0.9em; color:var(--text-secondary);">{logic_str}</td>
                        </tr>
                        """

            tabs_content += f"""
            <div id="{cat['id']}" class="tabcontent" style="display: {display_style};">
                <div class="panel-title" style="border:none; margin-bottom:10px;">
                    {cat['label']} <span style="font-weight:normal; font-size:0.85em; color:var(--text-secondary);"> :: {cat['desc']}</span>
                </div>
                <div class="data-table-container">
                    <table class="stat-table">
                        <thead>
                            {thead_html}
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                    </table>
                </div>
            </div>
            """
            
        tabs_nav += "</div>"
        
        tabbed_section_html = f"""
        <div class="card-panel">
            {tabs_nav}
            {tabs_content}
        </div>
        """

        # 3. Chart (Simplified)
        chart_html = "" # Optionally keep or remove chart if table is focus. Let's keep it below.
        categories_chart = list(stats.keys())[3:]
        values = [stats[k] for k in categories_chart]
        colors = ['#3fb950', '#f85149', '#2f81f7', '#d29922', '#8b949e', '#8b949e']
        
        fig = go.Figure(go.Bar(x=categories_chart, y=values, marker_color=colors))
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI'", color="#e6edf3"),
            title=dict(text="Regime Distribution", font=dict(size=16)),
            height=300,
            margin=dict(l=40, r=40, t=40, b=40)
        )
        chart_html = f'<div class="card-panel">{pio.to_html(fig, full_html=False, include_plotlyjs="cdn")}</div>'


        content_html = metrics_html + chart_html + tabbed_section_html

    # Full HTML construction
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Gap Analysis: {ticker}</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        {css}
    </head>
    <body>
        <div class="app-container">
            <!-- Sidebar -->
            <div class="sidebar">
                <div class="sidebar-header">
                    <!-- Simple Logo Icon -->
                    <div class="brand-logo">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
                            <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
                            <line x1="12" y1="22.08" x2="12" y2="12"></line>
                        </svg>
                    </div>
                    <div>
                        <h1 class="sidebar-title">IndexMisBn Backtesting</h1>
                        <div class="sidebar-subtitle">Gap Analysis</div>
                    </div>
                </div>
                
                <ul class="nav-links">
                    <li class="nav-item active">
                       Overall Analysis
                    </li>
                </ul>
                
                <div style="padding: 24px; font-size: 0.75rem; color: #8b949e; border-top: 1px solid rgba(56, 139, 253, 0.1); text-align: center;">
                    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
                </div>
            </div>

            <!-- Content -->
            <div class="content-area">
                <div class="page-title">
                    <h2>{ticker} | Gap Analysis Report</h2>
                </div>
                {content_html}
            </div>
        </div>
    </body>
    </html>
    """
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
        
    return output_path

