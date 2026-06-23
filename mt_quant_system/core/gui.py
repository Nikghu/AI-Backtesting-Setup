import sys
from typing import List, Optional, Tuple, Dict
from datetime import datetime
import pandas as pd
from PyQt5.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout, 
                             QLabel, QListWidget, QPushButton, QWidget, 
                             QMessageBox, QAbstractItemView, QCheckBox, QDateEdit, QGroupBox, QGridLayout, QTimeEdit, QRadioButton, QSpinBox, QDoubleSpinBox, QComboBox, QFileDialog)
from PyQt5.QtCore import Qt, QDate, QTime, QUrl
from PyQt5.QtGui import QDesktopServices
import os
from pathlib import Path
from .data_loader import DataLoader
from .regime_evaluator import MarketRegimeOracle, generate_regime_html_report

"""
mtQuant GUI Configuration Module.
Provides PyQt5 dialogs for selection strategies, symbols, timeframes, and date ranges.
"""

class SelectorDialog(QDialog):
    def __init__(self, strategies: List[str], data_dir: str = "data", initial_file: str = None):
        """
        strategies: List of strategy names
        data_dir: Directory containing feather files
        initial_file: Pre-selected file path
        """
        super().__init__()
        self.setWindowTitle("IndexMisBn Backtesting")
        self.resize(700, 700)
        
        self.data_dir = Path(data_dir)
        self.timeframe_data = {}
        
        # Outputs
        self.selected_file = None
        self.selected_strategy = None
        self.selected_symbols = []
        self.selected_timeframes = []
        self.start_date = None
        self.end_date = None
        self.intraday_enabled = False
        self.start_time = None
        self.stop_time = None
        self.instrument_type = "Spot"
        self.lot_size = 1
        self.initial_capital = 100000.0
        self.analysis_tf = "3m"
        self.analysis_lookback = 10
        self.losing_analysis = False
        self.debug_mode = False
        
        # Layouts
        main_layout = QVBoxLayout(self)
        
        # 0. Data File Selection
        file_group = QGroupBox("0. Select Data File")
        file_layout = QHBoxLayout()
        
        self.combo_files = QComboBox()
        self.refresh_file_list()
        self.combo_files.currentIndexChanged.connect(self.on_file_changed)
        
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self.refresh_file_list)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self.browse_file)
        
        file_layout.addWidget(QLabel("File:"))
        file_layout.addWidget(self.combo_files, 1)
        file_layout.addWidget(btn_refresh)
        file_layout.addWidget(btn_browse)
        file_group.setLayout(file_layout)
        
        # Top Section: Strategy & Symbol
        top_layout = QHBoxLayout()
        
        # 1. Strategy
        strat_group = QGroupBox("1. Select Strategy")
        strat_layout = QVBoxLayout()
        self.strat_list = QListWidget()
        self.strat_list.addItems(strategies)
        self.strat_list.setSelectionMode(QAbstractItemView.SingleSelection)
        if strategies:
            self.strat_list.setCurrentRow(0)
        strat_layout.addWidget(self.strat_list)
        strat_group.setLayout(strat_layout)
        
        # 2. Symbols
        sym_group = QGroupBox("2. Select Symbols")
        sym_layout = QVBoxLayout()
        self.chk_all_sym = QCheckBox("Select All")
        self.chk_all_sym.setChecked(True)
        self.chk_all_sym.stateChanged.connect(self.toggle_all_symbols)
        self.chk_all_sym.setEnabled(False) # Disabled until data loads
        
        self.sym_list = QListWidget()
        self.sym_list.setSelectionMode(QAbstractItemView.MultiSelection)
        
        sym_layout.addWidget(self.chk_all_sym)
        sym_layout.addWidget(self.sym_list)
        sym_group.setLayout(sym_layout)
        
        top_layout.addWidget(strat_group, 1)
        top_layout.addWidget(sym_group, 1)
        
        # Middle Section: Timeframe & Date
        mid_layout = QHBoxLayout()
        
        # 3. Timeframes
        tf_group = QGroupBox("3. Select Timeframes")
        self.tf_layout_inner = QHBoxLayout() # Store to add/remove widgets
        self.tf_checkboxes = {}
        tf_group.setLayout(self.tf_layout_inner)
        
        # 4. Data Range
        date_group = QGroupBox("4. Select Date Range")
        date_layout = QHBoxLayout()
        
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        
        date_layout.addWidget(QLabel("Start Date:"))
        date_layout.addWidget(self.date_start)
        date_layout.addWidget(QLabel("End Date:"))
        date_layout.addWidget(self.date_end)
        date_group.setLayout(date_layout)
        
        mid_layout.addWidget(tf_group, 1)
        mid_layout.addWidget(date_group, 1)
        
        # 5. Intraday Settings
        intra_group = QGroupBox("5. Intraday Settings")
        intra_layout = QHBoxLayout()
        
        self.chk_intraday = QCheckBox("Intraday Mode")
        self.chk_intraday.setChecked(True)
        self.chk_intraday.stateChanged.connect(self.toggle_intraday)
        
        self.time_start = QTimeEdit()
        self.time_start.setDisplayFormat("HH:mm")
        self.time_start.setTime(QTime(9, 16))
        
        self.time_stop = QTimeEdit()
        self.time_stop.setDisplayFormat("HH:mm")
        self.time_stop.setTime(QTime(15, 15))
        
        intra_layout.addWidget(self.chk_intraday)
        intra_layout.addWidget(QLabel("Start:"))
        intra_layout.addWidget(self.time_start)
        intra_layout.addWidget(QLabel("Stop:"))
        intra_layout.addWidget(self.time_stop)
        intra_group.setLayout(intra_layout)

        # 6. Instrument & Capital Settings
        cap_group = QGroupBox("6. Instrument & Capital")
        cap_layout = QGridLayout()

        self.rb_spot = QRadioButton("Spot")
        self.rb_future = QRadioButton("Future")
        self.rb_future.setChecked(True)
        self.rb_future.toggled.connect(self.toggle_instrument)
        
        self.spin_lot = QSpinBox()
        self.spin_lot.setRange(1, 100000)
        self.spin_lot.setValue(65)
        
        self.spin_capital = QDoubleSpinBox()
        self.spin_capital.setRange(100.0, 1000000000.0)
        self.spin_capital.setValue(100000.0)
        self.spin_capital.setPrefix("") 
        
        cap_layout.addWidget(QLabel("Type:"), 0, 0)
        cap_layout.addWidget(self.rb_spot, 0, 1)
        cap_layout.addWidget(self.rb_future, 0, 2)
        
        cap_layout.addWidget(QLabel("Lot Size:"), 0, 3)
        cap_layout.addWidget(self.spin_lot, 0, 4)
        
        cap_layout.addWidget(QLabel("Initial Capital:"), 0, 5)
        cap_layout.addWidget(self.spin_capital, 0, 6)
        
        cap_group.setLayout(cap_layout)

        # 7. Trade Analysis Settings
        analysis_group = QGroupBox("7. Trade Analysis Settings")
        analysis_layout = QGridLayout()

        analysis_layout.addWidget(QLabel("Timeframe:"), 0, 0)
        self.combo_analysis_tf = QComboBox()
        self.combo_analysis_tf.addItems(["3m", "1m"])  # Default 3m first
        analysis_layout.addWidget(self.combo_analysis_tf, 0, 1)

        analysis_layout.addWidget(QLabel("Swing Lookback:"), 0, 2)
        self.spin_lookback = QSpinBox()
        self.spin_lookback.setRange(1, 100)
        self.spin_lookback.setValue(10) # Default
        analysis_layout.addWidget(self.spin_lookback, 0, 3)

        self.chk_losing_analysis = QCheckBox("Losing Trade Analysis")
        self.chk_losing_analysis.setToolTip("Generate a separate detailed report for losing trades")
        analysis_layout.addWidget(self.chk_losing_analysis, 1, 0, 1, 2)
        
        self.chk_debug_mode = QCheckBox("Debug Mode (Save CSV)")
        self.chk_debug_mode.setToolTip("Generate detailed CSV files for debugging strategy signals")
        analysis_layout.addWidget(self.chk_debug_mode, 1, 2, 1, 2)
        
        analysis_group.setLayout(analysis_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.btn_regime = QPushButton("Market Regimes")
        self.btn_regime.clicked.connect(self.run_market_regime)
        self.btn_regime.setEnabled(False) # Depend on data
        
        self.btn_run = QPushButton("Run Backtest")
        self.btn_run.clicked.connect(self.accept_selection)
        self.btn_run.setEnabled(False) # Depend on data

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        
        button_layout.addWidget(self.btn_regime)
        button_layout.addStretch()
        button_layout.addWidget(btn_cancel)
        button_layout.addWidget(self.btn_run)
        
        # Assemble
        main_layout.addWidget(file_group)
        main_layout.addLayout(top_layout)
        main_layout.addLayout(mid_layout)
        main_layout.addWidget(intra_group)
        main_layout.addWidget(cap_group)
        main_layout.addWidget(analysis_group)
        main_layout.addLayout(button_layout)
        
        # Styles
        self.setStyleSheet("""
            QWidget { 
                background-color: #1e1e1e; 
                color: #e0e0e0; 
                font-family: 'Segoe UI', sans-serif;
            }
            QDialog { 
                background-color: #1e1e1e; 
            }
            QGroupBox { 
                font-weight: bold; 
                border: 1px solid #3e3e3e; 
                border-radius: 6px; 
                margin-top: 10px; 
                padding: 12px; 
                background-color: #252526;
            }
            QGroupBox::title { 
                subcontrol-origin: margin; 
                left: 10px; 
                padding: 0 5px; 
                color: #569cd6;
                background-color: #252526;
            }
            QListWidget {
                background-color: #333333;
                border: 1px solid #3e3e3e;
                border-radius: 4px;
                color: #cccccc;
            }
            QListWidget::item:selected {
                background-color: #094771;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: #2a2d2e;
            }
            QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox {
                background-color: #3c3c3c;
                border: 1px solid #3e3e3e;
                color: #cccccc;
                padding: 4px;
                border-radius: 3px;
            }
            QComboBox::drop-down {
                border: none;
                background: #3c3c3c;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #cccccc;
                margin-right: 5px;
            }
            QPushButton { 
                padding: 8px 16px; 
                background-color: #0e639c; 
                color: white; 
                border-radius: 4px; 
                font-weight: bold; 
                border: none;
            }
            QPushButton:hover { 
                background-color: #1177bb; 
            }
            QPushButton:disabled { 
                background-color: #333333; 
                color: #666666; 
                border: 1px solid #3e3e3e;
            }
            QCheckBox, QRadioButton {
                spacing: 6px;
                color: #cccccc;
            }
            QCheckBox::indicator, QRadioButton::indicator {
                width: 14px;
                height: 14px;
                background-color: #3c3c3c;
                border: 1px solid #555555;
                border-radius: 2px;
            }
            QRadioButton::indicator {
                border-radius: 7px;
            }
            QCheckBox::indicator:checked {
                background-color: #0e639c;
                border-color: #0e639c;
                image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath stroke='white' stroke-width='4' fill='none' stroke-linecap='round' stroke-linejoin='round' d='M20 6L9 17l-5-5'/%3E%3C/svg%3E");
            }
            QRadioButton::indicator:checked {
                background-color: #0e639c;
                border-color: #0e639c;
                image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='6' fill='white'/%3E%3C/svg%3E");
            }
            QLabel {
                color: #cccccc;
                background: transparent;
            }
            QCheckBox, QRadioButton {
                background: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #1e1e1e;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #424242;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # Handle initial file
        if initial_file and os.path.exists(initial_file):
             # Set combo to this file if in list, else add it
             # Find in combo
             index = self.combo_files.findData(initial_file)
             if index >= 0:
                 self.combo_files.setCurrentIndex(index)
             else:
                 # It might be in another folder
                 self.combo_files.addItem(os.path.basename(initial_file), initial_file)
                 self.combo_files.setCurrentIndex(self.combo_files.count() - 1)
        elif self.combo_files.count() > 0:
             self.on_file_changed(0) # Load first one

    def refresh_file_list(self):
        self.combo_files.blockSignals(True)
        self.combo_files.clear()
        if self.data_dir.exists():
            files = sorted(list(self.data_dir.glob("*.feather")))
            for f in files:
                self.combo_files.addItem(f.name, str(f))
        self.combo_files.blockSignals(False)
        
    def browse_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Open Data File", str(self.data_dir), "Feather Files (*.feather)")
        if fname:
            # Add to list and select
            self.combo_files.blockSignals(True)
            self.combo_files.addItem(os.path.basename(fname), fname)
            self.combo_files.setCurrentIndex(self.combo_files.count() - 1)
            self.combo_files.blockSignals(False)
            self.on_file_changed(self.combo_files.currentIndex())

    def on_file_changed(self, index):
        file_path = self.combo_files.itemData(index)
        if file_path:
            self.load_dataset(file_path)

    def load_dataset(self, file_path):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.selected_file = file_path
            # Load Data
            loader = DataLoader(file_path)
            data = loader.load_data()
            
            # Extract Metadata
            available_symbols, tf_ranges = self.extract_metadata(data)
            self.timeframe_data = tf_ranges
            
            # Update UI
            self.update_ui_symbols(available_symbols)
            self.update_ui_timeframes(tf_ranges)
            self.update_date_ranges() # Initial date update
            
            self.btn_run.setEnabled(True)
            self.btn_regime.setEnabled(True)
            self.chk_all_sym.setEnabled(True)
            
        except Exception as e:
            QMessageBox.critical(self, "Error Loading File", f"Failed to load {os.path.basename(file_path)}:\n{str(e)}")
            self.btn_run.setEnabled(False)
            self.btn_regime.setEnabled(False)
        finally:
            QApplication.restoreOverrideCursor()

    def extract_metadata(self, data):
        # Identify unique symbols
        available_symbols = sorted(list(set(k[0] for k in data.keys())))
        
        # Calculate date range per timeframe (Global Union)
        tf_ranges = {} # tf_name -> (global_min, global_max)
        
        for (sym, tf), df in data.items():
            if df.empty: continue
            d_min = df['timestamp'].min().to_pydatetime()
            d_max = df['timestamp'].max().to_pydatetime()
            
            if tf not in tf_ranges:
                tf_ranges[tf] = (d_min, d_max)
            else:
                current_min, current_max = tf_ranges[tf]
                tf_ranges[tf] = (min(current_min, d_min), max(current_max, d_max))
                
        return available_symbols, tf_ranges

    def update_ui_symbols(self, symbols):
        self.sym_list.clear()
        self.sym_list.addItems(symbols)
        if self.chk_all_sym.isChecked():
            self.toggle_all_symbols(Qt.Checked)

    def update_ui_timeframes(self, tf_ranges):
        # Clear existing checkboxes
        for i in reversed(range(self.tf_layout_inner.count())): 
            item = self.tf_layout_inner.itemAt(i)
            widget = item.widget()
            if widget:
                widget.setParent(None)
            else:
                self.tf_layout_inner.removeItem(item)
        self.tf_checkboxes = {}
        
        # Add new ones
        for tf in sorted(tf_ranges.keys()):
            cb = QCheckBox(tf)
            cb.setChecked(True)
            cb.stateChanged.connect(self.update_date_ranges)
            self.tf_checkboxes[tf] = cb
            self.tf_layout_inner.addWidget(cb)
        self.tf_layout_inner.addStretch()

    def toggle_instrument(self, state):
        is_future = self.rb_future.isChecked()
        self.spin_lot.setEnabled(is_future)

    def toggle_intraday(self, state):
        enabled = (state == Qt.Checked)
        self.time_start.setEnabled(enabled)
        self.time_stop.setEnabled(enabled)

    def toggle_all_symbols(self, state):
        should_select = (state == Qt.Checked)
        for i in range(self.sym_list.count()):
            self.sym_list.item(i).setSelected(should_select)

    def update_date_ranges(self):
        # 1. Identify selected timeframes
        selected_tfs = [tf for tf, cb in self.tf_checkboxes.items() if cb.isChecked()]
        
        if not selected_tfs:
            self.date_start.setEnabled(False)
            self.date_end.setEnabled(False)
            return
        
        self.date_start.setEnabled(True)
        self.date_end.setEnabled(True)
        
        # 2. Find Intersection of Dates (Common Range)
        # Or Union? User said: "considering the common date among all timeframe"
        # Ideally: Max of Starts, Min of Ends?
        # But if they don't overlap, we have an issue.
        # Let's verify valid ranges first.
        
        min_dates = []
        max_dates = []
        
        for tf in selected_tfs:
            d_min, d_max = self.timeframe_data[tf]
            min_dates.append(d_min)
            max_dates.append(d_max)
            
        # Common Range = [Max(Start), Min(End)]
        global_min = max(min_dates)
        global_max = min(max_dates)
        
        if global_min > global_max:
            # Overlap issue
            # Fallback to Union? Or just warn?
            # Let's default to Union logic for UI limits, but warn?
            # Actually, "common date" usually implies valid intersection.
            # If no intersection, we default to full range but user might select invalid.
            # Let's switch to Union for safety so UI doesn't break.
             global_min = min(min_dates)
             global_max = max(max_dates)
        
        # Convert datetime to QDate
        q_min = QDate(global_min.year, global_min.month, global_min.day)
        q_max = QDate(global_max.year, global_max.month, global_max.day)
        
        # Update UI Limits
        self.date_start.setMinimumDate(q_min)
        self.date_start.setMaximumDate(q_max)
        self.date_end.setMinimumDate(q_min)
        self.date_end.setMaximumDate(q_max)
        
        # Set Defaults (Start to End)
        # Only change if currently outside? Or always reset?
        # Better to reset on TF change to valid range.
        self.date_start.setDate(q_min)
        self.date_end.setDate(q_max)

    def accept_selection(self):
        # Validate Strategy
        if not self.strat_list.selectedItems():
            QMessageBox.warning(self, "Warning", "Please select a strategy.")
            return
        self.selected_strategy = self.strat_list.selectedItems()[0].text()
        
        # Validate Symbols
        self.selected_symbols = [item.text() for item in self.sym_list.selectedItems()]
        if not self.selected_symbols:
            QMessageBox.warning(self, "Warning", "Please select at least one symbol.")
            return

        # Validate Timeframes
        self.selected_timeframes = [tf for tf, cb in self.tf_checkboxes.items() if cb.isChecked()]
        if not self.selected_timeframes:
             QMessageBox.warning(self, "Warning", "Please select at least one timeframe.")
             return
             
        # Dates
        self.start_date = self.date_start.date().toPyDate()
        self.end_date = self.date_end.date().toPyDate()
        
        if self.start_date > self.end_date:
            QMessageBox.warning(self, "Warning", "Start date cannot be after End date.")
            return

        # Intraday
        self.intraday_enabled = self.chk_intraday.isChecked()
        if self.intraday_enabled:
            self.start_time = self.time_start.time().toPyTime()
            self.stop_time = self.time_stop.time().toPyTime()

        # Check Instrument
        self.instrument_type = "Future" if self.rb_future.isChecked() else "Spot"
        self.lot_size = self.spin_lot.value() if self.instrument_type == "Future" else 1
        self.initial_capital = self.spin_capital.value()

        # Trade Analysis
        self.analysis_tf = self.combo_analysis_tf.currentText() # "3m" or "1m"
        self.analysis_lookback = self.spin_lookback.value()
        self.losing_analysis = self.chk_losing_analysis.isChecked()
        self.debug_mode = self.chk_debug_mode.isChecked()

        self.accept()

    def run_market_regime(self):
        """Executes Market Regime Analysis for selected symbols."""
        # 1. Validate Selection
        selected_symbols = [item.text() for item in self.sym_list.selectedItems()]
        if not selected_symbols:
            QMessageBox.warning(self, "Warning", "Please select at least one symbol for Regime Analysis.")
            return
            
        if not self.selected_file:
             QMessageBox.critical(self, "Error", "Data File not selected.")
             return
             
        try:
            # 2. Load Data (On Demand)
            # We need the finest available data for resampling. 
            # DataLoader loads all, let's filter after.
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            loader = DataLoader(self.selected_file)
            all_data = loader.load_data() # Returns dict {(symbol, timeframe): df}
            
            generated_reports = []
            
            for symbol in selected_symbols:
                # Find best resolution data for this symbol
                # Preference: 1m > 3m > 5m > 15m > 1h
                available_tfs = [k[1] for k in all_data.keys() if k[0] == symbol]
                
                if not available_tfs:
                    continue
                    
                # Pick finest
                # Simple logic: Sort by string or custom map. 
                # Assuming standard strings like '1m', '5m'. 1m < 3m.
                # Just take the first one available in a priority list or sort.
                priority = ['1m', '3m', '5m', '15m', '30m', '1h', '1d']
                best_tf = None
                for p in priority:
                    if p in available_tfs:
                        best_tf = p
                        break
                
                if not best_tf:
                    best_tf = available_tfs[0] # Fallback
                
                df = all_data[(symbol, best_tf)]
                
                # 3. Analyze
                oracle = MarketRegimeOracle(symbol, df)
                results = oracle.run_full_report()
                
                # 4. Generate Report
                output_dir = "reports"
                if not os.path.exists(output_dir):
                    os.makedirs(output_dir)
                    
                filename = f"regime_report_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                report_path = os.path.join(output_dir, filename)
                
                generate_regime_html_report(symbol, results, report_path)
                generated_reports.append(report_path)
                
            QApplication.restoreOverrideCursor()
            
            if generated_reports:
                msg = f"Successfully generated {len(generated_reports)} reports.\n" + "\n".join(generated_reports)
                QMessageBox.information(self, "Success", msg)
                
                # Open the last one
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(generated_reports[-1])))
            else:
                QMessageBox.warning(self, "Warning", "No data found for selected symbols.")
                
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error", f"Failed to run analysis: {e}")
            print(e)
            import traceback
            traceback.print_exc()

def get_user_selection(strategies: List[str], input_path: str = None) -> Tuple:
    """
    Returns: (input_path, strategy_name, symbols, timeframes, start_date, end_date, intraday_enabled, start_time, stop_time, instrument_type, lot_size, initial_capital, analysis_tf, analysis_lookback, losing_analysis, debug_mode)
    """
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    dialog = SelectorDialog(strategies, initial_file=input_path)
    if dialog.exec_() == QDialog.Accepted:
        # Convert QDate/PyDate to datetime if needed, or keep as date
        # Returning date objects (YYYY-MM-DD)
        return (dialog.selected_file, dialog.selected_strategy, dialog.selected_symbols, 
                dialog.selected_timeframes, dialog.start_date, dialog.end_date,
                dialog.intraday_enabled, dialog.start_time, dialog.stop_time,
                dialog.instrument_type, dialog.lot_size, dialog.initial_capital,
                dialog.analysis_tf, dialog.analysis_lookback, dialog.losing_analysis, dialog.debug_mode)
    return None, None, [], [], None, None, False, None, None, "Spot", 1, 100000.0, "3m", 10, False, False

