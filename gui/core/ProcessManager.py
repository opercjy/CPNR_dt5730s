import subprocess
import re
from PyQt5.QtCore import QThread, pyqtSignal

class ProcessManager(QThread):
    log_signal = pyqtSignal(str)
    stat_signal = pyqtSignal(dict) 
    finished_signal = pyqtSignal(int)

    def __init__(self, cmd, cwd=None):
        super().__init__()
        self.cmd = cmd
        self.cwd = cwd
        self.process = None
        self.is_running = False
        
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])|\r')

    def run(self):
        self.is_running = True
        try:
            self.process = subprocess.Popen(
                self.cmd,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            for line in iter(self.process.stdout.readline, ''):
                if not self.is_running:
                    break
                if line:
                    clean_line = self.ansi_escape.sub('', line).strip()
                    if not clean_line:
                        continue
                    
                    if "[LIVE DAQ]" in clean_line:
                        self._parse_and_emit_stats(clean_line)
                    else:
                        self.log_signal.emit(clean_line)
            
            self.process.wait()
            self.finished_signal.emit(self.process.returncode)
        except Exception as e:
            self.log_signal.emit(f"[Error] Process execution failed: {e}")
            self.finished_signal.emit(-1)
        finally:
            self.is_running = False

    def _parse_and_emit_stats(self, line):
        try:
            stats = {}
            parts = line.split("|")
            for part in parts:
                if "Time:" in part:
                    stats['time'] = part.split("Time:")[1].strip()
                elif "Events:" in part:
                    stats['events'] = part.split("Events:")[1].strip()
                elif "Trg Rate:" in part:
                    stats['rate'] = part.split("Trg Rate:")[1].strip()
                elif "Speed:" in part:
                    stats['speed'] = part.split("Speed:")[1].strip()
                elif "ZMQ Drops" in part:
                    stats['drops'] = part.split(":")[1].strip()
            self.stat_signal.emit(stats)
        except Exception:
            pass

    def stop(self):
        self.is_running = False
        if self.process and self.process.poll() is None:
            self.log_signal.emit("[System] Sending SIGINT to gracefully stop the process...")
            self.process.send_signal(2)
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()