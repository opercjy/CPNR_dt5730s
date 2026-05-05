import struct
import numpy as np
import pyqtgraph as pg
import zmq
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QPushButton
from PyQt5.QtCore import QTimer
from collections import deque

# ExtTTT(Q), EvtID(I), RecLen(I), Mask(H), Pattern(H), Reserved(I)
HEADER_FORMAT = "=QIIHHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

class MonitorTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_zmq()
        self.setup_ui()
        self.q_long_hist = deque(maxlen=10000)
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
        
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("<b>Display Engine:</b>"))
        
        self.cb_monitor = QComboBox()
        self.cb_monitor.addItems(["🟢 Live Monitor: ON", "🔴 Live Monitor: OFF (Save CPU)"])
        self.cb_monitor.currentIndexChanged.connect(self.toggle_monitor)
        ctrl_layout.addWidget(self.cb_monitor)

        # --- [신규 기능] 타겟 모니터링 채널 선택기 ---
        ctrl_layout.addWidget(QLabel("  |  <b>Target CH:</b>"))
        self.cb_channel = QComboBox()
        self.cb_channel.addItems([f"CH{i}" for i in range(8)])
        self.cb_channel.currentIndexChanged.connect(self.on_channel_changed)
        ctrl_layout.addWidget(self.cb_channel)
        # ---------------------------------------------

        self.btn_clear = QPushButton("🗑️ Clear Histogram")
        self.btn_clear.setStyleSheet("font-weight: bold; padding: 4px 15px; margin-left: 10px;")
        self.btn_clear.clicked.connect(self.clear_data)
        ctrl_layout.addWidget(self.btn_clear)

        ctrl_layout.addStretch() 
        layout.addLayout(ctrl_layout)

        pg.setConfigOptions(antialias=True, background='#f8f9fa', foreground='#212529')
        
        self.glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self.glw)

        self.plot_wave = self.glw.addPlot(title="Live Waveform (CH0)")
        self.plot_wave.setLabel('bottom', "Samples (2ns)")
        self.plot_wave.setLabel('left', "ADC Value (14-bit)")
        self.curve_wave = self.plot_wave.plot(pen=pg.mkPen('#0d6efd', width=1.5))
        self.glw.nextRow()

        self.plot_qlong = self.glw.addPlot(title="Real-time Computed Charge Spectrum")
        self.plot_qlong.setLogMode(y=True)
        self.plot_qlong.setLabel('bottom', "Integrated Charge (ADC Bins)")
        self.plot_qlong.setLabel('left', "Counts (Log)")
        self.curve_qlong = self.plot_qlong.plot(stepMode="center", fillLevel=0, brush=(0, 150, 255, 150))

    def toggle_monitor(self, idx):
        if idx == 0:
            self.timer.start(33)
        else:
            self.timer.stop()
            while True:
                try: self.sock.recv(flags=zmq.NOBLOCK)
                except zmq.Again: break

    def on_channel_changed(self, idx):
        """채널 변경 시 그래프 타이틀 업데이트 및 기존 히스토그램 날림"""
        self.plot_wave.setTitle(f"Live Waveform (CH{idx})")
        self.clear_data()

    def clear_data(self):
        self.q_long_hist.clear()
        self.curve_wave.setData(np.array([], dtype=np.uint16))
        self.curve_qlong.setData(np.array([0, 1]), np.array([0.1]))

    def poll_zmq(self):
        latest_msg = None
        target_ch = self.cb_channel.currentIndex()
        
        while True:
            try:
                msg = self.sock.recv(flags=zmq.NOBLOCK)
                latest_msg = msg
                
                header = struct.unpack(HEADER_FORMAT, msg[:HEADER_SIZE])
                record_len = int(header[2])
                mask = int(header[3])
                
                # 비트마스크를 분석하여 현재 켜져 있는 채널 리스트업 [예: 0, 2, 3]
                active_channels = [i for i in range(8) if (mask >> i) & 1]
                
                # 내가 모니터링하려는 채널이 현재 패킷에 존재할 때만 연산 수행
                if target_ch in active_channels:
                    idx = active_channels.index(target_ch)
                    # 데이터 블록에서 정확한 바이트 오프셋 계산 (O(1))
                    offset = HEADER_SIZE + (idx * record_len * 2)
                    wave_bytes = msg[offset : offset + (record_len * 2)]
                    
                    if wave_bytes:
                        wave_arr = np.frombuffer(wave_bytes, dtype=np.uint16)
                        if len(wave_arr) > 200:
                            baseline = np.mean(wave_arr[:150])
                            pulse_area = np.sum(baseline - wave_arr[150:]) 
                            if pulse_area > 0: self.q_long_hist.append(pulse_area)
            except zmq.Again: 
                break

        # 화면 렌더링 (가장 마지막에 낚아챈 패킷 1개 기준)
        if latest_msg:
            header = struct.unpack(HEADER_FORMAT, latest_msg[:HEADER_SIZE])
            record_len = int(header[2])
            mask = int(header[3])
            active_channels = [i for i in range(8) if (mask >> i) & 1]
            
            if target_ch in active_channels:
                idx = active_channels.index(target_ch)
                offset = HEADER_SIZE + (idx * record_len * 2)
                wave_bytes = latest_msg[offset : offset + (record_len * 2)]
                
                if wave_bytes:
                    wave_arr = np.frombuffer(wave_bytes, dtype=np.uint16)
                    self.curve_wave.setData(wave_arr)
                    
            if len(self.q_long_hist) > 2:
                y, x = np.histogram(np.array(self.q_long_hist), bins=100)
                y = np.where(y == 0, 0.1, y)
                self.curve_qlong.setData(x, y)

    def cleanup(self):
        if self.timer.isActive(): self.timer.stop()
        self.sock.close()
        self.ctx.term()