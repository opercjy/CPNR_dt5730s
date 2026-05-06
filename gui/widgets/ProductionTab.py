import re
import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QPushButton, QProgressBar, QLabel, QLineEdit, 
                             QTextEdit, QSpinBox, QFileDialog, QGridLayout, QCheckBox)
from PyQt5.QtCore import Qt, pyqtSlot, QSettings, QProcess

class ProductionTab(QWidget):
    def __init__(self):
        super().__init__()
        
        # OS 레지스트리/설정 기반 마지막 폴더 기억
        self.settings = QSettings("CPNR", "DT5730S_DAQ")
        
        # 외부 ProcessManager에 의존하지 않는 독자적 QProcess 엔진 탑재
        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.handle_finished)
        self.process.errorOccurred.connect(self.handle_error)

        self.init_ui()

        # 백엔드 로그 파싱 정규식
        self.log_pattern = re.compile(
            r"\[Progress\]\s+([0-9.]+)%\s+\|\s+Events:\s+(\d+)\s+\|\s+Speed:\s+([0-9.]+)\s+MB/s\s+\|\s+ETA:\s+(\d+)"
        )

    def init_ui(self):
        layout = QVBoxLayout()

        # =====================================================================
        # 1. Input / Output Selection
        # =====================================================================
        io_group = QGroupBox("Input / Output Selection")
        io_layout = QGridLayout()
        
        self.input_edit = QLineEdit()
        self.btn_browse_in = QPushButton("📁 Browse")
        self.btn_browse_in.clicked.connect(self.browse_input)
        
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Auto-generated if empty (*_prod.root)")
        self.btn_browse_out = QPushButton("📁 Browse")
        self.btn_browse_out.clicked.connect(self.browse_output)

        io_layout.addWidget(QLabel("Input Raw (.dat):"), 0, 0)
        io_layout.addWidget(self.input_edit, 0, 1)
        io_layout.addWidget(self.btn_browse_in, 0, 2)
        io_layout.addWidget(QLabel("Output ROOT (.root):"), 1, 0)
        io_layout.addWidget(self.output_edit, 1, 1)
        io_layout.addWidget(self.btn_browse_out, 1, 2)
        io_group.setLayout(io_layout)
        layout.addWidget(io_group)

        # =====================================================================
        # 2. Conversion Options & Interactive Debugger Controls
        # =====================================================================
        opt_group = QGroupBox("Conversion Options & Interactive Debugger")
        opt_layout = QHBoxLayout()
        
        # 파형 보존 옵션 (-w)
        self.chk_save_waveforms = QCheckBox("Save Waveforms (-w)")
        self.chk_save_waveforms.setStyleSheet("font-weight: bold;")
        
        self.btn_run = QPushButton("▶ Run ROOT Conversion")
        self.btn_run.setStyleSheet("background-color: #5bc0de; color: white; font-weight: bold; padding: 8px;")
        self.btn_run.clicked.connect(self.run_conversion)
        
        self.btn_stop = QPushButton("■ Force Stop")
        self.btn_stop.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold; padding: 8px;")
        self.btn_stop.clicked.connect(self.stop_all)

        self.btn_prev = QPushButton("◁ Prev (p)")
        self.btn_next = QPushButton("▷ Next (n)")
        self.btn_jump = QPushButton("↷ Jump (j)")
        self.spin_jump = QSpinBox()
        self.spin_jump.setRange(0, 9999999)
        self.btn_quit = QPushButton("✕ Quit Debug (q)")

        self.btn_prev.clicked.connect(lambda: self.send_debug_command("p\n"))
        self.btn_next.clicked.connect(lambda: self.send_debug_command("n\n"))
        self.btn_jump.clicked.connect(lambda: self.send_debug_command(f"j {self.spin_jump.value()}\n"))
        self.btn_quit.clicked.connect(lambda: self.send_debug_command("q\n"))

        opt_layout.addWidget(self.chk_save_waveforms)
        opt_layout.addWidget(self.btn_run)
        opt_layout.addWidget(self.btn_stop)
        opt_layout.addSpacing(20)
        opt_layout.addWidget(self.btn_prev)
        opt_layout.addWidget(self.btn_next)
        opt_layout.addWidget(self.spin_jump)
        opt_layout.addWidget(self.btn_jump)
        opt_layout.addWidget(self.btn_quit)
        opt_group.setLayout(opt_layout)
        layout.addWidget(opt_group)

        # =====================================================================
        # 3. Dashboard
        # =====================================================================
        dash_group = QGroupBox("Conversion Status Dashboard")
        dash_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #5cb85c; }")

        stat_layout = QHBoxLayout()
        self.lbl_events = QLabel("Events: 0")
        self.lbl_speed = QLabel("Speed: 0.0 MB/s")
        self.lbl_eta = QLabel("ETA: 0 s")
        
        font = self.lbl_events.font()
        font.setPointSize(11)
        font.setBold(True)
        for lbl in [self.lbl_events, self.lbl_speed, self.lbl_eta]:
            lbl.setFont(font)
            lbl.setAlignment(Qt.AlignCenter)
            stat_layout.addWidget(lbl)

        dash_layout.addWidget(self.progress_bar)
        dash_layout.addLayout(stat_layout)
        dash_group.setLayout(dash_layout)
        layout.addWidget(dash_group)

        # =====================================================================
        # 4. Raw Log Window (밝은 테마)
        # =====================================================================
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumHeight(150)
        self.log_console.setStyleSheet("background-color: #f8f9fa; color: #333333; font-family: monospace; border: 1px solid #cccccc;")
        layout.addWidget(self.log_console)

        self.setLayout(layout)

    # =====================================================================
    # 경로 기억 로직
    # =====================================================================
    def browse_input(self):
        last_dir = self.settings.value("last_prod_input_dir", os.getcwd())
        fname, _ = QFileDialog.getOpenFileName(self, "Open Raw Data", last_dir, "Data Files (*.dat)")
        if fname:
            self.input_edit.setText(fname)
            self.settings.setValue("last_prod_input_dir", os.path.dirname(fname))

    def browse_output(self):
        last_dir = self.settings.value("last_prod_output_dir", os.getcwd())
        fname, _ = QFileDialog.getSaveFileName(self, "Save ROOT Data", last_dir, "ROOT Files (*.root)")
        if fname:
            self.output_edit.setText(fname)
            self.settings.setValue("last_prod_output_dir", os.path.dirname(fname))

    # =====================================================================
    # QProcess 제어 로직 (시작, 정지, 명령어 전송)
    # =====================================================================
    def run_conversion(self):
        in_file = self.input_edit.text().strip()
        out_file = self.output_edit.text().strip()
        
        if not in_file:
            self.log_console.append("<span style='color:red;'>[Error] Please select input file!</span>")
            return
            
        args = ["-i", in_file]
        if out_file:
            args.extend(["-o", out_file])
            
        # 체크박스 상태 확인 후 -w 인자 추가
        if self.chk_save_waveforms.isChecked():
            args.append("-w")
            
        self.progress_bar.setValue(0)
        self.lbl_events.setText("Events: 0")
        self.lbl_speed.setText("Speed: 0.0 MB/s")
        self.lbl_eta.setText("ETA: 0 s")
        self.log_console.clear()
        
        # 🌟 경로 추상화 (Soft-Coding) 완벽 적용
        widget_dir = os.path.dirname(os.path.abspath(__file__)) # .../bin/gui/widgets
        gui_dir = os.path.dirname(widget_dir)                   # .../bin/gui
        bin_dir = os.path.dirname(gui_dir)                      # .../bin (실행파일 위치)
        
        exe_path = os.path.join(bin_dir, "production_dt5730")
        
        if not os.path.exists(exe_path):
            self.log_console.append(f"<span style='color:red;'>[Error] Executable not found at: {exe_path}. Did you run 'make'?</span>")
            return

        self.btn_run.setEnabled(False)
        self.log_console.append(f"<b>[System] Starting:</b> {exe_path} {' '.join(args)}")
        self.process.start(exe_path, args)

    def stop_all(self):
        if self.process.state() == QProcess.Running:
            self.process.terminate()
            self.process.waitForFinished(1000)
            if self.process.state() == QProcess.Running:
                self.process.kill()
            self.log_console.append("<span style='color:red;'>[System] Conversion forcefully stopped.</span>")
            self.btn_run.setEnabled(True)

    def send_debug_command(self, cmd_str):
        if self.process.state() == QProcess.Running:
            self.process.write(cmd_str.encode('utf-8'))
            self.log_console.append(f"<span style='color:blue;'>[Sent Command] {cmd_str.strip()}</span>")

    # =====================================================================
    # 스트리밍 로그 파싱 및 라우팅
    # =====================================================================
    @pyqtSlot()
    def handle_stdout(self):
        while self.process.canReadLine():
            line = self.process.readLine().data().decode('utf-8').strip()
            if not line: continue

            match = self.log_pattern.search(line)
            if match:
                self.progress_bar.setValue(int(float(match.group(1))))
                self.lbl_events.setText(f"Events: {int(match.group(2)):,}")
                self.lbl_speed.setText(f"Speed: {match.group(3)} MB/s")
                self.lbl_eta.setText(f"ETA: {match.group(4)} s")
            else:
                self.log_console.append(line)
                self.log_console.verticalScrollBar().setValue(self.log_console.verticalScrollBar().maximum())

    @pyqtSlot()
    def handle_stderr(self):
        while self.process.canReadLine():
            line = self.process.readLine().data().decode('utf-8').strip()
            if line:
                self.log_console.append(f"<span style='color:red;'>{line}</span>")

    @pyqtSlot(QProcess.ProcessError)
    def handle_error(self, error):
        error_msgs = {
            QProcess.FailedToStart: "Failed to start. Executable missing or lacks permissions.",
            QProcess.Crashed: "Process crashed.",
            QProcess.Timedout: "Process timed out.",
            QProcess.WriteError: "Failed to write to process.",
            QProcess.ReadError: "Failed to read from process.",
            QProcess.UnknownError: "Unknown error occurred."
        }
        msg = error_msgs.get(error, "Unknown Error")
        self.log_console.append(f"<span style='color:red;'><b>[QProcess Error]</b> {msg}</span>")
        self.btn_run.setEnabled(True)

    @pyqtSlot(int, QProcess.ExitStatus)
    def handle_finished(self, exitCode, exitStatus):
        self.btn_run.setEnabled(True)
        if exitStatus == QProcess.NormalExit and exitCode == 0:
            self.log_console.append(f"<span style='color:#5cb85c;'><b>[System] Conversion Successfully Finished!</b></span>")
        else:
            self.log_console.append(f"<span style='color:red;'><b>[System] Conversion Exited with Code: {exitCode}</b></span>")
