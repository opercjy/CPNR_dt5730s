import sqlite3
import os
import datetime

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        # 디렉토리가 없으면 생성
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # hv 컬럼을 문자열(TEXT)도 수용할 수 있도록 유연하게 설계
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS run_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT,
                output_file TEXT,
                hv TEXT,
                config_dump TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def record_run_start(self, output_file, hv_str, config_path):
        """DAQ 런 시작 시각과 메타데이터, .conf 파일의 스냅샷을 DB에 기록합니다."""
        config_dump = ""
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config_dump = f.read()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute('''
            INSERT INTO run_history (start_time, output_file, hv, config_dump)
            VALUES (?, ?, ?, ?)
        ''', (start_time, output_file, str(hv_str), config_dump))
        
        run_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return run_id