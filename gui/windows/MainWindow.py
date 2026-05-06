from PyQt5.QtWidgets import QMainWindow, QTabWidget
from widgets.DaqTab import DaqTab
from widgets.ConfigTab import ConfigTab
from widgets.MonitorTab import MonitorTab
from widgets.ProductionTab import ProductionTab
from widgets.DatabaseTab import DatabaseTab

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HEP 3-Tier DAQ Control Center")
        self.resize(1200, 900)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.daq_tab = DaqTab()
        self.config_tab = ConfigTab()
        self.monitor_tab = MonitorTab()
        # 🌟 인자 없이 깔끔하게 탭만 생성합니다.
        self.production_tab = ProductionTab()
        self.database_tab = DatabaseTab()

        self.tabs.addTab(self.daq_tab, "🚀 DAQ Control")
        self.tabs.addTab(self.config_tab, "⚙️ Hardware Config")
        self.tabs.addTab(self.monitor_tab, "📈 Live Monitor")
        self.tabs.addTab(self.production_tab, "🔬 Offline Production")
        self.tabs.addTab(self.database_tab, "🗄️ Run DB History")

    def closeEvent(self, event):
        self.daq_tab.stop_all()
        self.monitor_tab.cleanup()
        self.production_tab.stop_all()
        event.accept()
