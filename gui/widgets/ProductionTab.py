import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
                             QPushButton, QLineEdit, QLabel, QTextEdit, 
                             QGroupBox, QSpinBox, QCheckBox, QFileDialog)
from PyQt5.QtGui import QFont, QTextCursor
from core.ProcessManager import ProcessManager

class ProductionTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.prod_process = None
        self.bin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        file_group = QGroupBox("Input / Output Selection")
        file_layout = QGridLayout()
        file_layout.addWidget(QLabel("Input Raw (.dat):"), 0, 0)
        self.input_file = QLineEdit("../data/data_run.dat")
        file_layout.addWidget(self.input_file, 0, 1)
        self.btn_browse_in = QPushButton("📂 Browse")
        self.btn_browse_in.clicked.connect(self.browse_input)
        file_layout.addWidget(self.btn_browse_in, 0, 2)

        file_layout.addWidget(QLabel("Output ROOT (.root):"), 1, 0)
        self.output_file = QLineEdit("")
        self.output_file.setPlaceholderText("Auto-generated if empty")
        file_layout.addWidget(self.output_file, 1, 1)
        self.btn_browse_out = QPushButton("📂 Browse")
        self.btn_browse_out.clicked.connect(self.browse_output)
        file_layout.addWidget(self.btn_browse_out, 1, 2)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        opt_group = QGroupBox("Conversion Options")
        opt_layout = QHBoxLayout()
        self.chk_waveform = QCheckBox("Save Waveforms (-w)")
        self.chk_waveform.setChecked(True) 
        opt_layout.addWidget(self.chk_waveform)

        opt_layout.addWidget(QLabel(" |   Interactive Debug Event ID (-d):"))
        self.spin_debug = QSpinBox()
        self.spin_debug.setRange(-1, 2000000000)
        self.spin_debug.setValue(-1)
        opt_layout.addWidget(self.spin_debug)
        opt_layout.addStretch()
        opt_group.setLayout(opt_layout)
        layout.addWidget(opt_group)

        btn_layout = QHBoxLayout()
        self.btn_run = QPushButton("⚙️ Run ROOT Conversion")
        self.btn_run.setStyleSheet("background-color: #17a2b8; color: white; font-weight: bold; padding: 10px;")
        self.btn_run.clicked.connect(self.run_production)

        self.btn_stop = QPushButton("■ Force Stop")
        self.btn_stop.setStyleSheet("background-color: #6c757d; color: white; font-weight: bold; padding: 10px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_all)

        btn_layout.addWidget(self.btn_run)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)

        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setFont(QFont("Monospace", 10))
        self.terminal.setStyleSheet("background-color: #f8f9fa; color: #212529; border: 1px solid #ced4da;")
        layout.addWidget(self.terminal)

    def browse_input(self):
        default_dir = os.path.abspath(os.path.join(self.bin_dir, "../data"))
        path, _ = QFileDialog.getOpenFileName(self, "Select Raw Data", default_dir, "Data Files (*.dat)")
        if path: self.input_file.setText(os.path.relpath(path, self.bin_dir))

    def browse_output(self):
        default_dir = os.path.abspath(os.path.join(self.bin_dir, "../data"))
        path, _ = QFileDialog.getSaveFileName(self, "Select Output ROOT", default_dir, "ROOT Files (*.root)")
        if path: self.output_file.setText(os.path.relpath(path, self.bin_dir))

    def append_log(self, text):
        safe_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        color = "#212529" 
        bold = False
        
        if "[Info]" in safe_text or "[Debugger]" in safe_text:
            color = "#0d6efd" 
            bold = True
        elif "[Production]" in safe_text:
            color = "#198754" 
            bold = True
        elif "[Warning]" in safe_text or "Error" in safe_text:
            color = "#dc3545" 
            bold = True
        elif "[Progress]" in safe_text:
            color = "#fd7e14" 
        elif safe_text.strip().startswith("[") and "]" in safe_text:
            color = "#6f42c1" 
            
        b_open = "<b>" if bold else ""
        b_close = "</b>" if bold else ""
        html_line = f'<span style="color: {color};">{b_open}{safe_text}{b_close}</span>'
        self.terminal.append(html_line)
        self.terminal.moveCursor(QTextCursor.End)

    def run_production(self):
        cmd = ["./production_dt5730", "-i", self.input_file.text()]
        if self.output_file.text().strip(): cmd.extend(["-o", self.output_file.text()])
        if self.chk_waveform.isChecked(): cmd.append("-w")
        if self.spin_debug.value() >= 0: cmd.extend(["-d", str(self.spin_debug.value())])

        self.prod_process = ProcessManager(cmd, cwd=self.bin_dir)
        self.prod_process.log_signal.connect(self.append_log)
        self.prod_process.finished_signal.connect(self.on_finished)
        
        self.append_log(f"\n>>> Executing ROOT Converter: {' '.join(cmd)}")
        if self.spin_debug.value() >= 0:
            self.append_log("[Info] Interactive Debug Mode ON. A ROOT Canvas window should pop up.")
            
        self.prod_process.start()
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def on_finished(self, returncode):
        self.append_log(f">>> Conversion Exited (Code: {returncode})")
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def stop_all(self):
        if self.prod_process and self.prod_process.isRunning():
            self.prod_process.stop()