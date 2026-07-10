"""
Migrate all data from the old SQLite database (attendance.db) to PostgreSQL.

Steps:
  1. Create the Postgres database first:
       sudo -u postgres psql -c "CREATE DATABASE housekeep;"
  2. Set the target in .env:
       DATABASE_URL=postgresql+psycopg2://postgres:YOURPASS@localhost:5432/housekeep
  3. pip install psycopg2-binary
  4. Run:
       python migrate_sqlite_to_postgres.py --sqlite ./attendance.db

Copies: users, staff, face_embeddings (binary embeddings included),
attendance_punches, attendance_records, audit_logs — preserving IDs so
all foreign keys stay intact. Safe to re-run: it skips rows whose ID
already exists in Postgres.
"""
import argparse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, init_db
from app.models.user import User
from app.models.staff import Staff, FaceEmbedding
from app.models.attendance import AttendancePunch, AttendanceRecord
from app.models.audit import AuditLog

# Order matters: parents before children (FK integrity)
TABLES = [User, Staff, FaceEmbedding, AttendancePunch, AttendanceRecord, AuditLog]


def copy_table(model, src, dst):
    name = model.__tablename__
    existing_ids = {row[0] for row in dst.query(model.id).all()}
    rows = src.query(model).all()
    copied = 0
    for row in rows:
        if row.id in existing_ids:
            continue
        data = {c.name: getattr(row, c.name) for c in model.__table__.columns}
        dst.add(model(**data))
        copied += 1
    dst.commit()
    print(f"  {name:22s} copied {copied:5d} / {len(rows)} rows")


def fix_sequences(engine):
    """Postgres sequences must be bumped past the max copied IDs."""
    with engine.connect() as conn:
        from sqlalchemy import text
        for model in TABLES:
            t = model.__tablename__
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {t}), 1))"
            ))
        conn.commit()
    print("  sequences updated ✔")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default="./attendance.db",
                    help="Path to the old SQLite database file")
    args = ap.parse_args()

    if "postgresql" not in settings.DATABASE_URL:
        raise SystemExit("DATABASE_URL in .env is not Postgres — aborting.")

    print(f"Source : sqlite:///{args.sqlite}")
    print(f"Target : {settings.DATABASE_URL.split('@')[-1]}")

    src_engine = create_engine(f"sqlite:///{args.sqlite}",
                               connect_args={"check_same_thread": False})
    SrcSession = sessionmaker(bind=src_engine)

    # Create all tables on Postgres
    init_db()
    from app.database import SessionLocal as DstSession, engine as dst_engine

    src, dst = SrcSession(), DstSession()
    try:
        for model in TABLES:
            copy_table(model, src, dst)
        fix_sequences(dst_engine)
        print("\n✅ Migration complete. Point the app at Postgres and restart.")
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    main()
