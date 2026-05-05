#!/usr/bin/env python3
import sys
import zmq
import struct
import numpy as np
import pyqtgraph as pg
from collections import deque
from pyqtgraph.Qt import QtWidgets, QtCore

# 24 Bytes Header Layout:
# ExtTTT(Q), EvtID(I), RecLen(I), Mask(H), Pattern(H), Reserved(I)
HEADER_FORMAT = "=QIIHHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

class LiveMonitor(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HEP DAQ: Live Raw Waveform & Spectrum")
        self.resize(1000, 800)

        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.SUB)
        self.sock.setsockopt(zmq.RCVHWM, 2000)
        self.sock.connect("tcp://127.0.0.1:5555")
        self.sock.setsockopt_string(zmq.SUBSCRIBE, "")

        self.q_long_hist = deque(maxlen=10000)
        
        self.setup_ui()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.poll_zmq)
        self.timer.start(33)

    def setup_ui(self):
        pg.setConfigOptions(antialias=True)
        self.glw = pg.GraphicsLayoutWidget()
        self.setCentralWidget(self.glw)

        self.plot_wave = self.glw.addPlot(title="Live Waveform (CH0)")
        self.curve_wave = self.plot_wave.plot(pen="y")
        self.glw.nextRow()

        self.plot_qlong = self.glw.addPlot(title="Real-time Python Computed Charge Spectrum")
        self.plot_qlong.setLogMode(y=True)
        self.curve_qlong = self.plot_qlong.plot(stepMode="center", fillLevel=0, brush=(0, 150, 255, 150))

    def poll_zmq(self):
        latest_msg = None
        while True:
            try:
                msg = self.sock.recv(flags=zmq.NOBLOCK)
                latest_msg = msg
                
                header = struct.unpack(HEADER_FORMAT, msg[:HEADER_SIZE])
                record_len = int(header[2])
                wave_bytes = msg[HEADER_SIZE : HEADER_SIZE + (record_len * 2)]
                
                if wave_bytes:
                    wave_arr = np.frombuffer(wave_bytes, dtype=np.uint16)
                    # 동적 파형 적분 (앞 150샘플을 베이스라인으로 활용)
                    if len(wave_arr) > 200:
                        baseline = np.mean(wave_arr[:150])
                        # 음극성(Negative) 파형 면적 적분
                        pulse_area = np.sum(baseline - wave_arr[150:]) 
                        
                        if pulse_area > 0:
                            self.q_long_hist.append(pulse_area)
            except zmq.Again:
                break

        if latest_msg:
            header = struct.unpack(HEADER_FORMAT, latest_msg[:HEADER_SIZE])
            record_len = int(header[2])
            wave_bytes = latest_msg[HEADER_SIZE : HEADER_SIZE + (record_len * 2)]
            
            if wave_bytes:
                wave_arr = np.frombuffer(wave_bytes, dtype=np.uint16)
                self.curve_wave.setData(wave_arr)
            
            if len(self.q_long_hist) > 2:
                y, x = np.histogram(np.array(self.q_long_hist), bins=100)
                y = np.where(y == 0, 0.1, y)
                self.curve_qlong.setData(x, y)

    def closeEvent(self, event):
        if self.timer.isActive():
            self.timer.stop()
        self.sock.close()
        self.ctx.term()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    viewer = LiveMonitor()
    viewer.show()
    sys.exit(app.exec())  # 아주 심플하게 최신 문법으로 고정