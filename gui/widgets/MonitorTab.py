import struct
import numpy as np
import pyqtgraph as pg
import zmq
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, 
                             QLabel, QPushButton, QSpinBox, QProgressBar, 
                             QMessageBox, QCheckBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from collections import deque

# CAEN Event Header: ExtTTT(Q), EvtID(I), RecLen(I), Mask(H), Pattern(H), BoardEventCounter(I)
HEADER_FORMAT = "=QIIHHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

class MonitorTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_mask = -1  
        self.curves_wave = {}   
        self.curves_qlong = {}  
        self.q_long_hists = {}  
        self.ch_cbs = {} # 채널별 체크박스 객체 저장소
        
        self.colors = [
            '#0d6efd', '#198754', '#dc3545', '#fd7e14', 
            '#6f42c1', '#0dcaf0', '#d63384', '#6c757d'
        ]
        
        self.warning_latched = False 
        
        self.setup_zmq()
        self.setup_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_zmq)
        self.timer.start(33) 

    def setup_zmq(self):
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.SUB)
        self.sock.setsockopt(zmq.RCVHWM, 2000) 
        self.sock.connect("tcp://127.0.0.1:5555")
        self.sock.setsockopt_string(zmq.SUBSCRIBE, "")

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 1. 상단 컨트롤 패널
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("<b>Display Engine:</b>"))
        
        self.cb_monitor = QComboBox()
        self.cb_monitor.addItems(["🟢 Live Monitor: ON (Auto Multi-Channel)", "🔴 Live Monitor: OFF (Save CPU)"])
        self.cb_monitor.currentIndexChanged.connect(self.toggle_monitor)
        ctrl_layout.addWidget(self.cb_monitor)

        ctrl_layout.addWidget(QLabel("  |  <b>Analysis Mode:</b>"))
        self.cb_spec_mode = QComboBox()
        self.cb_spec_mode.addItems(["📊 Pulse Charge (Integral Area)", "📈 Pulse Height (Amplitude)"])
        self.cb_spec_mode.currentIndexChanged.connect(self.toggle_spec_mode)
        ctrl_layout.addWidget(self.cb_spec_mode)

        ctrl_layout.addWidget(QLabel("  |  <b>Spectrum History:</b>"))
        self.spin_history = QSpinBox()
        self.spin_history.setRange(100, 100000)
        self.spin_history.setSingleStep(500)
        self.spin_history.setValue(2000)
        self.spin_history.setSuffix(" Evts")
        self.spin_history.valueChanged.connect(self.update_history_size)
        ctrl_layout.addWidget(self.spin_history)

        self.btn_clear = QPushButton("🗑️ Clear All")
        self.btn_clear.setStyleSheet("font-weight: bold; padding: 4px 15px; margin-left: 10px;")
        self.btn_clear.clicked.connect(self.clear_data)
        ctrl_layout.addWidget(self.btn_clear)
        
        ctrl_layout.addWidget(QLabel("  |  <b>ADC Temp:</b>"))
        self.temp_bar = QProgressBar()
        self.temp_bar.setRange(0, 100)
        self.temp_bar.setFormat("%v °C")
        self.temp_bar.setFixedWidth(100)
        self.temp_bar.setStyleSheet("QProgressBar { text-align: center; } QProgressBar::chunk { background-color: #198754; }")
        ctrl_layout.addWidget(self.temp_bar)
        
        ctrl_layout.addStretch() 
        layout.addLayout(ctrl_layout)

        # =========================================================================
        # [신규 추가] 채널별 렌더링 가시성(Visibility) 토글 체크박스
        # =========================================================================
        vis_layout = QHBoxLayout()
        vis_layout.addWidget(QLabel("<b>Channel Visibility:</b>"))
        
        for i in range(8):
            cb = QCheckBox(f"CH {i}")
            cb.setChecked(True)
            cb.setEnabled(False) # 데이터가 들어와서 활성화되기 전까지 잠금
            # 채널 색상과 동일하게 라벨 색상 부여
            cb.setStyleSheet(f"QCheckBox {{ color: {self.colors[i]}; font-weight: bold; margin-right: 10px; }}")
            cb.stateChanged.connect(lambda state, ch=i: self.toggle_channel_visibility(ch, state))
            vis_layout.addWidget(cb)
            self.ch_cbs[i] = cb
            
        vis_layout.addStretch()
        layout.addLayout(vis_layout)
        # =========================================================================

        # 2. PyQtGraph 캔버스 설정
        pg.setConfigOptions(antialias=True, background='#f8f9fa', foreground='#212529')
        self.glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self.glw)

        self.plot_wave = self.glw.addPlot(title="Live Waveform (Auto Overlay)")
        self.plot_wave.setLabel('bottom', "Samples (2ns)")
        self.plot_wave.setLabel('left', "ADC Value (14-bit)")
        self.plot_wave.addLegend(offset=(10, 10))
        self.glw.nextRow()

        self.plot_qlong = self.glw.addPlot(title="Real-time Computed Charge Spectrum")
        self.plot_qlong.setLogMode(y=True)
        self.plot_qlong.setLabel('bottom', "Integrated Charge (ADC Bins)")
        self.plot_qlong.setLabel('left', "Counts (Log)")
        self.plot_qlong.addLegend(offset=(10, 10))

    @pyqtSlot(int, int)
    def toggle_channel_visibility(self, ch, state):
        """체크박스 상태에 따라 파형과 스펙트럼 곡선을 숨기거나 표시합니다."""
        is_visible = (state == Qt.CheckState.Checked.value)
        if ch in self.curves_wave:
            self.curves_wave[ch].setVisible(is_visible)
        if ch in self.curves_qlong:
            self.curves_qlong[ch].setVisible(is_visible)

    @pyqtSlot(int)
    def toggle_spec_mode(self, idx):
        if idx == 0:
            self.plot_qlong.setTitle("Real-time Computed Charge Spectrum")
            self.plot_qlong.setLabel('bottom', "Integrated Charge (ADC Bins)")
        else:
            self.plot_qlong.setTitle("Real-time Pulse Height Spectrum")
            self.plot_qlong.setLabel('bottom', "Pulse Height Amplitude (ADC Bins)")
        self.clear_data()

    @pyqtSlot(float)
    def update_temperature(self, temp: float):
        self.temp_bar.setValue(int(temp))
        if temp >= 80.0:
            self.temp_bar.setStyleSheet("QProgressBar { text-align: center; } QProgressBar::chunk { background-color: #dc3545; }")
            if not self.warning_latched:
                self.warning_latched = True
                QMessageBox.warning(
                    self, 
                    "Over-Temperature Warning", 
                    "ADC 내부 온도가 80°C를 초과했습니다.\n82°C 도달 시 하드웨어 보호를 위해 ADC가 강제 종료됩니다."
                )
        else:
            self.temp_bar.setStyleSheet("QProgressBar { text-align: center; } QProgressBar::chunk { background-color: #198754; }")
            if temp < 75.0:
                self.warning_latched = False

    def update_history_size(self):
        new_size = self.spin_history.value()
        for ch in self.q_long_hists:
            current_data = list(self.q_long_hists[ch])
            self.q_long_hists[ch] = deque(current_data[-new_size:], maxlen=new_size)

    def rebuild_plots(self, mask):
        self.plot_wave.clear()
        self.plot_qlong.clear()
        if self.plot_wave.legend: self.plot_wave.legend.clear()
        if self.plot_qlong.legend: self.plot_qlong.legend.clear()
        
        self.curves_wave.clear()
        self.curves_qlong.clear()
        self.q_long_hists.clear()
        
        # 모든 체크박스 초기화
        for i in range(8):
            self.ch_cbs[i].setEnabled(False)
            
        active_channels = [i for i in range(8) if (mask >> i) & 1]
        
        for ch in active_channels:
            # 해당 채널의 체크박스 활성화
            self.ch_cbs[ch].setEnabled(True)
            
            color = self.colors[ch % len(self.colors)]
            pen = pg.mkPen(color, width=1.5)
            self.curves_wave[ch] = self.plot_wave.plot(name=f"CH {ch}", pen=pen)
            
            brush = pg.mkColor(color)
            brush.setAlpha(100)
            
            self.curves_qlong[ch] = self.plot_qlong.plot(name=f"CH {ch}", stepMode=True, fillLevel=0.1, brush=brush, pen=color)
            self.q_long_hists[ch] = deque(maxlen=self.spin_history.value())
            
            # 체크박스 상태에 따라 가시성 즉각 적용
            self.toggle_channel_visibility(ch, self.ch_cbs[ch].checkState().value)

    def toggle_monitor(self, idx):
        if idx == 0:
            self.timer.start(33)
        else:
            self.timer.stop()
            while True:
                try: self.sock.recv(flags=zmq.NOBLOCK)
                except zmq.Again: break

    def clear_data(self):
        for ch in self.q_long_hists:
            self.q_long_hists[ch].clear()
            if ch in self.curves_wave:
                self.curves_wave[ch].setData(np.array([], dtype=np.uint16))
            if ch in self.curves_qlong:
                self.curves_qlong[ch].setData(x=np.array([-0.5, 0.5]), y=np.array([0.1]))

    def poll_zmq(self):
        latest_msg = None
        while True:
            try:
                msg = self.sock.recv(flags=zmq.NOBLOCK)
                latest_msg = msg
                
                header = struct.unpack(HEADER_FORMAT, msg[:HEADER_SIZE])
                record_len = int(header[2])
                mask = int(header[3])
                
                if mask != self.current_mask:
                    self.current_mask = mask
                    self.rebuild_plots(mask)
                    self.clear_data()
                    
                active_channels = [i for i in range(8) if (mask >> i) & 1]
                spec_mode = self.cb_spec_mode.currentIndex()
                
                for idx, ch in enumerate(active_channels):
                    # 가시성 체크박스가 꺼져 있다면 스펙트럼 적분 연산도 생략하여 CPU 절약
                    if not self.ch_cbs[ch].isChecked():
                        continue

                    offset = HEADER_SIZE + (idx * record_len * 2)
                    wave_bytes = msg[offset : offset + (record_len * 2)]
                    
                    if wave_bytes:
                        wave_arr = np.frombuffer(wave_bytes, dtype=np.uint16)
                        if len(wave_arr) > 20: 
                            min_idx = int(np.argmin(wave_arr))
                            
                            if min_idx > 10:
                                baseline_end = min(record_len // 4, min_idx - 5)
                            else:
                                baseline_end = 10
                                
                            baseline_end = max(5, baseline_end) 
                            baseline = np.mean(wave_arr[:baseline_end])

                            val = 0.0
                            if spec_mode == 0:
                                pulse_region = wave_arr[wave_arr < baseline]
                                val = np.sum(baseline - pulse_region)
                            else:
                                val = baseline - wave_arr[min_idx]

                            if val > 0: 
                                self.q_long_hists[ch].append(val)
            except zmq.Again: 
                break

        if latest_msg:
            header = struct.unpack(HEADER_FORMAT, latest_msg[:HEADER_SIZE])
            record_len = int(header[2])
            mask = int(header[3])
            active_channels = [i for i in range(8) if (mask >> i) & 1]
            
            for idx, ch in enumerate(active_channels):
                if not self.ch_cbs[ch].isChecked():
                    continue

                if ch in self.curves_wave:
                    offset = HEADER_SIZE + (idx * record_len * 2)
                    wave_bytes = latest_msg[offset : offset + (record_len * 2)]
                    if wave_bytes:
                        wave_arr = np.frombuffer(wave_bytes, dtype=np.uint16)
                        self.curves_wave[ch].setData(wave_arr)
                        
            for ch in self.curves_qlong:
                if not self.ch_cbs[ch].isChecked():
                    continue

                hist_data = self.q_long_hists[ch]
                if len(hist_data) > 5:
                    data_min, data_max = min(hist_data), max(hist_data)
                    if data_min == data_max: 
                        continue 
                        
                    y, x_edges = np.histogram(hist_data, bins=150)
                    y = np.where(y == 0, 0.1, y) 
                    
                    self.curves_qlong[ch].setData(x=x_edges, y=y)

    def cleanup(self):
        if self.timer.isActive(): self.timer.stop()
        self.sock.close()
        self.ctx.term()