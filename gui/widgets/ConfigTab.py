import os
import configparser
import pyqtgraph as pg
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QLabel, QTableWidget, QTableWidgetItem,
                             QGroupBox, QSpinBox, QDoubleSpinBox, QHeaderView, 
                             QFileDialog, QMessageBox, QCheckBox)
from PyQt5.QtCore import Qt

class ConfigTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        self.current_config_path = ""
        self.config = configparser.ConfigParser()
        self.config.optionxform = str 
        self.setup_ui()
        self.update_mask_calc()
        self.update_adc_simulator()
        self.update_time_simulator()

    def setup_ui(self):
        layout = QHBoxLayout(self)

        # ==========================================
        # [좌측] TableWidget
        # ==========================================
        left_layout = QVBoxLayout()
        btn_layout = QHBoxLayout()
        self.btn_load = QPushButton("📂 Load .conf")
        self.btn_load.clicked.connect(self.load_config)
        self.btn_save = QPushButton("💾 Save .conf")
        self.btn_save.clicked.connect(self.save_config)
        self.btn_save.setStyleSheet("background-color: #0d6efd; color: white; font-weight: bold;")
        
        btn_layout.addWidget(self.btn_load)
        btn_layout.addWidget(self.btn_save)
        left_layout.addLayout(btn_layout)

        self.lbl_current_file = QLabel("Current File: None")
        self.lbl_current_file.setStyleSheet("color: #6c757d; font-weight: bold;")
        left_layout.addWidget(self.lbl_current_file)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Section", "Parameter", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        left_layout.addWidget(self.table)
        layout.addLayout(left_layout, stretch=5)

        # ==========================================
        # [우측] 마스터 아키텍트 시뮬레이터 패널
        # ==========================================
        right_layout = QVBoxLayout()

        # ------------------------------------------
        # 1. 채널 비트마스크 계산기
        # ------------------------------------------
        mask_group = QGroupBox("🔌 Channel Bitmask Calculator")
        mask_group.setStyleSheet("QGroupBox { font-weight: bold; color: #6f42c1; }")
        mask_vbox = QVBoxLayout()
        chk_layout = QGridLayout()
        self.ch_checks = []
        for i in range(8):
            chk = QCheckBox(f"CH{i}")
            if i == 0 or i == 1: chk.setChecked(True) # 기본 CH0, CH1 (동시계수)
            chk.stateChanged.connect(self.update_mask_calc)
            chk_layout.addWidget(chk, i // 4, i % 4)
            self.ch_checks.append(chk)
        mask_vbox.addLayout(chk_layout)

        res_mask_layout = QHBoxLayout()
        res_mask_layout.addWidget(QLabel("Decimal Mask Value:"))
        self.lbl_mask_res = QLabel("3")
        self.lbl_mask_res.setStyleSheet("background-color: #e9ecef; padding: 5px; font-weight: bold; font-family: monospace; border-radius: 3px;")
        res_mask_layout.addWidget(self.lbl_mask_res)
        
        self.btn_apply_mask = QPushButton("Apply Mask")
        self.btn_apply_mask.setStyleSheet("background-color: #6f42c1; color: white; font-weight: bold;")
        self.btn_apply_mask.clicked.connect(self.apply_mask_to_table)
        res_mask_layout.addWidget(self.btn_apply_mask)
        mask_vbox.addLayout(res_mask_layout)
        mask_group.setLayout(mask_vbox)
        right_layout.addWidget(mask_group)

        # ------------------------------------------
        # 2. 시간축 & DSP (페데스탈) 계산기 (신규 탑재)
        # ------------------------------------------
        time_group = QGroupBox("⏱️ Time & DSP Calculator")
        time_group.setStyleSheet("QGroupBox { font-weight: bold; color: #fd7e14; }")
        time_vbox = QVBoxLayout()

        time_grid = QGridLayout()
        time_grid.addWidget(QLabel("RecordLength (Samples):"), 0, 0)
        self.spin_record = QSpinBox()
        self.spin_record.setRange(128, 102400)
        self.spin_record.setValue(512)
        self.spin_record.valueChanged.connect(self.update_time_simulator)
        time_grid.addWidget(self.spin_record, 0, 1)

        time_grid.addWidget(QLabel("PostTrigger (%):"), 1, 0)
        self.spin_post = QSpinBox()
        self.spin_post.setRange(10, 90)
        self.spin_post.setValue(60) # 연구원님 요청: 60% 로 변경
        self.spin_post.setSuffix(" %")
        self.spin_post.valueChanged.connect(self.update_time_simulator)
        time_grid.addWidget(self.spin_post, 1, 1)

        time_grid.addWidget(QLabel("Coincidence Window:"), 2, 0)
        self.spin_coin = QSpinBox()
        self.spin_coin.setRange(0, 1000)
        self.spin_coin.setValue(20) # 기본 20 ns
        self.spin_coin.setSuffix(" ns")
        time_grid.addWidget(self.spin_coin, 2, 1)
        time_vbox.addLayout(time_grid)

        res_style = "background-color: #e9ecef; padding: 5px; font-weight: bold; font-family: monospace; border-radius: 3px;"
        self.lbl_res_pedestal = QLabel()
        self.lbl_res_pedestal.setStyleSheet(res_style)
        time_vbox.addWidget(QLabel("▶ Recommended BaselineSamples (Pedestal):"))
        time_vbox.addWidget(self.lbl_res_pedestal)

        self.btn_apply_time = QPushButton("⚡ Apply Time & DSP Configs")
        self.btn_apply_time.setStyleSheet("background-color: #fd7e14; color: white; font-weight: bold; padding: 5px;")
        self.btn_apply_time.clicked.connect(self.apply_time_to_table)
        time_vbox.addWidget(self.btn_apply_time)
        
        time_group.setLayout(time_vbox)
        right_layout.addWidget(time_group)

        # ------------------------------------------
        # 3. ADC 파라미터 시뮬레이터 
        # ------------------------------------------
        sim_group = QGroupBox("🧮 ADC Parameter Simulator (14-bit)")
        sim_group.setStyleSheet("QGroupBox { font-weight: bold; color: #198754; }")
        sim_vbox = QVBoxLayout()

        input_grid = QGridLayout()
        input_grid.addWidget(QLabel("Target Baseline (%):"), 0, 0)
        self.spin_base_pct = QSpinBox()
        self.spin_base_pct.setRange(10, 95)
        self.spin_base_pct.setValue(90) 
        self.spin_base_pct.setSuffix(" %")
        self.spin_base_pct.valueChanged.connect(self.update_adc_simulator)
        input_grid.addWidget(self.spin_base_pct, 0, 1)

        input_grid.addWidget(QLabel("Trigger Depth (mV):"), 1, 0)
        self.spin_trg_mv = QDoubleSpinBox()
        self.spin_trg_mv.setRange(1.0, 1000.0)
        self.spin_trg_mv.setValue(15.0) 
        self.spin_trg_mv.setSuffix(" mV")
        self.spin_trg_mv.valueChanged.connect(self.update_adc_simulator)
        input_grid.addWidget(self.spin_trg_mv, 1, 1)
        sim_vbox.addLayout(input_grid)

        self.lbl_res_offset = QLabel()
        self.lbl_res_offset.setStyleSheet(res_style)
        sim_vbox.addWidget(QLabel("▶ Required DCOffset (Inverted DAC):"))
        sim_vbox.addWidget(self.lbl_res_offset)

        self.lbl_res_trg = QLabel()
        self.lbl_res_trg.setStyleSheet(res_style)
        sim_vbox.addWidget(QLabel("▶ Required TriggerThreshold (ADC):"))
        sim_vbox.addWidget(self.lbl_res_trg)

        self.btn_apply_adc = QPushButton("⚡ Apply ADC to Active Channels")
        self.btn_apply_adc.setStyleSheet("background-color: #198754; color: white; font-weight: bold; padding: 5px;")
        self.btn_apply_adc.clicked.connect(self.apply_adc_to_table)
        sim_vbox.addWidget(self.btn_apply_adc)

        pg.setConfigOptions(antialias=True, background='#f8f9fa', foreground='#212529')
        self.plot_sim = pg.PlotWidget(title="Dynamic Range Visualizer")
        self.plot_sim.setYRange(0, 16383, padding=0)
        self.plot_sim.setXRange(0, 1, padding=0)
        self.plot_sim.hideAxis('bottom')
        self.plot_sim.setLabel('left', "ADC Bins (14-bit)")
        
        self.line_base = pg.InfiniteLine(angle=0, pen=pg.mkPen('#198754', width=2, style=Qt.DashLine))
        self.line_trg = pg.InfiniteLine(angle=0, pen=pg.mkPen('#dc3545', width=2))
        self.plot_sim.addItem(self.line_base)
        self.plot_sim.addItem(self.line_trg)
        sim_vbox.addWidget(self.plot_sim)
        
        sim_group.setLayout(sim_vbox)
        right_layout.addWidget(sim_group, stretch=1)
        
        layout.addLayout(right_layout, stretch=3)

    # ==========================================
    # 로직 구현부
    # ==========================================
    def update_mask_calc(self):
        mask = sum((1 << i) for i, chk in enumerate(self.ch_checks) if chk.isChecked())
        self.lbl_mask_res.setText(str(mask))

    def apply_mask_to_table(self):
        if self.table.rowCount() == 0: return
        self.set_table_value("Digitizer", "ChannelMask", self.lbl_mask_res.text())

    def update_time_simulator(self):
        rec_len = self.spin_record.value()
        post_pct = self.spin_post.value()
        # 제1원리: Pre-Trigger 샘플 수 = 전체 * (100 - Post%)
        pre_trg_samples = int(rec_len * ((100 - post_pct) / 100.0))
        # 노이즈를 피하기 위해 Pre-Trigger 구역의 80%만 페데스탈(Baseline) 측정에 사용
        recommended_pedestal = int(pre_trg_samples * 0.8)
        
        self.lbl_res_pedestal.setText(f"{recommended_pedestal}  (Pre-Trg: {pre_trg_samples} * 80%)")

    def apply_time_to_table(self):
        if self.table.rowCount() == 0: return
        self.set_table_value("Digitizer", "RecordLength", str(self.spin_record.value()))
        self.set_table_value("Digitizer", "PostTrigger", str(self.spin_post.value()))
        
        rec_len = self.spin_record.value()
        post_pct = self.spin_post.value()
        pre_trg_samples = int(rec_len * ((100 - post_pct) / 100.0))
        recommended_pedestal = str(int(pre_trg_samples * 0.8))
        
        self.set_table_value("SoftwareDSP", "BaselineSamples", recommended_pedestal)
        self.set_table_value("SoftwareDSP", "CoincidenceWindow", str(self.spin_coin.value()))

    def update_adc_simulator(self):
        base_pct = self.spin_base_pct.value() / 100.0
        trg_mv = self.spin_trg_mv.value()
        
        dac_offset = int((1.0 - base_pct) * 65535)
        adc_baseline = int(base_pct * 16383)
        adc_trg_drop = int(trg_mv / 0.122) 
        adc_trigger = adc_baseline - adc_trg_drop
        
        self.lbl_res_offset.setText(f"{dac_offset}  (Target: {self.spin_base_pct.value()}%)")
        self.lbl_res_trg.setText(f"{adc_trigger}  (Baseline {adc_baseline} - Drop {adc_trg_drop})")
        
        self.line_base.setValue(adc_baseline)
        self.line_trg.setValue(adc_trigger)
        
        if adc_trigger < 0:
            self.lbl_res_trg.setStyleSheet("background-color: #dc3545; color: white; padding: 5px; font-weight: bold;")
        else:
            self.lbl_res_trg.setStyleSheet("background-color: #e9ecef; padding: 5px; font-weight: bold; font-family: monospace;")

    def apply_adc_to_table(self):
        if self.table.rowCount() == 0: return
        base_pct = self.spin_base_pct.value() / 100.0
        trg_mv = self.spin_trg_mv.value()
        calc_offset = str(int((1.0 - base_pct) * 65535))
        calc_trg = str(int((base_pct * 16383) - (trg_mv / 0.122)))

        for row in range(self.table.rowCount()):
            section = self.table.item(row, 0).text()
            param = self.table.item(row, 1).text()
            if section.startswith("Channel_"):
                if param == "DCOffset":
                    self.table.setItem(row, 2, QTableWidgetItem(calc_offset))
                    self.table.item(row, 2).setBackground(Qt.yellow)
                elif param == "TriggerThreshold":
                    self.table.setItem(row, 2, QTableWidgetItem(calc_trg))
                    self.table.item(row, 2).setBackground(Qt.yellow)

    def set_table_value(self, target_section, target_param, value):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == target_section and self.table.item(row, 1).text() == target_param:
                self.table.setItem(row, 2, QTableWidgetItem(value))
                self.table.item(row, 2).setBackground(Qt.yellow)
                return
        # 만약 해당 파라미터가 없으면 새로 추가
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(target_section))
        self.table.setItem(row, 1, QTableWidgetItem(target_param))
        self.table.setItem(row, 2, QTableWidgetItem(value))
        self.table.item(row, 2).setBackground(Qt.yellow)

    def load_config(self):
        default_dir = os.path.abspath(os.path.join(self.bin_dir, "..", "config"))
        path, _ = QFileDialog.getOpenFileName(self, "Select Config File", default_dir, "Config Files (*.conf *.ini);;All Files (*)")
        if not path: return
        self.current_config_path = path
        self.lbl_current_file.setText(f"Current File: {os.path.basename(path)}")
        self.config.read(path)
        self.table.setRowCount(0)
        for section in self.config.sections():
            for key, val in self.config.items(section):
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(section))
                self.table.setItem(row, 1, QTableWidgetItem(key))
                self.table.setItem(row, 2, QTableWidgetItem(val))
        try:
            mask_val = int(self.config.get("Digitizer", "ChannelMask", fallback="1"))
            for i, chk in enumerate(self.ch_checks):
                chk.setChecked(bool((mask_val >> i) & 1))
        except: pass

    def save_config(self):
        if not self.current_config_path: return
        self.config.clear()
        for row in range(self.table.rowCount()):
            sec = self.table.item(row, 0).text()
            key = self.table.item(row, 1).text()
            val = self.table.item(row, 2).text()
            if not self.config.has_section(sec): self.config.add_section(sec)
            self.config.set(sec, key, val)
            self.table.item(row, 2).setBackground(Qt.white) 
        with open(self.current_config_path, 'w') as configfile:
            self.config.write(configfile)