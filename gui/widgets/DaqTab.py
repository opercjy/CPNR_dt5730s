import os
import shutil
import configparser
import json
import zmq
import re
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
                             QPushButton, QLineEdit, QLabel, QTextEdit, 
                             QGroupBox, QSpinBox, QComboBox, QFileDialog, QCheckBox)
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtCore import QTimer, QSettings, QThread, pyqtSignal
from core.ProcessManager import ProcessManager
from core.DatabaseManager import DatabaseManager

class CtrlReceiver(QThread):
    run_completed = pyqtSignal()
    stat_received = pyqtSignal(dict)

    def __init__(self, ports=[5555, 5556]):
        super().__init__()
        self.ports = ports
        self.running = True

    def run(self):
        context = zmq.Context.instance()
        socket = context.socket(zmq.SUB)
        
        for port in self.ports:
            socket.connect(f"tcp://127.0.0.1:{port}")
        
        socket.setsockopt_string(zmq.SUBSCRIBE, "CTRL")
        socket.setsockopt_string(zmq.SUBSCRIBE, "STAT")

        while self.running:
            try:
                if socket.poll(100):
                    frames = socket.recv_multipart()
                    if len(frames) == 2:
                        if frames[0] == b"CTRL" and frames[1] == b"RUN_COMPLETED":
                            self.run_completed.emit()
                        elif frames[0] == b"STAT":
                            try:
                                stat_data = json.loads(frames[1].decode('utf-8'))
                                self.stat_received.emit(stat_data)
                            except: pass
            except Exception as e:
                pass
        socket.close()

    def stop(self):
        self.running = False
        self.wait()


