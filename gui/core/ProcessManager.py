import subprocess
import re
from PyQt6.QtCore import QThread, pyqtSignal

class ProcessManager(QThread):
    log_signal = pyqtSignal(str)
    stat_signal = pyqtSignal(dict) 
    finished_signal = pyqtSignal(int)
    
    temp_signal = pyqtSignal(float)
    led_signal = pyqtSignal(dict)
    fatal_signal = pyqtSignal(str) 

    def __init__(self, cmd, cwd=None):
        super().__init__()
        self.cmd = cmd
        self.cwd = cwd
        self.process = None
        self.is_running = False
        
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])|\r')
        self.re_temp = re.compile(r"\[STATUS\] TEMP:\s*([\d\.]+)")
        self.re_led = re.compile(r"\[STATUS\] LED:\s*LOCK=(\d),\s*BYPS=(\d),\s*RUN=(\d),\s*TRG=(\d),\s*DRDY=(\d),\s*BUSY=(\d)")

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
                    
                    if "[FATAL] OVER_TEMP_SOFT_KILL" in clean_line:
                        self.fatal_signal.emit("OVER_TEMP_SOFT_KILL")
                        
                    # =========================================================================
                    # [핵심 방어] 스트림 문자열 엉킴 방지 
                    # elif 대신 독립된 if문을 사용하여, 한 줄에 DAQ, TEMP, LED가 모두 엉겨있어도 
                    # 빠짐없이 캐치하여 UI로 발송합니다.
                    # =========================================================================
                    if "[STATUS] TEMP:" in clean_line:
                        m = self.re_temp.search(clean_line)
                        if m: self.temp_signal.emit(float(m.group(1)))
                        
                    if "[STATUS] LED:" in clean_line:
                        m = self.re_led.search(clean_line)
                        if m:
                            self.led_signal.emit({
                                'PLL LOCK': int(m.group(1)),
                                'PLL BYPS': int(m.group(2)),
                                'RUN': int(m.group(3)),
                                'TRG': int(m.group(4)),
                                'DRDY': int(m.group(5)),
                                'BUSY': int(m.group(6))
                            })
                            
                    if "[LIVE DAQ]" in clean_line:
                        self._parse_and_emit_stats(clean_line)
                    
                    # 일반 로그 출력 (충돌된 지저분한 상태 로그는 터미널에 보이지 않도록 필터링)
                    if "[LIVE DAQ]" not in clean_line and "[STATUS]" not in clean_line and "[FATAL]" not in clean_line:
                        self.log_signal.emit(clean_line)
            
            self.process.wait()
            self.finished_signal.emit(self.process.returncode)
        except Exception as e:
            self.log_signal.emit(f"[Error] Process execution failed: {e}")
            self.finished_signal.emit(-1)
        finally:
            self.is_running = False

    def _parse_and_emit_stats(self, line):
        """
        [정규식 기반 핀셋 추출] 
        문자열 스플릿의 취약점을 폐기하고 Regex를 도입하여,
        뒤에 어떤 쓰레기 문자가 섞여 들어와도 오직 '숫자'만 안전하게 추출합니다.
        """
        try:
            stats = {}
            if "Live:" in line:
                m = re.search(r"Live:\s*([\d\.]+)", line)
                if m: stats['live_time'] = f"{m.group(1)} s"
                
            if "DT:" in line:
                m = re.search(r"DT:\s*([\d\.]+)", line)
                if m: stats['dead_time'] = f"{m.group(1)} %"
                
            if "Events:" in line:
                m = re.search(r"Events:\s*(\d+)", line)
                if m: stats['events'] = m.group(1)
                
            if "Rate:" in line:
                m = re.search(r"Rate:\s*([\d\.]+)", line)
                if m: stats['rate'] = f"{m.group(1)} Hz"
                
            if "Speed:" in line:
                m = re.search(r"Speed:\s*([\d\.]+)", line)
                if m: stats['speed'] = f"{m.group(1)} MB/s"
                
            if "Drops:" in line:
                # 텍스트 엉김의 주범이었던 Drops 값을 정규식으로 안전하게 추출 ('0[STATUS] LED...' -> '0')
                m = re.search(r"Drops:\s*(\d+)", line)
                if m: stats['drops'] = m.group(1)

            if stats:
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