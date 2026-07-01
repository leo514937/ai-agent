"""MySQL DB client — read-only connection wrapper for tool queries.

All queries open a fresh connection per call to avoid sharing a single
mysql.connector connection across worker threads.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from .. import config

_logger = logging.getLogger(__name__)

# ── Connection management ─────────────────────────────────────────


def _ensure_connection() -> Any:
    """Create a fresh DB connection for the current query."""
    import mysql.connector

    return mysql.connector.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        database=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        charset="utf8mb4",
        autocommit=True,
    )


@contextmanager
def _connection_cursor() -> Iterator[Any]:
    conn = _ensure_connection()
    try:
        with conn.cursor(dictionary=True, buffered=True) as cur:
            yield cur
    finally:
        try:
            conn.close()
        except Exception:
            pass


def close() -> None:
    """Kept for compatibility; per-query connections close automatically."""
    return None


# ── Row helpers ───────────────────────────────────────────────────


def _row_to_shop(row: dict[str, Any]) -> dict[str, Any]:
    """Map a tb_shop row (as dict) to the tool output format."""
    return {
        "shop_id": str(row["id"]),
        "shop_name": str(row["name"]),
        "category": str(row.get("type_name", "") or ""),
        "address": str(row.get("address", "") or ""),
        "lat": float(row["y"]) if row.get("y") is not None else 0.0,
        "lng": float(row["x"]) if row.get("x") is not None else 0.0,
        "avg_price": float(row["avg_price"]) if row.get("avg_price") is not None else 0.0,
        "rating": float(row["score"] or 0) / 10.0 if row.get("score") is not None else 0.0,
        "business_hours": str(row.get("open_hours", "") or ""),
        "open_status": "open",  # simplified — see check_open_status for logic
        "images": str(row.get("images", "") or ""),
        "area": str(row.get("area", "") or ""),
        "sold": int(row.get("sold", 0) or 0),
        "comments": int(row.get("comments", 0) or 0),
        # Fields not in DB schema: keep empty for backward compat
        "alias": "",
        "sub_category": "",
        "tags": [],
    }


def _row_to_matched_shop(row: dict[str, Any]) -> dict[str, Any]:
    """Like _row_to_shop but with minimal fields for candidate lists."""
    return {
        "shop_id": str(row["id"]),
        "shop_name": str(row["name"]),
        "address": str(row.get("address", "") or ""),
        "category": str(row.get("type_name", "") or ""),
        "lat": float(row["y"]) if row.get("y") is not None else 0.0,
        "lng": float(row["x"]) if row.get("x") is not None else 0.0,
        "avg_price": float(row["avg_price"]) if row.get("avg_price") is not None else 0.0,
        "rating": float(row["score"] or 0) / 10.0 if row.get("score") is not None else 0.0,
        "tags": [],
    }


def _row_to_coupon(row: dict[str, Any]) -> dict[str, Any]:
    """Map a tb_voucher row to the coupon output format."""
    raw_status = row.get("status")
    status = "available" if str(raw_status) in {"1", "available", "AVAILABLE"} or raw_status == 1 else "unavailable"
    return {
        "coupon_id": str(row["id"]),
        "shop_id": str(row["shop_id"]),
        "title": str(row.get("title", "") or ""),
        "description": str(row.get("rules", "") or row.get("sub_title", "") or ""),
        "pay_value": row.get("pay_value", 0),
        "actual_value": row.get("actual_value", 0),
        "status": status,
    }


# ── Query helpers ─────────────────────────────────────────────────


def query_all_shops() -> list[dict[str, Any]]:
    """Return all shops with their type name.

    SELECT from tb_shop LEFT JOIN tb_shop_type.

    Returns:
        List of shop dicts in tool output format.
    """
    sql = """
        SELECT
            s.id, s.name, s.type_id, s.images, s.area, s.address,
            s.x, s.y, s.avg_price, s.sold, s.comments, s.score,
            s.open_hours,
            t.name AS type_name
        FROM tb_shop s
        LEFT JOIN tb_shop_type t ON t.id = s.type_id
        ORDER BY s.id
    """
    with _connection_cursor() as cur:
        cur.execute(sql)
        return [_row_to_shop(row) for row in cur.fetchall()]


def query_shop_by_id(shop_id: str) -> dict[str, Any] | None:
    """Query a single shop by its numeric ID.

    Args:
        shop_id: Numeric shop ID as string (e.g. "1", "900001").

    Returns:
        Shop dict or None.
    """
    sql = """
        SELECT
            s.id, s.name, s.type_id, s.images, s.area, s.address,
            s.x, s.y, s.avg_price, s.sold, s.comments, s.score,
            s.open_hours,
            t.name AS type_name
        FROM tb_shop s
        LEFT JOIN tb_shop_type t ON t.id = s.type_id
        WHERE s.id = %s
    """
    try:
        sid = int(shop_id)
    except (ValueError, TypeError):
        return None
    with _connection_cursor() as cur:
        cur.execute(sql, (sid,))
        row = cur.fetchone()
        return _row_to_shop(row) if row else None


def query_shop_by_name(name: str) -> list[dict[str, Any]]:
    """Query shops whose name matches *exactly* or contains the query.

    Args:
        name: Shop name or partial keyword.

    Returns:
        List of matching shop dicts.
    """
    sql = """
        SELECT
            s.id, s.name, s.type_id, s.images, s.area, s.address,
            s.x, s.y, s.avg_price, s.sold, s.comments, s.score,
            s.open_hours,
            t.name AS type_name
        FROM tb_shop s
        LEFT JOIN tb_shop_type t ON t.id = s.type_id
        WHERE s.name LIKE %s
           OR s.name = %s
        ORDER BY s.id
    """
    pattern = f"%{name}%"
    with _connection_cursor() as cur:
        cur.execute(sql, (pattern, name))
        return [_row_to_shop(row) for row in cur.fetchall()]


def query_shops_by_keyword(
    keyword: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Search shops by keyword across name, address, and type name.

    Args:
        keyword: Search keyword.
        limit: Max results.

    Returns:
        List of matched shop dicts.
    """
    sql = """
        SELECT
            s.id, s.name, s.type_id, s.images, s.area, s.address,
            s.x, s.y, s.avg_price, s.sold, s.comments, s.score,
            s.open_hours,
            t.name AS type_name
        FROM tb_shop s
        LEFT JOIN tb_shop_type t ON t.id = s.type_id
        WHERE s.name LIKE %s
           OR s.address LIKE %s
           OR t.name LIKE %s
        ORDER BY s.score DESC, s.sold DESC
    """
    pattern = f"%{keyword}%"
    with _connection_cursor() as cur:
        cur.execute(sql, (pattern, pattern, pattern))
        rows = cur.fetchall()
    if limit is not None and limit > 0:
        rows = rows[:limit]
    return [_row_to_matched_shop(row) for row in rows]


def query_coupons_by_shop_id(shop_id: str) -> list[dict[str, Any]]:
    """Query vouchers for a given shop.

    Args:
        shop_id: Numeric shop ID as string.

    Returns:
        List of coupon dicts. Empty list if shop has no vouchers
        or shop does not exist.
    """
    try:
        sid = int(shop_id)
    except (ValueError, TypeError):
        return []
    sql = """
        SELECT id, shop_id, title, sub_title, rules,
               pay_value, actual_value, type, status
        FROM tb_voucher
        WHERE shop_id = %s AND status = 1
    """
    with _connection_cursor() as cur:
        cur.execute(sql, (sid,))
        return [_row_to_coupon(row) for row in cur.fetchall()]


def query_all_type_names() -> dict[int, str]:
    """Return a mapping of type_id → type name."""
    with _connection_cursor() as cur:
        cur.execute("SELECT id, name FROM tb_shop_type")
        return {row["id"]: str(row["name"]) for row in cur.fetchall()}
