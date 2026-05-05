import os
import sqlite3
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QMessageBox)

class DatabaseTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        self.db_path = os.path.join(self.bin_dir, "data", "run_history.db")
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        btn_layout = QHBoxLayout()
        self.btn_refresh = QPushButton("🔄 Refresh Database")
        self.btn_refresh.setStyleSheet("font-weight: bold; padding: 8px;")
        self.btn_refresh.clicked.connect(self.load_data)
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Run ID", "Start Time", "Output File", "Applied HV (V)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

    def load_data(self):
        if not os.path.exists(self.db_path):
            QMessageBox.information(self, "Info", "Database file not found yet. Start a DAQ run first.")
            return

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, start_time, output_file, applied_hv FROM runs ORDER BY id DESC")
            rows = cursor.fetchall()
            conn.close()

            self.table.setRowCount(0)
            for row_idx, row_data in enumerate(rows):
                self.table.insertRow(row_idx)
                for col_idx, col_data in enumerate(row_data):
                    item = QTableWidgetItem(str(col_data))
                    item.setFlags(item.flags() & ~2)
                    self.table.setItem(row_idx, col_idx, item)
        except Exception as e:
            QMessageBox.critical(self, "DB Error", f"Failed to load database:\n{e}")

    def showEvent(self, event):
        self.load_data()
        super().showEvent(event)