#!/usr/bin/env python3
"""Bootstrap the local development database."""

import os
import subprocess
import sys
import time
from pathlib import Path

MIGRATIONS_SCRIPT = Path(__file__).parent / "run_migrations.py"


def wait_for_postgres(max_attempts: int = 30):
    """Wait for Postgres to be ready."""
    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    for i in range(max_attempts):
        try:
            conn = psycopg2.connect(dsn)
            conn.close()
            print("Postgres is ready.")
            return
        except psycopg2.OperationalError:
            print(f"Waiting for Postgres... ({i + 1}/{max_attempts})")
            time.sleep(1)

    print("ERROR: Postgres did not become ready in time.")
    sys.exit(1)


def main():
    print("Starting local Postgres container...")
    subprocess.run(
        ["docker-compose", "-f", "docker-compose.local.yml", "up", "-d"],
        check=True,
    )

    print("Waiting for Postgres to be ready...")
    wait_for_postgres()

    print("Running migrations...")
    subprocess.run([sys.executable, str(MIGRATIONS_SCRIPT)], check=True)

    print("Local database bootstrapped successfully.")


if __name__ == "__main__":
    main()
