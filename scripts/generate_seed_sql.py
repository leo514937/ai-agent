#!/usr/bin/env python3
"""
generate_seed_sql.py  —  Phase 2/4

Read normalized seed JSON (from Phase 1) and produce MySQL INSERT / rollback DELETE SQL.

Outputs:
  db/seed/local_life/seed_shops.sql      — INSERT INTO tb_shop
  db/seed/local_life/seed_vouchers.sql   — INSERT INTO tb_voucher
  db/seed/local_life/seed_all.sql        — Combined (shops + vouchers)
  db/seed/local_life/rollback.sql        — DELETE rollback statements
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = PROJECT_ROOT / "db" / "seed" / "local_life"

SQL_HEADER = """\
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

"""

SQL_FOOTER = """

SET FOREIGN_KEY_CHECKS = 1;
"""


# ── Escaping ──────────────────────────────────────────────────


def _sql_escape(value: str) -> str:
    """Escape a string value for MySQL single-quoted literal.
    Escapes: backslash, single quote, newline, tab, control chars.
    """
    value = value.replace("\\", "\\\\")
    value = value.replace("'", "''")
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    value = value.replace("\t", "\\t")
    return value


def _sql_literal(value: Any) -> str:
    """Convert a Python value to a MySQL SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Format without scientific notation, trim trailing zeros
        s = f"{value:.10f}".rstrip("0").rstrip(".")
        return s
    # string / timestamp
    escaped = _sql_escape(str(value))
    return f"'{escaped}'"


# ── SQL generation ────────────────────────────────────────────


def _on_duplicate_key_update_clause(columns: list[str]) -> str:
    """Build ON DUPLICATE KEY UPDATE clause for a given column list (excluding id)."""
    updates = [f"  `{c}`=VALUES(`{c}`)" for c in columns if c != "id"]
    return "ON DUPLICATE KEY UPDATE\n" + ",\n".join(updates) + ";\n"


def _generate_shop_sql(rows: list[dict], file: Path) -> int:
    """Write INSERT INTO tb_shop statements. Returns number of rows written."""
    columns = [
        "id", "name", "type_id", "images", "area", "address",
        "x", "y", "avg_price", "sold", "comments", "score",
        "open_hours", "create_time", "update_time",
    ]
    col_list = ", ".join(f"`{c}`" for c in columns)
    lines: list[str] = [
        SQL_HEADER,
        f"-- Seed data for tb_shop ({len(rows)} rows) — idempotent (ON DUPLICATE KEY UPDATE)\n",
        f"INSERT INTO `tb_shop` ({col_list}) VALUES\n",
    ]

    for i, row in enumerate(rows):
        vals = ", ".join(_sql_literal(row.get(c)) for c in columns)
        comma = "," if i < len(rows) - 1 else ""
        lines.append(f"  ({vals}){comma}\n")

    lines.append("")
    lines.append(_on_duplicate_key_update_clause(columns))
    lines.append(SQL_FOOTER)
    file.write_text("".join(lines), encoding="utf-8")
    return len(rows)


def _generate_voucher_sql(rows: list[dict], file: Path) -> int:
    """Write INSERT INTO tb_voucher statements. Returns number of rows written."""
    columns = [
        "id", "shop_id", "title", "sub_title", "rules",
        "pay_value", "actual_value", "type", "status",
        "create_time", "update_time",
    ]
    col_list = ", ".join(f"`{c}`" for c in columns)
    lines: list[str] = [
        SQL_HEADER,
        f"-- Seed data for tb_voucher ({len(rows)} rows) — idempotent (ON DUPLICATE KEY UPDATE)\n",
        f"INSERT INTO `tb_voucher` ({col_list}) VALUES\n",
    ]

    for i, row in enumerate(rows):
        vals = ", ".join(_sql_literal(row.get(c)) for c in columns)
        comma = "," if i < len(rows) - 1 else ""
        lines.append(f"  ({vals}){comma}\n")

    lines.append("")
    lines.append(_on_duplicate_key_update_clause(columns))
    lines.append(SQL_FOOTER)
    file.write_text("".join(lines), encoding="utf-8")
    return len(rows)


