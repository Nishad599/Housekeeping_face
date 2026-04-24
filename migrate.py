"""
Migration Script: SQLite → PostgreSQL
=====================================
Transfers all data from attendance.db (SQLite) to PostgreSQL (Housekeep).

Usage:
    cd ~/Final_house/face-attendance
    python migrate_sqlite_to_postgres.py

Prerequisites:
    1. PostgreSQL is running with database 'Housekeep' created
    2. pip install psycopg2-binary (already done)
    3. SQLite file (attendance.db) exists in current directory
"""

import sqlite3
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime
import sys
import os

# ── Configuration ────────────────────────────────────────────
SQLITE_PATH = os.getenv("SQLITE_PATH", "./attendance.db")

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DB = os.getenv("PG_DB", "Housekeep")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASS = os.getenv("PG_PASS", "123456")


def connect_sqlite():
    if not os.path.exists(SQLITE_PATH):
        print(f"[ERROR] SQLite database not found: {SQLITE_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    print(f"[OK] Connected to SQLite: {SQLITE_PATH}")
    return conn


def connect_postgres():
    try:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT,
            dbname=PG_DB, user=PG_USER, password=PG_PASS
        )
        conn.autocommit = False
        print(f"[OK] Connected to PostgreSQL: {PG_DB}@{PG_HOST}:{PG_PORT}")
        return conn
    except Exception as e:
        print(f"[ERROR] Cannot connect to PostgreSQL: {e}")
        sys.exit(1)


def get_sqlite_tables(sqlite_conn):
    """Get all table names from SQLite."""
    cursor = sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return [row[0] for row in cursor.fetchall()]


def get_row_count(sqlite_conn, table):
    cursor = sqlite_conn.execute(f"SELECT COUNT(*) FROM [{table}]")
    return cursor.fetchone()[0]


def create_pg_tables(pg_conn):
    """
    Create tables in PostgreSQL matching the SQLAlchemy models.
    This ensures correct types (SERIAL, BOOLEAN, BYTEA, etc.)
    """
    cur = pg_conn.cursor()

    cur.execute("""
    -- Users table
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        full_name VARCHAR(200) NOT NULL,
        role VARCHAR(20) DEFAULT 'viewer',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS ix_users_id ON users(id);
    CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);

    -- Staff table
    CREATE TABLE IF NOT EXISTS staff (
        id SERIAL PRIMARY KEY,
        employee_id VARCHAR(50) UNIQUE NOT NULL,
        name VARCHAR(200) NOT NULL,
        designation VARCHAR(100),
        phone VARCHAR(20),
        shift_start VARCHAR(10) DEFAULT '07:00',
        shift_end VARCHAR(10) DEFAULT '16:00',
        weekly_off VARCHAR(20) DEFAULT 'Sunday',
        is_active BOOLEAN DEFAULT TRUE,
        location VARCHAR(100),
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS ix_staff_id ON staff(id);
    CREATE INDEX IF NOT EXISTS ix_staff_employee_id ON staff(employee_id);

    -- Face Embeddings table
    CREATE TABLE IF NOT EXISTS face_embeddings (
        id SERIAL PRIMARY KEY,
        staff_id INTEGER NOT NULL REFERENCES staff(id),
        embedding BYTEA NOT NULL,
        version INTEGER DEFAULT 1,
        is_active BOOLEAN DEFAULT TRUE,
        registered_at TIMESTAMP DEFAULT NOW(),
        archived_at TIMESTAMP,
        registered_by VARCHAR(100)
    );
    CREATE INDEX IF NOT EXISTS ix_face_embeddings_id ON face_embeddings(id);

    -- Attendance Punches table
    CREATE TABLE IF NOT EXISTS attendance_punches (
        id SERIAL PRIMARY KEY,
        staff_id INTEGER NOT NULL REFERENCES staff(id),
        punch_type VARCHAR(10) NOT NULL,
        punch_time TIMESTAMP NOT NULL,
        confidence FLOAT,
        is_valid BOOLEAN DEFAULT TRUE,
        rejection_reason VARCHAR(500),
        device_info VARCHAR(200),
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS ix_attendance_punches_id ON attendance_punches(id);

    -- Attendance Records table
    CREATE TABLE IF NOT EXISTS attendance_records (
        id SERIAL PRIMARY KEY,
        staff_id INTEGER NOT NULL REFERENCES staff(id),
        date DATE NOT NULL,
        punch_in_time TIMESTAMP,
        punch_out_time TIMESTAMP,
        total_work_minutes INTEGER DEFAULT 0,
        regular_minutes INTEGER DEFAULT 0,
        ot_minutes INTEGER DEFAULT 0,
        status VARCHAR(20) DEFAULT 'Absent',
        is_edited BOOLEAN DEFAULT FALSE,
        edited_by VARCHAR(100),
        edited_at TIMESTAMP,
        edit_reason VARCHAR(500),
        original_punch_in TIMESTAMP,
        original_punch_out TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS ix_attendance_records_id ON attendance_records(id);
    CREATE INDEX IF NOT EXISTS ix_attendance_records_date ON attendance_records(date);

    -- Audit Log table
    CREATE TABLE IF NOT EXISTS audit_log (
        id SERIAL PRIMARY KEY,
        action VARCHAR(100) NOT NULL,
        entity_type VARCHAR(50),
        entity_id INTEGER,
        performed_by VARCHAR(100) DEFAULT 'system',
        details TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS ix_audit_log_id ON audit_log(id);
    """)

    pg_conn.commit()
    print("[OK] PostgreSQL tables created")


