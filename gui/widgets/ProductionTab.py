import re
import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QPushButton, QProgressBar, QLabel, QLineEdit, 
                             QTextEdit, QSpinBox, QFileDialog, QGridLayout)
from PyQt5.QtCore import Qt, pyqtSlot, QSettings

class ProductionTab(QWidget):
    def __init__(self, process_manager):
        super().__init__()
        self.pm = process_manager
        
        # 시스템 설정(QSettings) 초기화: 경로 기억용
        self.settings = QSettings("CPNR", "DT5730S_DAQ")
        
        self.init_ui()

        # 정규표현식 컴파일 (C++ 백엔드에서 쏘는 포맷)
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
        
        # 실행 제어 버튼
        self.btn_run = QPushButton("▶ Run ROOT Conversion")
        self.btn_run.setStyleSheet("background-color: #5bc0de; color: white; font-weight: bold; padding: 8px;")
        self.btn_run.clicked.connect(self.run_conversion)
        
        self.btn_stop = QPushButton("■ Force Stop")
        self.btn_stop.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold; padding: 8px;")
        self.btn_stop.clicked.connect(self.pm.stop_process)

        # 인터랙티브 컨트롤 패널
        self.btn_prev = QPushButton("◁ Prev (p)")
        self.btn_next = QPushButton("▷ Next (n)")
        self.btn_jump = QPushButton("↷ Jump (j)")
        self.spin_jump = QSpinBox()
        self.spin_jump.setRange(0, 9999999)
        self.btn_quit = QPushButton("✕ Quit Debug (q)")

        # 시그널 매핑 (표준 입력으로 전송)
        self.btn_prev.clicked.connect(lambda: self.send_debug_command("p\n"))
        self.btn_next.clicked.connect(lambda: self.send_debug_command("n\n"))
        self.btn_jump.clicked.connect(lambda: self.send_debug_command(f"j {self.spin_jump.value()}\n"))
        self.btn_quit.clicked.connect(lambda: self.send_debug_command("q\n"))

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
        # 3. 📊 Dashboard (진행률 및 실시간 스탯)
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
        # 4. Raw Log Window
        # =====================================================================
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumHeight(150)
        self.log_console.setStyleSheet("background-color: #2b2b2b; color: #a9b7c6; font-family: monospace;")
        layout.addWidget(self.log_console)

        self.setLayout(layout)

        # ProcessManager 시그널 연결
        self.pm.log_signal.connect(self.parse_and_update_dashboard)

    # =====================================================================
    # 파일 탐색 및 경로 기억 (QSettings 활용)
    # =====================================================================
    def browse_input(self):
        # 1. 저장된 마지막 경로 불러오기 (없으면 현재 디렉토리)
        last_dir = self.settings.value("last_prod_input_dir", os.getcwd())
        
        fname, _ = QFileDialog.getOpenFileName(self, "Open Raw Data", last_dir, "Data Files (*.dat)")
        if fname:
            self.input_edit.setText(fname)
            # 2. 선택한 파일의 폴더 경로를 저장하여 다음 번에 재사용
            self.settings.setValue("last_prod_input_dir", os.path.dirname(fname))

    def browse_output(self):
        last_dir = self.settings.value("last_prod_output_dir", os.getcwd())
        
        fname, _ = QFileDialog.getSaveFileName(self, "Save ROOT Data", last_dir, "ROOT Files (*.root)")
        if fname:
            self.output_edit.setText(fname)
            self.settings.setValue("last_prod_output_dir", os.path.dirname(fname))

    # =====================================================================
    # 실행 및 통신 로직
    # =====================================================================
    def run_conversion(self):
        in_file = self.input_edit.text().strip()
        out_file = self.output_edit.text().strip()
        
        if not in_file:
            self.log_console.append("<span style='color:red;'>[Error] Please select input file!</span>")
            return
            
        cmd = ["./bin/production_dt5730", "-i", in_file]
        if out_file:
            cmd.extend(["-o", out_file])
            
        # UI 초기화
        self.progress_bar.setValue(0)
        self.lbl_events.setText("Events: 0")
        self.lbl_speed.setText("Speed: 0.0 MB/s")
        self.lbl_eta.setText("ETA: 0 s")
        self.log_console.clear()
        
        self.pm.start_process(cmd)

    def send_debug_command(self, cmd_str):
        """인터랙티브 디버깅 시 C++ 백엔드의 표준 입력(stdin)으로 비동기 명령 전송"""
        if self.pm.process and self.pm.process.state() == self.pm.process.Running:
            self.pm.process.write(cmd_str.encode('utf-8'))
            self.log_console.append(f"<span style='color:yellow;'>[Sent Command] {cmd_str.strip()}</span>")

    @pyqtSlot(str)
    def parse_and_update_dashboard(self, text):
        """C++ stdout 파싱 및 대시보드 라우팅"""
        text = text.strip()
        if not text:
            return

        # 1. 정규표현식 매칭: 진행률 및 스탯 업데이트 (로그 창에는 숨김)
        match = self.log_pattern.search(text)
        if match:
            progress = float(match.group(1))
            events = match.group(2)
            speed = match.group(3)
            eta = match.group(4)
            
            self.progress_bar.setValue(int(progress))
            self.lbl_events.setText(f"Events: {int(events):,}")
            self.lbl_speed.setText(f"Speed: {speed} MB/s")
            self.lbl_eta.setText(f"ETA: {eta} s")
            return
        
        # 2. 일반 텍스트는 로그 창에 출력 (자동 스크롤)
        self.log_console.append(text)
        self.log_console.verticalScrollBar().setValue(self.log_console.verticalScrollBar().maximum())