def _generate_rollback_sql(
    shop_rows: list[dict], voucher_rows: list[dict], file: Path
) -> None:
    """Write rollback DELETE statements.

    Deletes voucher rows FIRST (child table), then shop rows (parent table),
    using BETWEEN range for safe, idempotent rollback.
    """
    shop_start = min(r["id"] for r in shop_rows)
    shop_end = max(r["id"] for r in shop_rows)
    voucher_start = min(r["id"] for r in voucher_rows)
    voucher_end = max(r["id"] for r in voucher_rows)

    lines: list[str] = [
        SQL_HEADER,
        "-- Rollback seed data\n",
        f"-- Delete vouchers first (child table), then shops (parent table)\n",
        f"-- Voucher ID range: {voucher_start}–{voucher_end}\n",
        f"DELETE FROM `tb_voucher` WHERE `id` BETWEEN {voucher_start} AND {voucher_end};\n",
        "\n",
        f"-- Shop ID range: {shop_start}–{shop_end}\n",
        f"DELETE FROM `tb_shop` WHERE `id` BETWEEN {shop_start} AND {shop_end};\n",
        SQL_FOOTER,
    ]
    file.write_text("".join(lines), encoding="utf-8")


def _generate_combined_sql(
    seed_shops: Path, seed_vouchers: Path, file: Path
) -> None:
    """Concatenate shops SQL and vouchers SQL into seed_all.sql."""
    parts: list[str] = [
        "-- ============================================\n",
        "-- seed_all.sql  —  Combined seed data\n",
        "-- ============================================\n",
        SQL_HEADER,
    ]
    parts.append(f"\n-- >>> tb_shop ({seed_shops.name})\n")
    parts.append(seed_shops.read_text(encoding="utf-8"))
    parts.append(f"\n-- >>> tb_voucher ({seed_vouchers.name})\n")
    parts.append(seed_vouchers.read_text(encoding="utf-8"))

    file.write_text("".join(parts), encoding="utf-8")


# ── Main ───────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate seed SQL from normalized JSON (Phase 2)."
    )
    parser.add_argument(
        "--seed-dir",
        default=str(SEED_DIR),
        help=f"Seed data directory (default: {SEED_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Print summary but skip writing files.",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_false",
        dest="dry_run",
        help="Actually write output files.",
    )
    args = parser.parse_args()

    seed_dir = Path(args.seed_dir)

    print("=" * 60)
    print("  generate_seed_sql.py  —  Phase 2")
    print("=" * 60)
    print(f"  Seed dir  : {seed_dir}")
    print(f"  Dry-run   : {args.dry_run}")
    print()

    # ── Load normalized JSON ─────────────────────────────────
    shops_path = seed_dir / "normalized_shops.json"
    vouchers_path = seed_dir / "normalized_vouchers.json"

    if not shops_path.exists():
        print(f"  [ERROR] {shops_path} not found. Run Phase 1 first.")
        raise SystemExit(1)
    if not vouchers_path.exists():
        print(f"  [ERROR] {vouchers_path} not found. Run Phase 1 first.")
        raise SystemExit(1)

    with open(shops_path, "r", encoding="utf-8") as f:
        shop_rows: list[dict] = json.load(f)
    with open(vouchers_path, "r", encoding="utf-8") as f:
        voucher_rows: list[dict] = json.load(f)

    print(f"  Loaded {len(shop_rows)} shops, {len(voucher_rows)} vouchers\n")

    # ── Generate SQL ─────────────────────────────────────────
    seed_shops = seed_dir / "seed_shops.sql"
    seed_vouchers = seed_dir / "seed_vouchers.sql"
    rollback = seed_dir / "rollback.sql"
    seed_all = seed_dir / "seed_all.sql"

    if args.dry_run:
        print(f"  [dry-run] Would write:")
        print(f"    {seed_shops.relative_to(PROJECT_ROOT)} ({len(shop_rows)} rows)")
        print(f"    {seed_vouchers.relative_to(PROJECT_ROOT)} ({len(voucher_rows)} rows)")
        print(f"    {rollback.relative_to(PROJECT_ROOT)}")
        print(f"    {seed_all.relative_to(PROJECT_ROOT)} (combined)")
    else:
        print("  [write] Writing SQL files …")

        n_shop = _generate_shop_sql(shop_rows, seed_shops)
        print(f"    ✓ {seed_shops.relative_to(PROJECT_ROOT)} ({n_shop} rows)")

        n_voucher = _generate_voucher_sql(voucher_rows, seed_vouchers)
        print(f"    ✓ {seed_vouchers.relative_to(PROJECT_ROOT)} ({n_voucher} rows)")

        _generate_rollback_sql(shop_rows, voucher_rows, rollback)
        print(f"    ✓ {rollback.relative_to(PROJECT_ROOT)}")

        _generate_combined_sql(seed_shops, seed_vouchers, seed_all)
        print(f"    ✓ {seed_all.relative_to(PROJECT_ROOT)}")

    print()
    print("─" * 60)
    print(f"  Phase 2 complete. SQL files ready at:")
    print(f"    {seed_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
