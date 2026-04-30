import sqlite3
import os

db_path = "attendance.db"
if not os.path.exists(db_path):
    print("DB not found")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT staff_id, date, total_work_minutes, regular_minutes, status FROM attendance_records WHERE status = 'Partial' AND total_work_minutes > 0;")
    rows = cursor.fetchall()
    for row in rows:
        print(row)
    conn.close()
