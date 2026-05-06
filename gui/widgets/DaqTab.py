import os
import shutil
import configparser
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
                             QPushButton, QLineEdit, QLabel, QTextEdit, 
                             QGroupBox, QSpinBox, QComboBox, QFileDialog)
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtCore import QTimer
from core.ProcessManager import ProcessManager
from core.DatabaseManager import DatabaseManager

class DaqTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.daq_process = None
        self.bin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        
        db_path = os.path.join(self.bin_dir, "data", "run_history.db")
        self.db = DatabaseManager(db_path)
        
        self.current_batch = 0
        self.total_batches = 1
        self.base_output_path = ""
        self.scan_values = [] # 스캔 모드 시 적용될 임계값 리스트
        
        self.setup_ui()

        self.disk_timer = QTimer(self)
        self.disk_timer.timeout.connect(self.update_disk_space)
        self.disk_timer.start(1000)
        self.update_disk_space()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # --- File & Environment ---
        file_group = QGroupBox("File & Environment")
        file_layout = QGridLayout()
        file_layout.addWidget(QLabel("Config:"), 0, 0)
        self.config_input = QLineEdit("../config/dt5730s_ls_coin.conf")
        file_layout.addWidget(self.config_input, 0, 1)
        self.btn_browse_config = QPushButton("📂 Browse")
        self.btn_browse_config.clicked.connect(self.browse_config)
        file_layout.addWidget(self.btn_browse_config, 0, 2)

        file_layout.addWidget(QLabel("Base Output (.dat):"), 1, 0)
        self.output_input = QLineEdit("../data/data_run.dat")
        file_layout.addWidget(self.output_input, 1, 1)
        self.btn_browse_output = QPushButton("📂 Browse")
        self.btn_browse_output.clicked.connect(self.browse_output)
        file_layout.addWidget(self.btn_browse_output, 1, 2)
        
        file_layout.addWidget(QLabel("Applied HV (Multi-CH):"), 2, 0)
        self.hv_input = QLineEdit("CH0: 900V, CH1: 900V")
        file_layout.addWidget(self.hv_input, 2, 1)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # --- Run Conditions & Mode ---
        cond_group = QGroupBox("Run Conditions & Mode")
        cond_main_layout = QVBoxLayout()
        
        cond_layout1 = QHBoxLayout()
        cond_layout1.addWidget(QLabel("Max Events:"))
        self.spin_events = QSpinBox(); self.spin_events.setRange(0, 2000000000); self.spin_events.setValue(0)
        cond_layout1.addWidget(self.spin_events)

        cond_layout1.addWidget(QLabel("Max Time (sec):"))
        self.spin_time = QSpinBox(); self.spin_time.setRange(0, 86400); self.spin_time.setValue(3600)
        cond_layout1.addWidget(self.spin_time)

        cond_layout1.addWidget(QLabel("Run Mode:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Single Continuous", "Split/Batch Mode", "Auto Threshold Scan"])
        self.combo_mode.currentIndexChanged.connect(self.toggle_batch_mode)
        cond_layout1.addWidget(self.combo_mode)

        self.lbl_batch = QLabel("Batches:")
        self.spin_batch = QSpinBox(); self.spin_batch.setRange(2, 999); self.spin_batch.setValue(10); self.spin_batch.setEnabled(False)
        cond_layout1.addWidget(self.lbl_batch)
        cond_layout1.addWidget(self.spin_batch)
        cond_main_layout.addLayout(cond_layout1)

        # [신규 탑재] 임계값 자동 스캔 레이아웃
        self.scan_layout = QHBoxLayout()
        self.scan_layout.addWidget(QLabel("🚀 <b>Scan Range (ADC):</b>"))
        
        self.scan_layout.addWidget(QLabel("Start:"))
        self.spin_scan_start = QSpinBox(); self.spin_scan_start.setRange(0, 16383); self.spin_scan_start.setValue(14500)
        self.scan_layout.addWidget(self.spin_scan_start)
        
        self.scan_layout.addWidget(QLabel("End:"))
        self.spin_scan_end = QSpinBox(); self.spin_scan_end.setRange(0, 16383); self.spin_scan_end.setValue(14700)
        self.scan_layout.addWidget(self.spin_scan_end)
        
        self.scan_layout.addWidget(QLabel("Step:"))
        self.spin_scan_step = QSpinBox(); self.spin_scan_step.setRange(1, 1000); self.spin_scan_step.setValue(10)
        self.scan_layout.addWidget(self.spin_scan_step)
        
        # 초기에는 스캔 기능 비활성화 상태
        self.set_scan_enabled(False)
        cond_main_layout.addLayout(self.scan_layout)
        
        cond_group.setLayout(cond_main_layout)
        layout.addWidget(cond_group)

        # --- Real-time Status Dashboard (라이트 테마 적용) ---
        dash_group = QGroupBox("Real-time Status Dashboard")
        dash_layout = QGridLayout()
        lbl_style = "font-weight: bold; color: #495057; font-size: 13px;"
        # 블랙/그린 네온사인을 버리고, 깔끔하고 모던한 연회색 박스로 변경
        self.val_style = "font-weight: bold; font-size: 14px; background-color: #e9ecef; color: #0d6efd; padding: 4px; border: 1px solid #ced4da; border-radius: 4px;"
        self.val_style_warn = "font-weight: bold; font-size: 14px; background-color: #f8d7da; color: #dc3545; padding: 4px; border: 1px solid #f5c2c7; border-radius: 4px;"
        
        dash_layout.addWidget(QLabel("Storage:", styleSheet=lbl_style), 0, 0)
        self.val_disk = QLabel("Checking...", styleSheet=self.val_style)
        dash_layout.addWidget(self.val_disk, 0, 1)

        dash_layout.addWidget(QLabel("Batch/Scan:", styleSheet=lbl_style), 0, 2)
        self.val_batch = QLabel("1/1", styleSheet=self.val_style)
        dash_layout.addWidget(self.val_batch, 0, 3)

        dash_layout.addWidget(QLabel("Time:", styleSheet=lbl_style), 0, 4)
        self.val_time = QLabel("00:00", styleSheet=self.val_style)
        dash_layout.addWidget(self.val_time, 0, 5)

        dash_layout.addWidget(QLabel("Events:", styleSheet=lbl_style), 0, 6)
        self.val_events = QLabel("0", styleSheet=self.val_style)
        dash_layout.addWidget(self.val_events, 0, 7)

        dash_layout.addWidget(QLabel("Trg Rate:", styleSheet=lbl_style), 1, 0)
        self.val_rate = QLabel("0.0 Hz", styleSheet=self.val_style)
        dash_layout.addWidget(self.val_rate, 1, 1)

        dash_layout.addWidget(QLabel("Data Speed:", styleSheet=lbl_style), 1, 2)
        self.val_speed = QLabel("0.00 MB/s", styleSheet=self.val_style)
        dash_layout.addWidget(self.val_speed, 1, 3)

        dash_layout.addWidget(QLabel("ZMQ Drops:", styleSheet=lbl_style), 1, 4)
        self.val_drops = QLabel("0", styleSheet=self.val_style)
        dash_layout.addWidget(self.val_drops, 1, 5)

        dash_group.setLayout(dash_layout)
        layout.addWidget(dash_group)

        # --- Controls & Terminal ---
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ Start DAQ")
        self.btn_start.setStyleSheet("background-color: #0d6efd; color: white; font-weight: bold; padding: 10px; font-size: 14px;")
        self.btn_start.clicked.connect(self.start_daq_sequence)

        self.btn_stop = QPushButton("■ Stop DAQ")
        self.btn_stop.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold; padding: 10px; font-size: 14px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_all)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)

        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setFont(QFont("Monospace", 10))
        self.terminal.setStyleSheet("background-color: #ffffff; color: #212529; border: 1px solid #ced4da;")
        layout.addWidget(self.terminal)

    def set_scan_enabled(self, enabled):
        self.spin_scan_start.setEnabled(enabled)
        self.spin_scan_end.setEnabled(enabled)
        self.spin_scan_step.setEnabled(enabled)

    def toggle_batch_mode(self, idx):
        self.spin_batch.setEnabled(idx == 1)
        self.set_scan_enabled(idx == 2)

    def browse_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Config File", self.bin_dir, "Config Files (*.conf *.ini);;All Files (*)")
        if path: self.config_input.setText(os.path.relpath(path, self.bin_dir))

    def browse_output(self):
        default_dir = os.path.abspath(os.path.join(self.bin_dir, "../data"))
        path, _ = QFileDialog.getSaveFileName(self, "Select Output File", default_dir, "Data Files (*.dat);;All Files (*)")
        if path: self.output_input.setText(os.path.relpath(path, self.bin_dir))

    def update_disk_space(self):
        target_dir = os.path.abspath(os.path.join(self.bin_dir, "..", "data"))
        os.makedirs(target_dir, exist_ok=True)
        total, used, free = shutil.disk_usage(target_dir)
        free_gb = free / (2**30)
        
        if free_gb < 10.0:
            self.val_disk.setStyleSheet(self.val_style_warn)
        else:
            self.val_disk.setStyleSheet(self.val_style)
        self.val_disk.setText(f"{free_gb:.1f} GB")

    def append_log(self, text):
        safe_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        color = "#212529" 
        bold = False
        
        if "[LIVE DAQ]" in safe_text: color = "#0d6efd"; bold = True
        elif "[Frontend]" in safe_text: color = "#198754"; bold = True
        elif "[DAQManager]" in safe_text: color = "#0dcaf0" 
        elif "[DB]" in safe_text: color = "#6f42c1" 
        elif "[Warning]" in safe_text or "Error" in safe_text or "Failed" in safe_text: color = "#dc3545"; bold = True
        elif "===" in safe_text or "---" in safe_text: color = "#6c757d"; bold = True
        elif safe_text.strip().startswith("[") and "]" in safe_text: color = "#d63384" 
            
        b_open = "<b>" if bold else ""
        b_close = "</b>" if bold else ""
        html_line = f'<span style="color: {color};">{b_open}{safe_text}{b_close}</span>'
        self.terminal.append(html_line)
        self.terminal.moveCursor(QTextCursor.End)

    def update_dashboard(self, stats):
        self.val_time.setText(stats.get('time', '00:00'))
        self.val_events.setText(stats.get('events', '0'))
        self.val_rate.setText(stats.get('rate', '0.0 Hz'))
        self.val_speed.setText(stats.get('speed', '0.00 MB/s')) 
        
        drops = int(stats.get('drops', '0'))
        if drops > 0: self.val_drops.setStyleSheet(self.val_style_warn)
        else: self.val_drops.setStyleSheet(self.val_style)
        self.val_drops.setText(str(drops))

    def start_daq_sequence(self):
        self.base_output_path = self.output_input.text()
        self.current_batch = 1
        
        mode = self.combo_mode.currentIndex()
        if mode == 0:   # Single
            self.total_batches = 1
        elif mode == 1: # Batch
            self.total_batches = self.spin_batch.value()
        elif mode == 2: # Threshold Scan
            start = self.spin_scan_start.value()
            end = self.spin_scan_end.value()
            step = self.spin_scan_step.value()
            if start <= end:
                self.scan_values = list(range(start, end + 1, step))
            else:
                self.scan_values = list(range(start, end - 1, -step))
            self.total_batches = len(self.scan_values)

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.combo_mode.setEnabled(False)
        self.run_single_batch()

    def run_single_batch(self):
        self.val_batch.setText(f"{self.current_batch} / {self.total_batches}")
        output_file = self.base_output_path
        name, ext = os.path.splitext(self.base_output_path)
        
        config_path_str = self.config_input.text()
        if config_path_str.startswith("config/"):
            config_path_str = "../" + config_path_str
            self.config_input.setText(config_path_str)
        config_full = os.path.abspath(os.path.join(self.bin_dir, config_path_str))

        # --- [핵심] 모드에 따른 파일명 및 하드웨어 제어 ---
        mode = self.combo_mode.currentIndex()
        if mode == 1: # 일반 분할
            output_file = f"{name}_part{self.current_batch:02d}{ext}"
        elif mode == 2: # 스캔 모드: 파일명에 임계값 명시 및 .conf 동적 수정
            current_th = self.scan_values[self.current_batch - 1]
            output_file = f"{name}_th{current_th}{ext}"
            
            # 파이썬으로 config 파일을 즉석에서 까서 활성 채널의 Threshold를 덮어씁니다.
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(config_full)
            for sec in config.sections():
                if sec.startswith("Channel_"):
                    config.set(sec, "TriggerThreshold", str(current_th))
            with open(config_full, 'w') as f:
                config.write(f)
            self.append_log(f"\n[SCAN AUTOMATION] Target Threshold updated to {current_th} ADC.")

        run_id = self.db.record_run_start(output_file, self.hv_input.text(), config_full)
        
        self.append_log(f"\n========== [ Batch/Scan {self.current_batch}/{self.total_batches} Started ] ==========")
        self.append_log(f"--- Output: {output_file} | DB ID: {run_id} | HV: {self.hv_input.text()} ---")
        
        cmd = ["./frontend_dt5730", "-c", config_full, "-o", output_file]
        if self.spin_events.value() > 0: cmd.extend(["-n", str(self.spin_events.value())])
        if self.spin_time.value() > 0: cmd.extend(["-t", str(self.spin_time.value())])

        self.daq_process = ProcessManager(cmd, cwd=self.bin_dir)
        self.daq_process.log_signal.connect(self.append_log)
        self.daq_process.stat_signal.connect(self.update_dashboard)
        self.daq_process.finished_signal.connect(self.on_batch_finished)
        self.daq_process.start()

    def on_batch_finished(self, returncode):
        self.append_log(f">>> Process Exited (Code: {returncode})")
        if self.current_batch < self.total_batches and returncode == 0:
            self.current_batch += 1
            self.run_single_batch()
        else:
            self.append_log("\n========== [ All DAQ Sequences Completed ] ==========")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.combo_mode.setEnabled(True)

    def stop_all(self):
        self.total_batches = 0 
        if self.daq_process and self.daq_process.isRunning():
            self.daq_process.stop()