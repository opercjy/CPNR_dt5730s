from PyQt5.QtWidgets import QMainWindow, QTabWidget
from widgets.DaqTab import DaqTab
from widgets.ConfigTab import ConfigTab
from widgets.MonitorTab import MonitorTab
from widgets.ProductionTab import ProductionTab
from widgets.DatabaseTab import DatabaseTab
from core.ProcessManager import ProcessManager


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HEP 3-Tier DAQ Control Center")
        self.resize(1200, 900)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        self.production_pm = ProcessManager()

        self.daq_tab = DaqTab()
        self.config_tab = ConfigTab()
        self.monitor_tab = MonitorTab()
        self.production_tab = ProductionTab(self.production_pm)
        self.database_tab = DatabaseTab()

        self.tabs.addTab(self.daq_tab, "🚀 DAQ Control")
        self.tabs.addTab(self.config_tab, "⚙️ Hardware Config")
        self.tabs.addTab(self.monitor_tab, "📈 Live Monitor")
        self.tabs.addTab(self.production_tab, "🔬 Offline Production")
        self.tabs.addTab(self.database_tab, "🗄️ Run DB History")

    def closeEvent(self, event):
        """프로그램 종료 시 실행 중인 모든 백그라운드 프로세스와 스레드를 안전하게 정리합니다."""
        self.daq_tab.stop_all()
        self.monitor_tab.cleanup()
        
        if hasattr(self, 'production_pm') and self.production_pm.process:
            if self.production_pm.process.state() == self.production_pm.process.Running:
                self.production_pm.stop_process()
                
        event.accept()
