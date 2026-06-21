#!/usr/bin/env python3
"""
import_mock_seed_to_mysql.py  —  Phase 3/4

Read seed SQL files (seed_shops.sql, seed_vouchers.sql, rollback.sql)
and execute them against a MySQL database.

Dry-run by default: only prints what would be done.
Use --apply to execute seed, --rollback to execute rollback.

Database credentials are read from environment variables.
No passwords are hardcoded.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = PROJECT_ROOT / "db" / "seed" / "local_life"

# Environment variable names for MySQL connection
ENV_HOST = "HMDP_MYSQL_HOST"
ENV_PORT = "HMDP_MYSQL_PORT"
ENV_DATABASE = "HMDP_MYSQL_DATABASE"
ENV_USER = "HMDP_MYSQL_USER"
ENV_PASSWORD = "HMDP_MYSQL_PASSWORD"

DEFAULT_PORT = 3306

SEED_FILES = ["seed_shops.sql", "seed_vouchers.sql"]
ROLLBACK_FILES = ["rollback.sql"]


# ── Helpers ──────────────────────────────────────────────────


def _mask_password(pw: str) -> str:
    """Mask password for safe logging."""
    if not pw:
        return "(empty)"
    if len(pw) <= 4:
        return "*" * len(pw)
    return pw[:2] + "*" * (len(pw) - 4) + pw[-2:]


def _read_sql_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"SQL file not found: {path}")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise RuntimeError(f"SQL file is empty: {path}")
    return content


def _get_db_config() -> dict[str, Any]:
    """Read DB connection parameters from environment variables."""
    host = os.environ.get(ENV_HOST, "")
    port_str = os.environ.get(ENV_PORT, str(DEFAULT_PORT))
    database = os.environ.get(ENV_DATABASE, "")
    user = os.environ.get(ENV_USER, "")

    missing = []
    if not host:
        missing.append(ENV_HOST)
    if not database:
        missing.append(ENV_DATABASE)
    if not user:
        missing.append(ENV_USER)

    try:
        port = int(port_str)
    except ValueError:
        print(f"  [ERROR] {ENV_PORT}='{port_str}' is not a valid port number.")
        raise SystemExit(1)

    return {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": os.environ.get(ENV_PASSWORD, ""),
        "_missing": missing,
    }


def _non_comment_lines_count(sql: str) -> int:
    """Count lines that are non-empty and not comments."""
    return sum(
        1 for line in sql.splitlines()
        if line.strip() and not line.strip().startswith("--")
        and not line.strip().startswith("SET ")
    )


# ── Execution (connects to MySQL) ────────────────────────────


def execute_sql_files(
    sql_files: list[str], db_config: dict[str, Any]
) -> int:
    """Execute SQL files against the database.

    Each file is split by ';' and individual statements are executed.
    SET statements (charset, FK checks) are included.

    Args:
        sql_files: list of filenames relative to SEED_DIR.
        db_config: database connection parameters.

    Returns:
        Number of DML statements executed.

    Raises:
        ImportError: if mysql-connector-python is not installed.
        RuntimeError: on SQL execution failure.
    """
    missing = db_config.get("_missing", [])
    if missing:
        raise RuntimeError(
            f"Database not configured. Missing env vars: {', '.join(missing)}"
        )

    import mysql.connector  # noqa: E402 — lazy import, only needed when actually writing

    conn = mysql.connector.connect(
        host=db_config["host"],
        port=db_config["port"],
        database=db_config["database"],
        user=db_config["user"],
        password=db_config.get("password", ""),
    )

    try:
        cursor = conn.cursor()
        total_dml = 0
        for fname in sql_files:
            fpath = SEED_DIR / fname
            sql = _read_sql_file(fpath)
            statements = [s.strip() for s in sql.split(";") if s.strip()]
            dml_count = 0
            for stmt in statements:
                cursor.execute(stmt)
                dml_count += 1
            conn.commit()
            total_dml += dml_count
            print(f"  [exec] {fname} — executed ({dml_count} statements, committed).")
        return total_dml
    except ImportError:
        raise
    except FileNotFoundError:
        raise
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"SQL execution failed: {e}") from e
    finally:
        conn.close()


# ── Main ─────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Import mock seed SQL into MySQL (Phase 3). "
            "Dry-run by default. Use --apply or --rollback to execute."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute seed SQL (seed_shops.sql + seed_vouchers.sql).",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Execute rollback SQL (rollback.sql).",
    )
    parser.add_argument(
        "--env",
        default="local",
        choices=["local", "dev", "staging", "prod"],
        help="Environment label (informational only, does not change config source).",
    )
    args = parser.parse_args()

    # Validate mutual exclusion
    if args.apply and args.rollback:
        print("  [ERROR] --apply and --rollback cannot be used together.")
        raise SystemExit(1)

    # Determine action and which files to use
    if args.rollback:
        action = "rollback"
        sql_files = ROLLBACK_FILES
        label = "rollback DELETE"
    elif args.apply:
        action = "apply"
        sql_files = SEED_FILES
        label = "seed INSERT"
    else:
        action = "dry-run"
        sql_files = SEED_FILES
        label = "seed INSERT"

    print("=" * 60)
    print("  import_mock_seed_to_mysql.py  —  Phase 3")
    print("=" * 60)
    print(f"  Seed dir : {SEED_DIR}")
    print(f"  Action   : {action}")
    print(f"  Env      : {args.env}")
    print()

    # Check seed dir exists
    if not SEED_DIR.exists():
        print(f"  [ERROR] Seed directory not found: {SEED_DIR}")
        print("  Run Phase 1 (normalize) and Phase 2 (generate SQL) first.")
        raise SystemExit(1)

    # Read DB config (may be incomplete — that's OK for dry-run)
    db_config = _get_db_config()
    has_config = not bool(db_config.get("_missing", []))
    masked_pw = _mask_password(str(db_config.get("password", "")))

    if has_config:
        print(
            f"  Database : {db_config['user']}@{db_config['host']}:"
            f"{db_config['port']}/{db_config['database']}"
        )
        print(f"  Password : {masked_pw}")
    else:
        missing = db_config["_missing"]
        print(f"  Database : not configured (missing: {', '.join(missing)})")
        print(f"  (Set {ENV_HOST}, {ENV_DATABASE}, {ENV_USER} to configure)")
    print()

    # ── Dry-run path (default) ─────────────────────────────
    if not args.apply and not args.rollback:
        print(f"  [dry-run] Would execute {label}:")
        for fname in sql_files:
            fpath = SEED_DIR / fname
            if fpath.exists():
                content = _read_sql_file(fpath)
                ncl = _non_comment_lines_count(content)
                print(f"    {fname}  ({ncl} data lines)")
            else:
                print(f"    {fname}  [FILE NOT FOUND]")
        print("  [dry-run] No SQL was executed. No database connection was made.")
        print()
        print("─" * 60)
        print("  Dry-run complete. Pass --apply to execute seed or --rollback to revert.")
        print("=" * 60)
        return

    # ── Execute path ───────────────────────────────────────
    if not has_config:
        print(
            f"  [ERROR] Database not configured. "
            f"Set {ENV_HOST}, {ENV_DATABASE}, {ENV_USER}."
        )
        raise SystemExit(1)

    try:
        dml_count = execute_sql_files(sql_files, db_config)
        print(f"  [done] {label} complete ({dml_count} DML statements).")
    except ImportError:
        print("  [ERROR] mysql-connector-python is not installed.")
        print("  Install: pip install mysql-connector-python")
        raise SystemExit(1)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"  [ERROR] {e}")
        raise SystemExit(1)

    print()
    print("─" * 60)
    print("  Phase 3 complete. Verify with:")
    print("    mysql -u <user> -p <db_name> < scripts/verify_seed_data.sql")
    print("=" * 60)


if __name__ == "__main__":
    main()
