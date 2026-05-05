import sqlite3
import os
import datetime

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT,
                output_file TEXT,
                applied_hv INTEGER,
                config_snapshot TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def record_run_start(self, output_file, applied_hv, config_path):
        config_text = ""
        try:
            with open(config_path, 'r') as f:
                config_text = f.read()
        except Exception as e:
            config_text = f"Failed to read config: {e}"

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO runs (start_time, output_file, applied_hv, config_snapshot)
            VALUES (?, ?, ?, ?)
        ''', (now, output_file, applied_hv, config_text))
        run_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return run_id