def migrate_table(sqlite_conn, pg_conn, table_name, columns, has_binary=False):
    """Migrate a single table from SQLite to PostgreSQL."""
    count = get_row_count(sqlite_conn, table_name)
    if count == 0:
        print(f"  [{table_name}] Empty — skipping")
        return 0

    # Read from SQLite
    col_list = ", ".join([f"[{c}]" for c in columns])
    rows = sqlite_conn.execute(f"SELECT {col_list} FROM [{table_name}]").fetchall()

    # Insert into PostgreSQL
    pg_cur = pg_conn.cursor()
    pg_col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO {table_name} ({pg_col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    inserted = 0
    for row in rows:
        values = []
        for i, val in enumerate(row):
            # Convert SQLite integer booleans to Python bools for PostgreSQL
            col = columns[i]
            if col in ("is_active", "is_valid", "is_edited") and isinstance(val, int):
                values.append(bool(val))
            elif val == "" and col in ("created_at", "updated_at", "edited_at", "archived_at", "registered_at", "punch_time"):
                values.append(None)
            elif isinstance(val, bytes) and has_binary and col == "embedding":
                values.append(psycopg2.Binary(val))
            else:
                values.append(val)
        try:
            pg_cur.execute(insert_sql, values)
            inserted += 1
        except Exception as e:
            print(f"  [WARN] Row skipped in {table_name}: {e}")
            pg_conn.rollback()
            continue

    pg_conn.commit()
    print(f"  [{table_name}] Migrated {inserted}/{count} rows")
    return inserted


def reset_sequences(pg_conn):
    """Reset PostgreSQL sequences to max(id) + 1 for each table."""
    pg_cur = pg_conn.cursor()
    tables = ["users", "staff", "face_embeddings", "attendance_punches", "attendance_records", "audit_log"]
    for table in tables:
        try:
            pg_cur.execute(f"SELECT MAX(id) FROM {table}")
            max_id = pg_cur.fetchone()[0]
            if max_id:
                pg_cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), {max_id})")
                print(f"  [{table}] Sequence reset to {max_id}")
        except Exception as e:
            print(f"  [{table}] Sequence reset skipped: {e}")
            pg_conn.rollback()
    pg_conn.commit()


def main():
    print("=" * 60)
    print("  SQLite → PostgreSQL Migration")
    print("  Database: Housekeep")
    print("=" * 60)

    sqlite_conn = connect_sqlite()
    pg_conn = connect_postgres()

    # Show what's in SQLite
    tables = get_sqlite_tables(sqlite_conn)
    print(f"\n[INFO] SQLite tables found: {tables}")
    for t in tables:
        print(f"  {t}: {get_row_count(sqlite_conn, t)} rows")

    # Step 1: Create tables in PostgreSQL
    print("\n── Step 1: Creating PostgreSQL tables ──")
    create_pg_tables(pg_conn)

    # Step 2: Migrate data (order matters for foreign keys)
    print("\n── Step 2: Migrating data ──")

    # Users
    migrate_table(sqlite_conn, pg_conn, "users",
        ["id", "username", "password_hash", "full_name", "role", "is_active", "created_at"])

    # Staff
    migrate_table(sqlite_conn, pg_conn, "staff",
        ["id", "employee_id", "name", "designation", "phone",
         "shift_start", "shift_end", "weekly_off", "is_active", "location",
         "created_at", "updated_at"])

    # Face Embeddings (has binary data)
    migrate_table(sqlite_conn, pg_conn, "face_embeddings",
        ["id", "staff_id", "embedding", "version", "is_active",
         "registered_at", "archived_at", "registered_by"],
        has_binary=True)

    # Attendance Punches
    migrate_table(sqlite_conn, pg_conn, "attendance_punches",
        ["id", "staff_id", "punch_type", "punch_time", "confidence",
         "is_valid", "rejection_reason", "device_info", "created_at"])

    # Attendance Records
    migrate_table(sqlite_conn, pg_conn, "attendance_records",
        ["id", "staff_id", "date", "punch_in_time", "punch_out_time",
         "total_work_minutes", "regular_minutes", "ot_minutes", "status",
         "is_edited", "edited_by", "edited_at", "edit_reason",
         "original_punch_in", "original_punch_out", "created_at", "updated_at"])

    # Audit Log
    migrate_table(sqlite_conn, pg_conn, "audit_log",
        ["id", "action", "entity_type", "entity_id", "performed_by",
         "details", "created_at"])

    # Step 3: Reset sequences
    print("\n── Step 3: Resetting sequences ──")
    reset_sequences(pg_conn)

    # Step 4: Verify
    print("\n── Step 4: Verification ──")
    pg_cur = pg_conn.cursor()
    for t in ["users", "staff", "face_embeddings", "attendance_punches", "attendance_records", "audit_log"]:
        pg_cur.execute(f"SELECT COUNT(*) FROM {t}")
        pg_count = pg_cur.fetchone()[0]
        print(f"  [{t}] PostgreSQL: {pg_count} rows")

    sqlite_conn.close()
    pg_conn.close()

    print("\n" + "=" * 60)
    print("  Migration complete!")
    print("  Next steps:")
    print("    1. Update .env: DATABASE_URL=postgresql+psycopg2://postgres:123456@localhost:5432/Housekeep")
    print("    2. Restart the app: bash stop.sh && bash start.sh")
    print("    3. Verify the app works, then optionally rename attendance.db")
    print("=" * 60)


if __name__ == "__main__":
    main()