class DaqTab(QWidget):
    def __init__(self, parent=None, env_data_provider=None):
        super().__init__(parent)
        self.env_data_provider = env_data_provider
        
        self.daq_processes = []
        self.running_processes_count = 0
        self.batch_success = True
        
        curr = os.path.abspath(os.path.dirname(__file__))
        while curr != '/' and not os.path.exists(os.path.join(curr, 'CMakeLists.txt')):
            curr = os.path.dirname(curr)
        self.proj_dir = curr if curr != '/' else os.getcwd()
        
        self.bin_dir = os.path.join(self.proj_dir, "build", "bin")
        self.data_dir = os.path.join(self.proj_dir, "data")
        self.config_dir = os.path.join(self.proj_dir, "config")
        
        os.makedirs(self.data_dir, exist_ok=True)
        self.settings = QSettings("CPNR", "DT5730_DAQTab")
        self.db = DatabaseManager(os.path.join(self.data_dir, "run_history.db"))
        
        self.current_batch = 0; self.total_batches = 1
        self.base_output_path = ""; self.scan_values = [] 
        self.last_stats = {}; self.current_run_id = -1
        self.is_recovering = False
        
        self.setup_ui()
        self.load_settings()

        self.disk_timer = QTimer(self)
        self.disk_timer.timeout.connect(self.update_disk_space)
        self.disk_timer.start(1000)
        self.update_disk_space()

        self.watchdog_timer = QTimer(self)
        self.watchdog_timer.timeout.connect(self.trigger_watchdog_recovery)

        self.ctrl_receiver = CtrlReceiver()
        self.ctrl_receiver.run_completed.connect(self.on_run_completed_received)
        self.ctrl_receiver.stat_received.connect(self.on_stat_received)
        self.ctrl_receiver.start()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        file_group = QGroupBox("File & Configuration Environment")
        file_layout = QGridLayout()
        file_layout.addWidget(QLabel("Config (.conf):"), 0, 0)
        self.config_input = QLineEdit("config/dt5730s_master.conf")
        file_layout.addWidget(self.config_input, 0, 1)
        self.btn_browse_config = QPushButton("Browse")
        self.btn_browse_config.clicked.connect(self.browse_config)
        file_layout.addWidget(self.btn_browse_config, 0, 2)

        file_layout.addWidget(QLabel("Output (.dat):"), 1, 0)
        self.output_input = QLineEdit("data/data_run.dat")
        file_layout.addWidget(self.output_input, 1, 1)
        self.btn_browse_output = QPushButton("Browse")
        self.btn_browse_output.clicked.connect(self.browse_output)
        file_layout.addWidget(self.btn_browse_output, 1, 2)

        file_layout.addWidget(QLabel("Run Metadata:"), 2, 0)
        env_layout = QHBoxLayout()
        self.operator_input = QLineEdit("Unknown")
        self.hv_input = QLineEdit("0V")
        self.temp_input = QLineEdit("20.0")
        env_layout.addWidget(QLabel("Operator:")); env_layout.addWidget(self.operator_input)
        env_layout.addWidget(QLabel("  |  Applied HV:")); env_layout.addWidget(self.hv_input)
        env_layout.addWidget(QLabel("  |  Room Temp (°C):")); env_layout.addWidget(self.temp_input)
        file_layout.addLayout(env_layout, 2, 1, 1, 2)
        file_group.setLayout(file_layout); layout.addWidget(file_group)

        cond_group = QGroupBox("Run Conditions & Mode")
        cond_main_layout = QVBoxLayout()
        cond_layout1 = QHBoxLayout()
        cond_layout1.addWidget(QLabel("Max Events:"))
        self.spin_events = QSpinBox(); self.spin_events.setRange(0, 2000000000)
        cond_layout1.addWidget(self.spin_events)
        cond_layout1.addWidget(QLabel("Max Time (sec):"))
        self.spin_time = QSpinBox(); self.spin_time.setRange(0, 86400)
        cond_layout1.addWidget(self.spin_time)
        cond_layout1.addWidget(QLabel("Run Mode:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Single Continuous", "Split/Batch Mode", "Auto Threshold Scan"])
        self.combo_mode.currentIndexChanged.connect(self.toggle_batch_mode)
        cond_layout1.addWidget(self.combo_mode)
        self.lbl_batch = QLabel("Batches:")
        self.spin_batch = QSpinBox(); self.spin_batch.setRange(2, 999); self.spin_batch.setEnabled(False)
        cond_layout1.addWidget(self.lbl_batch); cond_layout1.addWidget(self.spin_batch)
        
        self.chk_inf_repeat = QCheckBox("Infinite Auto-Repeat")
        self.chk_inf_repeat.setStyleSheet("font-weight: bold; color: #198754;")
        cond_layout1.addWidget(self.chk_inf_repeat)
        cond_main_layout.addLayout(cond_layout1)
        
        self.scan_layout = QHBoxLayout()
        self.scan_layout.addWidget(QLabel("Scan Range (ADC):"))
        self.scan_layout.addWidget(QLabel("Start:")); self.spin_scan_start = QSpinBox(); self.spin_scan_start.setRange(0, 16383); self.spin_scan_start.setValue(500)
        self.scan_layout.addWidget(self.spin_scan_start)
        self.scan_layout.addWidget(QLabel("End:")); self.spin_scan_end = QSpinBox(); self.spin_scan_end.setRange(0, 16383); self.spin_scan_end.setValue(600)
        self.scan_layout.addWidget(self.spin_scan_end)
        self.scan_layout.addWidget(QLabel("Step:")); self.spin_scan_step = QSpinBox(); self.spin_scan_step.setRange(1, 1000); self.spin_scan_step.setValue(5)
        self.scan_layout.addWidget(self.spin_scan_step)
        self.set_scan_enabled(False)
        cond_main_layout.addLayout(self.scan_layout); cond_group.setLayout(cond_main_layout)
        layout.addWidget(cond_group)

        dash_group = QGroupBox("Real-time Status Dashboard (Dual Board Mixed)")
        dash_layout = QGridLayout()
        lbl_style = "font-weight: bold; color: #495057; font-size: 13px;"
        self.val_style = "font-weight: bold; font-size: 14px; background-color: #e9ecef; color: #0d6efd; padding: 4px; border: 1px solid #ced4da; border-radius: 4px;"
        self.val_style_warn = "font-weight: bold; font-size: 14px; background-color: #f8d7da; color: #dc3545; padding: 4px; border: 1px solid #f5c2c7; border-radius: 4px;"
        
        dash_layout.addWidget(QLabel("Storage:", styleSheet=lbl_style), 0, 0); self.val_disk = QLabel("Checking...", styleSheet=self.val_style); dash_layout.addWidget(self.val_disk, 0, 1)
        dash_layout.addWidget(QLabel("Batch/Scan:", styleSheet=lbl_style), 0, 2); self.val_batch = QLabel("1/1", styleSheet=self.val_style); dash_layout.addWidget(self.val_batch, 0, 3)
        dash_layout.addWidget(QLabel("Time:", styleSheet=lbl_style), 0, 4); self.val_time = QLabel("00:00", styleSheet=self.val_style); dash_layout.addWidget(self.val_time, 0, 5)
        dash_layout.addWidget(QLabel("Events:", styleSheet=lbl_style), 0, 6); self.val_events = QLabel("0", styleSheet=self.val_style); dash_layout.addWidget(self.val_events, 0, 7)
        dash_layout.addWidget(QLabel("Trg Rate:", styleSheet=lbl_style), 1, 0); self.val_rate = QLabel("0.0 Hz", styleSheet=self.val_style); dash_layout.addWidget(self.val_rate, 1, 1)
        dash_layout.addWidget(QLabel("Data Speed:", styleSheet=lbl_style), 1, 2); self.val_speed = QLabel("0.00 MB/s", styleSheet=self.val_style); dash_layout.addWidget(self.val_speed, 1, 3)
        dash_layout.addWidget(QLabel("ZMQ Drops:", styleSheet=lbl_style), 1, 4); self.val_drops = QLabel("0", styleSheet=self.val_style); dash_layout.addWidget(self.val_drops, 1, 5)
        dash_layout.addWidget(QLabel("Board Temp:", styleSheet=lbl_style), 1, 6)
        self.val_board_temp = QLabel("0 °C", styleSheet=self.val_style)
        dash_layout.addWidget(self.val_board_temp, 1, 7)
        
        dash_group.setLayout(dash_layout); layout.addWidget(dash_group)

        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start DUAL DAQ")
        self.btn_start.setStyleSheet("background-color: #0d6efd; color: white; font-weight: bold; padding: 10px; font-size: 14px;")
        self.btn_start.clicked.connect(self.start_daq_sequence)
        self.btn_stop = QPushButton("Stop DAQ")
        self.btn_stop.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold; padding: 10px; font-size: 14px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_all)
        btn_layout.addWidget(self.btn_start); btn_layout.addWidget(self.btn_stop); layout.addLayout(btn_layout)

        self.terminal = QTextEdit(); self.terminal.setReadOnly(True); self.terminal.setFont(QFont("Monospace", 10))
        self.terminal.setStyleSheet("background-color: #000000; color: #ffffff; border: 1px solid #ced4da;") # 블랙 테마
        self.terminal.setLineWrapMode(QTextEdit.NoWrap) 
        layout.addWidget(self.terminal)

    def load_settings(self):
        saved_config = self.settings.value("last_config", "config/dt5730s_master.conf")
        self.config_input.setText(saved_config)
        self.output_input.setText(self.settings.value("last_output", "data/data_run.dat"))
        self.spin_events.setValue(int(self.settings.value("last_events", 0)))
        self.spin_time.setValue(int(self.settings.value("last_time", 20))) 
        if saved_config: self.parse_env_from_config(saved_config)

    def save_settings(self):
        self.settings.setValue("last_config", self.config_input.text()); self.settings.setValue("last_output", self.output_input.text())
        self.settings.setValue("last_events", self.spin_events.value()); self.settings.setValue("last_time", self.spin_time.value())

    def parse_env_from_config(self, filepath):
        full_path = os.path.abspath(os.path.join(self.proj_dir, filepath))
        if not os.path.exists(full_path): return
        cfg = configparser.ConfigParser(); cfg.optionxform = str; cfg.read(full_path)
        if cfg.has_section("Environment"):
            self.operator_input.setText(cfg.get("Environment", "Operator", fallback="Unknown"))
            self.hv_input.setText(cfg.get("Environment", "AppliedHV", fallback="0V"))
            self.temp_input.setText(cfg.get("Environment", "Temperature", fallback="20.0"))

    def set_scan_enabled(self, enabled):
        self.spin_scan_start.setEnabled(enabled); self.spin_scan_end.setEnabled(enabled); self.spin_scan_step.setEnabled(enabled)

    def toggle_batch_mode(self, idx):
        self.spin_batch.setEnabled(idx == 1); self.set_scan_enabled(idx == 2)

    def browse_config(self):
        default_dir = os.path.abspath(os.path.join(self.proj_dir, "config"))
        path, _ = QFileDialog.getOpenFileName(self, "Select Config File", default_dir, "Config Files (*.conf *.ini);;All Files (*)")
        if path: 
            self.config_input.setText(os.path.relpath(path, self.proj_dir))
            self.parse_env_from_config(path); self.save_settings()

    def browse_output(self):
        default_dir = os.path.abspath(os.path.join(self.proj_dir, "data"))
        path, _ = QFileDialog.getSaveFileName(self, "Select Output File", default_dir, "Data Files (*.dat);;All Files (*)")
        if path: self.output_input.setText(os.path.relpath(path, self.proj_dir)); self.save_settings()

    def update_disk_space(self):
        os.makedirs(self.data_dir, exist_ok=True)
        total, used, free = shutil.disk_usage(self.data_dir)
        free_gb = free / (2**30)
        self.val_disk.setStyleSheet(self.val_style_warn if free_gb < 10.0 else self.val_style); self.val_disk.setText(f"{free_gb:.1f} GB")

    def append_log(self, text):
        safe_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        # 🚀 C++ ANSI 색상 코드를 HTML 색상으로 변환
        html_text = safe_text.replace('\033[1;36m', '<span style="color:#0dcaf0; font-weight:bold;">') \
                             .replace('\033[1;32m', '<span style="color:#28a745; font-weight:bold;">') \
                             .replace('\033[1;33m', '<span style="color:#ffc107; font-weight:bold;">') \
                             .replace('\033[1;35m', '<span style="color:#e83e8c; font-weight:bold;">') \
                             .replace('\033[1;31m', '<span style="color:#dc3545; font-weight:bold;">') \
                             .replace('\033[1m', '<b>').replace('\033[0m', '</span></b>')
        
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        html_text = ansi_escape.sub('', html_text)
        
        if html_text.strip():
            self.terminal.append(html_text)
            self.terminal.moveCursor(QTextCursor.End)
            self.terminal.horizontalScrollBar().setValue(0)

    def update_dashboard(self, stats):
        self.last_stats.update(stats)
        self.val_time.setText(stats.get('time', '00:00'))
        self.val_events.setText(stats.get('events', '0'))
        self.val_rate.setText(stats.get('rate', '0.0 Hz'))
        self.val_speed.setText(stats.get('speed', '0.00 MB/s')) 
        drops = int(stats.get('drops', '0'))
        self.val_drops.setStyleSheet(self.val_style_warn if drops > 0 else self.val_style); self.val_drops.setText(str(drops))
        
        if self.watchdog_timer.isActive():
            self.watchdog_timer.start(30000)

    def on_stat_received(self, data):
        if "temp" in data:
            temp = data["temp"]
            self.last_stats['board_temp'] = temp
            self.val_board_temp.setStyleSheet(self.val_style_warn if temp > 65 else self.val_style)
            self.val_board_temp.setText(f"{temp} °C")
        if "live_time" in data:
            self.last_stats['live_time'] = data['live_time']
            self.last_stats['elapsed_time'] = data['elapsed_time']
            self.last_stats['dead_time_pct'] = data['dead_time_pct']

    def start_daq_sequence(self):
        self.save_settings()
        self.base_output_path = self.output_input.text()
        self.current_batch = 1
        mode = self.combo_mode.currentIndex()
        if mode == 0: self.total_batches = 1
        elif mode == 1: self.total_batches = self.spin_batch.value()
        elif mode == 2:
            start = self.spin_scan_start.value(); end = self.spin_scan_end.value(); step = self.spin_scan_step.value()
            self.scan_values = list(range(start, end + 1, step)) if start <= end else list(range(start, end - 1, -step))
            self.total_batches = len(self.scan_values)

        self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True); self.combo_mode.setEnabled(False)
        self.run_single_batch()

    def run_single_batch(self):
        try:
            self.is_recovering = False
            self.last_stats = {}
            self.batch_success = True
            
            if self.chk_inf_repeat.isChecked():
                self.val_batch.setText(f"{self.current_batch} / Inf")
            else:
                self.val_batch.setText(f"{self.current_batch} / {self.total_batches}")
            
            output_file = self.base_output_path
            name, ext = os.path.splitext(self.base_output_path)
            mode = self.combo_mode.currentIndex()
            
            config_path_str = self.config_input.text()
            config_full = os.path.abspath(os.path.join(self.proj_dir, config_path_str))

            current_env_data = {
                "Operator": self.operator_input.text().strip(),
                "Applied HV": self.hv_input.text().strip(),
                "Temperature (C)": self.temp_input.text().strip()
            }
            if self.env_data_provider: current_env_data.update(self.env_data_provider())

            db_output_name = f"{name}_part{self.current_batch:04d}_B0{ext}" if (mode == 1 or self.chk_inf_repeat.isChecked()) else f"{name}_B0{ext}"
            self.current_run_id = self.db.record_run_start(db_output_name, current_env_data, config_full)
            
            self.append_log(f"<br><span style='color:#0dcaf0; font-weight:bold;'>========== [ DUAL DAQ Batch {self.current_batch} Started ] ==========</span>")
            
            exe_path = os.path.join(self.bin_dir, "frontend_dt5730")

            # 🚀 마이크로서비스: 2개의 C++ 프로세스 독립 런칭
            NUM_BOARDS = 2
            self.daq_processes.clear()
            self.running_processes_count = NUM_BOARDS

            for board_idx in range(NUM_BOARDS):
                if mode == 1 or self.chk_inf_repeat.isChecked(): 
                    out_file_b = f"{name}_part{self.current_batch:04d}_B{board_idx}{ext}"
                elif mode == 2:
                    current_th = self.scan_values[self.current_batch - 1]
                    out_file_b = f"{name}_th{current_th}_B{board_idx}{ext}"
                else:
                    out_file_b = f"{name}_B{board_idx}{ext}"

                out_file_full = os.path.abspath(os.path.join(self.proj_dir, out_file_b))
                os.makedirs(os.path.dirname(out_file_full), exist_ok=True)

                port = str(5555 + board_idx)
                link = str(board_idx)

                cmd = [exe_path, "-c", config_path_str, "-o", out_file_b, "-l", link, "-p", port]
                if self.spin_events.value() > 0: cmd.extend(["-n", str(self.spin_events.value())])
                if self.spin_time.value() > 0: cmd.extend(["-t", str(self.spin_time.value())])

                proc = ProcessManager(cmd, cwd=self.proj_dir)
                proc.log_signal.connect(self.append_log)
                proc.stat_signal.connect(self.update_dashboard)
                proc.finished_signal.connect(self.on_batch_finished)
                
                self.daq_processes.append(proc)
                proc.start() 
            
            self.watchdog_timer.start(30000)

        except Exception as e:
            self.append_log(f"<br><span style='color:#dc3545; font-size:14px;'><b>[CRITICAL ERROR] DAQ Start Failed: {str(e)}</b></span>")
            self.stop_all()

    def trigger_watchdog_recovery(self):
        self.watchdog_timer.stop()
        self.is_recovering = True 
        self.append_log("<br><span style='color:#dc3545; font-size:14px;'><b>[FATAL] DAQ Timeout (30s). Killing zombies...</b></span>")
        self.stop_all()

    def on_batch_finished(self, returncode):
        if returncode != 0:
            self.batch_success = False
            
        self.running_processes_count -= 1
        
        if self.running_processes_count <= 0:
            self.watchdog_timer.stop() 
            self.append_log(f"<br><span style='color:#6c757d; font-weight:bold;'>>>> All Dual-Board Processes Exited.</span>")
            
            if self.current_run_id > 0 and self.last_stats:
                self.db.update_daq_summary(self.current_run_id, self.last_stats)

            if self.batch_success:
                if self.chk_inf_repeat.isChecked():
                    self.current_batch += 1
                    self.total_batches = max(self.total_batches, self.current_batch)
                    QTimer.singleShot(2000, self.run_single_batch)
                elif self.current_batch < self.total_batches:
                    self.current_batch += 1
                    self.run_single_batch()
                else:
                    self.append_log("<br><span style='color:#0dcaf0; font-weight:bold;'>========== [ All DAQ Sequences Completed ] ==========</span>")
                    self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False); self.combo_mode.setEnabled(True)
            else:
                self.append_log("<br><span style='color:#ffc107; font-weight:bold;'>[Warning] Process exited abnormally.</span>")
                self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False); self.combo_mode.setEnabled(True)

    def on_run_completed_received(self):
        pass

    def stop_all(self):
        self.watchdog_timer.stop() 
        self.total_batches = 0 
        self.chk_inf_repeat.setChecked(False) 
        self.append_log("<br><span style='color:#dc3545; font-weight:bold;'>[System] DAQ manually stopped.</span>")
        
        for proc in self.daq_processes:
            if proc and proc.isRunning():
                proc.stop()
                
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.combo_mode.setEnabled(True)

    def closeEvent(self, event):
        self.watchdog_timer.stop()
        self.ctrl_receiver.stop()
        super().closeEvent(event)
