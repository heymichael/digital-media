#!/usr/bin/env python3
"""Apply pending migrations to the database."""

import hashlib
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def get_checksum(filepath: Path) -> str:
    """Compute MD5 checksum of a file."""
    return hashlib.md5(filepath.read_bytes()).hexdigest()


def run_migrations():
    """Apply pending migrations."""
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    conn = psycopg2.connect(dsn)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # Ensure schema_migrations table exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ DEFAULT now(),
                    applied_by TEXT
                )
            """)
            conn.commit()

            # Get already-applied migrations
            cur.execute("SELECT filename, checksum FROM schema_migrations")
            applied = {row[0]: row[1] for row in cur.fetchall()}

            # Find pending migrations
            migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
            pending = []

            for f in migration_files:
                checksum = get_checksum(f)
                if f.name in applied:
                    if applied[f.name] != checksum:
                        print(f"ERROR: Checksum mismatch for {f.name}")
                        print(f"  Expected: {applied[f.name]}")
                        print(f"  Got:      {checksum}")
                        sys.exit(1)
                else:
                    pending.append((f, checksum))

            if not pending:
                print("No pending migrations.")
                return

            # Apply pending migrations
            for filepath, checksum in pending:
                print(f"Applying {filepath.name}...")
                sql = filepath.read_text()

                try:
                    cur.execute(sql)
                    cur.execute(
                        """
                        INSERT INTO schema_migrations (filename, checksum, applied_by)
                        VALUES (%s, %s, %s)
                        """,
                        (filepath.name, checksum, os.environ.get("USER", "unknown")),
                    )
                    conn.commit()
                    print(f"  Applied successfully.")
                except Exception as e:
                    conn.rollback()
                    print(f"  FAILED: {e}")
                    sys.exit(1)

            print(f"Applied {len(pending)} migration(s).")

    finally:
        conn.close()


if __name__ == "__main__":
    run_migrations()
