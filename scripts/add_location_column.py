"""Simple migration: add `location` column to `staff` table if missing.

Run with: python3 scripts/add_location_column.py
"""
import os


def main():
    # Avoid importing app.config (may require extra deps). Read DATABASE_URL from env or default.
    database_url = os.getenv('DATABASE_URL', 'sqlite:///./attendance.db')
    url = database_url.lower()
    if 'sqlite' in url:
        # Extract path after sqlite:/// (supports relative paths)
        path = database_url.split('sqlite:///')[-1]
        import sqlite3
        # Resolve relative paths relative to project root (one level up from scripts/)
        script_dir = os.path.dirname(__file__)
        default = './attendance.db'
        rel = path or default
        if os.path.isabs(rel):
            db_path = rel
        else:
            db_path = os.path.abspath(os.path.join(script_dir, '..', rel))
        print(f'Using SQLite DB at: {db_path}')
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info('staff')")
        cols = [r[1] for r in cur.fetchall()]
        if 'location' in cols:
            print('Column `location` already exists in staff table.')
            conn.close()
            return
        print('Adding `location` column to staff (SQLite)...')
        cur.execute("ALTER TABLE staff ADD COLUMN location TEXT")
        conn.commit()
        conn.close()
        print('Done.')
    else:
        # Try using SQLAlchemy if available (best-effort)
        try:
            from sqlalchemy import create_engine, text
            engine = create_engine(database_url)
            with engine.connect() as conn:
                try:
                    res = conn.execute(text(
                        "SELECT column_name FROM information_schema.columns WHERE table_name='staff' AND column_name='location'"
                    )).fetchone()
                    if res:
                        print('Column `location` already exists in staff table.')
                        return
                except Exception:
                    pass
                try:
                    print('Adding `location` column to staff...')
                    conn.execute(text("ALTER TABLE staff ADD COLUMN location VARCHAR(100)"))
                    print('Done.')
                except Exception as e:
                    print('Failed to add column automatically:', str(e))
        except Exception as e:
            print('Cannot run migration automatically on this DB (missing SQLAlchemy or unsupported DB).', str(e))


if __name__ == '__main__':
    main()
