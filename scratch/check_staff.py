import sqlite3
import os

db_path = "attendance.db"
if not os.path.exists(db_path):
    print("DB not found")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT employee_id, name, shift_start, shift_end FROM staff WHERE name LIKE '%Ravindra%' OR name LIKE '%Monica%';")
    rows = cursor.fetchall()
    for row in rows:
        print(row)
    conn.close()
