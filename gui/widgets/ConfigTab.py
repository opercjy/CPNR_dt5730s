import os
import configparser
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QLabel,
)


class ConfigTab(QWidget):
    """
    [작성 목적 및 작동 원리]
    Model-View 구조를 적용하여 INI 형식의 설정(.conf) 파일을 파이썬 딕셔너리로 파싱하고,
    이를 QTableWidget에 바인딩합니다.
    UI에서 파라미터(DCOffset, TriggerThreshold 등)를 수정 후 Save를 누르면,
    곧바로 백엔드(C++)가 다음 구동 시 읽어들일 수 있도록 파일 시스템에 덮어씁니다.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bin_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        # 백엔드 C++가 읽는 원본 설정 파일의 경로
        self.config_path = os.path.join(
            self.bin_dir, "config", "dt5730s_inorganic.conf"
        )

        self.parser = configparser.ConfigParser()
        # 파서가 Key의 대소문자를 강제로 소문자로 바꾸는 현상 방지
        self.parser.optionxform = str

        self.setup_ui()
        self.load_config()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        self.lbl_path = QLabel(f"Target Config: {self.config_path}")
        header_layout.addWidget(self.lbl_path)

        self.btn_load = QPushButton("Reload")
        self.btn_save = QPushButton("Save Changes")
        self.btn_save.setStyleSheet(
            "background-color: #007bff; color: white; font-weight: bold;"
        )
        header_layout.addWidget(self.btn_load)
        header_layout.addWidget(self.btn_save)
        layout.addLayout(header_layout)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Section", "Parameter", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)

        self.btn_load.clicked.connect(self.load_config)
        self.btn_save.clicked.connect(self.save_config)

    def load_config(self):
        if not os.path.exists(self.config_path):
            QMessageBox.warning(
                self, "Warning", f"Config file not found:\n{self.config_path}"
            )
            return

        self.parser.read(self.config_path)
        self.table.setRowCount(0)

        row = 0
        for section in self.parser.sections():
            for key, val in self.parser.items(section):
                self.table.insertRow(row)

                item_sec = QTableWidgetItem(section)
                item_sec.setFlags(item_sec.flags() & ~2)  # Section 열 Read-only

                item_key = QTableWidgetItem(key)
                item_key.setFlags(item_key.flags() & ~2)  # Key 열 Read-only

                self.table.setItem(row, 0, item_sec)
                self.table.setItem(row, 1, item_key)
                self.table.setItem(row, 2, QTableWidgetItem(val))
                row += 1

    def save_config(self):
        # 테이블의 변경 사항을 임시 파서에 반영
        for row in range(self.table.rowCount()):
            sec = self.table.item(row, 0).text()
            key = self.table.item(row, 1).text()
            val = self.table.item(row, 2).text()

            if not self.parser.has_section(sec):
                self.parser.add_section(sec)
            self.parser.set(sec, key, val)

        # 실제 파일 시스템으로 기록 (Single Source of Truth)
        try:
            with open(self.config_path, "w") as f:
                self.parser.write(f)
            QMessageBox.information(
                self, "Success", "Configuration saved successfully!"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to save configuration:\n{str(e)}"
            )
