#!/usr/bin/env python3
"""
normalize_mock_data_for_db.py  — Phase 1/4

Read Python mock JSON files (shops.json, coupons.json, distance_eta.json)
and produce MySQL-compatible normalized seed JSON with stable fixed-range IDs.

Outputs (Phase 1):
  db/seed/local_life/normalized_shops.json
  db/seed/local_life/normalized_vouchers.json
  db/seed/local_life/normalized_shop_id_mapping.json
  db/seed/local_life/normalized_coupon_id_mapping.json
  db/seed/local_life/normalized_seed_report.json

Not in scope (Phase 2+):
  - SQL generation
  - Database connection
  - Writing to MySQL
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MOCK_DATA_DIR = PROJECT_ROOT / "local_life_agent" / "mock_data"
SEED_DIR = PROJECT_ROOT / "db" / "seed" / "local_life"

# ── Constants ──────────────────────────────────────────────────

SHOP_ID_START = 900001
VOUCHER_ID_START = 910001

CATEGORY_TO_TYPE_ID: dict[str, int] = {
    "咖啡/茶饮": 1,
    "快餐": 1,
    "烘焙甜品": 1,
    "中式快餐": 1,
    "火锅": 1,
    "中餐": 1,
    "烧烤": 1,
    "日料": 1,
    "西餐": 1,
    "其他": 1,
}

DEFAULT_IMAGE = (
    "https://qcloud.dpfile.com/pc/default_shop_image.jpg"
)

FIXED_TIMESTAMP = "2026-01-01 00:00:00"

# ── Helpers ────────────────────────────────────────────────────


def _load_json(path: Path) -> list[dict] | dict:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _extract_area(address: str) -> str:
    """Extract district name (like '海淀区' / '朝阳区') from address.

    Strategy: prefer exactly 2 Chinese chars before '区'
    (e.g. 海淀区, 朝阳区, 西湖区), then 3 chars, then fallback to 'XX市'.
    """
    m = re.search(r"([\u4e00-\u9fff]{2}区)", address)
    if m:
        return m.group(1)
    m = re.search(r"([\u4e00-\u9fff]{3}区)", address)
    if m:
        return m.group(1)
    m = re.search(r"([\u4e00-\u9fff]{2,4}市)", address)
    return m.group(1) if m else ""


def _generate_stable_id_mapping(
    mock_ids: list[str], start: int
) -> dict[str, int]:
    """Deterministic mapping: sort mock IDs, assign sequential ints from start."""
    sorted_ids = sorted(set(mock_ids))
    return {mid: start + i for i, mid in enumerate(sorted_ids)}


# ── Shop normalization ─────────────────────────────────────────


def normalize_shops() -> tuple[list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    """
    Read shops.json and produce:
      - normalized_shop_rows (list of dicts for tb_shop)
      - shop_id_mapping (dict: mock_shop_id → fixed_int_id)
      - report_fragment (warnings / skipped)
    """
    raw: list[dict] = _load_json(MOCK_DATA_DIR / "shops.json")  # type: ignore[assignment]
    mock_ids = [s["shop_id"] for s in raw]
    mapping = _generate_stable_id_mapping(mock_ids, SHOP_ID_START)

    rows: list[dict[str, Any]] = []
    skipped_shop_fields: set[str] = set()
    warnings: list[str] = []
    manual_review: list[dict[str, Any]] = []

    for s in raw:
        sid = s["shop_id"]
        row: dict[str, Any] = {}

        # ID
        row["id"] = mapping[sid]

        # name
        row["name"] = s.get("shop_name", "").strip()
        if not row["name"]:
            warnings.append(f"Shop {sid}: shop_name is empty")
            manual_review.append({"mock_id": sid, "field": "shop_name", "reason": "empty name"})

        # type_id — all mapped to 1 (美食) for now
        cat = s.get("category", "")
        row["type_id"] = CATEGORY_TO_TYPE_ID.get(cat, 1)

        # images — default placeholder
        row["images"] = DEFAULT_IMAGE

        # area — try to extract from address
        addr = s.get("address", "")
        area = _extract_area(addr)
        row["area"] = area if area else None

        # address
        row["address"] = addr
        if not addr:
            warnings.append(f"Shop {sid}: address is empty")
            manual_review.append({"mock_id": sid, "field": "address", "reason": "empty address"})

        # x (经度) ← mock.lng
        lng = s.get("lng")
        if lng is not None:
            row["x"] = float(lng)
        else:
            warnings.append(f"Shop {sid}: lng is missing")
            row["x"] = 0.0

        # y (纬度) ← mock.lat
        lat = s.get("lat")
        if lat is not None:
            row["y"] = float(lat)
        else:
            warnings.append(f"Shop {sid}: lat is missing")
            row["y"] = 0.0

        # avg_price — round to int
        ap = s.get("avg_price")
        row["avg_price"] = round(ap) if ap is not None else None

        # sold / comments — default to 0 (NOT NULL in DB)
        row["sold"] = 0
        row["comments"] = 0

        # score = rating * 10 (int)
        rating = s.get("rating")
        if rating is not None:
            row["score"] = round(rating * 10)
        else:
            warnings.append(f"Shop {sid}: rating is missing, score set to 0")
            row["score"] = 0

        # open_hours ← mock.business_hours
        bh = s.get("business_hours", "")
        row["open_hours"] = bh if bh else None

        # timestamps
        row["create_time"] = FIXED_TIMESTAMP
        row["update_time"] = FIXED_TIMESTAMP

        rows.append(row)

        # Track skipped fields for first item only (all items share same schema)
        if len(rows) == 1:
            mock_keys = set(s.keys())
            used_keys = {
                "shop_id", "shop_name", "category", "sub_category", "address",
                "lat", "lng", "rating", "avg_price", "business_hours",
            }
            skipped_shop_fields = mock_keys - used_keys

    report_fragment: dict[str, Any] = {
        "shop_count": len(rows),
        "skipped_shop_fields": sorted(skipped_shop_fields - {"open_status", "phone", "tags", "alias", "aliases", "sub_category"}),
        "skipped_open_status": True,
        "skipped_phone": "phone" in skipped_shop_fields,
        "skipped_tags": "tags" in skipped_shop_fields,
        "skipped_alias": "alias" in skipped_shop_fields,
        "skipped_aliases": "aliases" in skipped_shop_fields,
        "skipped_sub_category": "sub_category" in skipped_shop_fields,
        "warnings": warnings,
        "manual_review": manual_review,
    }

    return rows, mapping, report_fragment


# ── Voucher normalization ─────────────────────────────────────


def _money_to_cents(value: float | int | None) -> int | None:
    if value is None:
        return None
    return round(float(value) * 100)


def normalize_vouchers(
    shop_mapping: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    """
    Read coupons.json and produce:
      - normalized_voucher_rows (list of dicts for tb_voucher)
      - coupon_id_mapping (dict: mock_coupon_id → fixed_int_id)
      - report_fragment (manual review items, skipped fields, etc.)
    """
    raw: list[dict] = _load_json(MOCK_DATA_DIR / "coupons.json")  # type: ignore[assignment]
    mock_ids = [c["coupon_id"] for c in raw]
    mapping = _generate_stable_id_mapping(mock_ids, VOUCHER_ID_START)

    rows: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    warnings: list[str] = []

    for c in raw:
        cid = c["coupon_id"]
        row: dict[str, Any] = {}

        # ID
        row["id"] = mapping[cid]

        # shop_id — look up via mapping
        mock_shop_id = c.get("shop_id", "")
        if mock_shop_id not in shop_mapping:
            manual_review.append({
                "mock_id": cid,
                "field": "shop_id",
                "reason": f"shop_id '{mock_shop_id}' cannot be mapped to any normalized shop",
            })
            warnings.append(f"Coupon {cid}: shop_id '{mock_shop_id}' not in shop mapping, skipping")
            continue
        row["shop_id"] = shop_mapping[mock_shop_id]

        # title
        row["title"] = c.get("title", "").strip()
        if not row["title"]:
            warnings.append(f"Coupon {cid}: title is empty")

        # sub_title ← description
        desc = c.get("description", "").strip()
        row["sub_title"] = desc if desc else None

        # rules — structured text with min_consume + validity
        rules_parts: list[str] = []
        if desc:
            rules_parts.append(desc)
        min_c = c.get("min_consume")
        if min_c is not None and min_c > 0:
            rules_parts.append(f"最低消费：{min_c}元")
        vf = c.get("valid_from", "")
        vu = c.get("valid_until", "")
        if vf and vu:
            rules_parts.append(f"有效期：{vf} 至 {vu}")
        row["rules"] = "。".join(rules_parts) if rules_parts else None

        # ── Money conversion ─────────────────────────────────
        discount_type = c.get("discount_type", "")
        discount_value = c.get("discount_value")
        min_consume = c.get("min_consume")

        needs_review = False
        review_reason: list[str] = []

        if min_consume is None or min_consume <= 0:
            needs_review = True
            review_reason.append(f"min_consume missing or <=0 ({min_consume})")

        if discount_value is None or discount_value <= 0:
            needs_review = True
            review_reason.append(f"discount_value missing or <=0 ({discount_value})")

        if needs_review:
            manual_review.append({
                "mock_id": cid,
                "field": "pay_value/actual_value",
                "reason": "; ".join(review_reason),
            })
            warnings.append(f"Coupon {cid}: money conversion needs manual review — {'; '.join(review_reason)}")
            continue

        min_cents = _money_to_cents(min_consume)  # type: ignore[arg-type]
        # actual_value = face value = min_consume (in cents)
        actual_value = min_cents

        if discount_type == "fixed":
            # e.g. discount_value=5 means "5元 off"
            pay_raw = float(min_consume) - float(discount_value)  # type: ignore[arg-type]
            pay_value = _money_to_cents(pay_raw)
        elif discount_type == "percentage":
            # e.g. discount_value=20 means "20% off" → user pays 80%
            pay_rate = (100.0 - float(discount_value)) / 100.0  # type: ignore[arg-type]
            pay_value = _money_to_cents(float(min_consume) * pay_rate)  # type: ignore[arg-type]
        else:
            pay_value = min_cents
            warnings.append(f"Coupon {cid}: unknown discount_type '{discount_type}', using full price")

        # Sanity checks
        if pay_value is None or actual_value is None:
            manual_review.append({
                "mock_id": cid,
                "field": "pay_value/actual_value",
                "reason": "pay_value or actual_value is None after conversion",
            })
            continue

        if pay_value <= 0:
            manual_review.append({
                "mock_id": cid,
                "field": "pay_value",
                "reason": f"pay_value={pay_value} <= 0",
            })
            continue

        if actual_value <= 0:
            manual_review.append({
                "mock_id": cid,
                "field": "actual_value",
                "reason": f"actual_value={actual_value} <= 0",
            })
            continue

        if pay_value >= actual_value:
            manual_review.append({
                "mock_id": cid,
                "field": "pay_value/actual_value",
                "reason": f"pay_value={pay_value} >= actual_value={actual_value} (no effective discount)",
            })
            continue

        row["pay_value"] = pay_value
        row["actual_value"] = actual_value

        # Fixed fields
        row["type"] = 0       # 普通券
        row["status"] = 1     # 上架
        row["create_time"] = FIXED_TIMESTAMP
        row["update_time"] = FIXED_TIMESTAMP

        rows.append(row)

    report_fragment: dict[str, Any] = {
        "voucher_count": len(rows),
        "skipped_voucher_fields": ["stock"],
        "skipped_stock_reason": "stock is only relevant for seckill vouchers (type=1); "
        "tb_seckill_voucher table not used in Phase 1 seed",
        "manual_review": manual_review,
        "warnings": warnings,
    }

    return rows, mapping, report_fragment


# ── Report compilation ────────────────────────────────────────


def compile_report(
    shop_rows: list[dict],
    voucher_rows: list[dict],
    shop_report: dict,
    voucher_report: dict,
    shop_mapping: dict[str, int],
    coupon_mapping: dict[str, int],
) -> dict[str, Any]:
    manual_all = list(shop_report.get("manual_review", [])) + list(voucher_report.get("manual_review", []))
    warnings_all = list(shop_report.get("warnings", [])) + list(voucher_report.get("warnings", []))

    return {
        "summary": {
            "shop_count": len(shop_rows),
            "voucher_count": len(voucher_rows),
            "manual_review_count": len(manual_all),
            "warning_count": len(warnings_all),
        },
        "id_ranges": {
            "shop_start": SHOP_ID_START,
            "shop_end": SHOP_ID_START + len(shop_rows) - 1,
            "voucher_start": VOUCHER_ID_START,
            "voucher_end": VOUCHER_ID_START + len(voucher_rows) - 1,
        },
        "skipped_fields": {
            "shop": {
                "open_status": "DB has no open_status column; should be dynamically determined from open_hours",
                "phone": "DB tb_shop has no phone column",
                "tags": "DB tb_shop has no tags column; could be introduced as a separate table",
                "alias": "DB tb_shop has no alias column",
                "aliases": "DB tb_shop has no aliases column",
                "sub_category": "DB uses type_id foreign key; sub_category is too granular",
            },
            "voucher": {
                "stock": "stock is only stored in tb_seckill_voucher for type=1 (seckill) vouchers; all mock vouchers are type=0 (普通券)",
            },
            "distance_eta": {
                "distance_km": "DB has no distance_eta table; distance should be dynamically calculated from shop coordinates (tb_shop.x, tb_shop.y) and user location",
                "eta_minutes": "same as above; ETA can be estimated from distance",
                "traffic_level": "same as above; not stored in DB",
                "_note": "distance_eta.json is NOT imported in any phase of this seed process",
            },
        },
        "category_mapping": dict(CATEGORY_TO_TYPE_ID),
        "open_status_handling": "skipped — DB has no open_status column; can be derived from open_hours + current time",
        "manual_review_items": manual_all,
        "warnings": warnings_all,
    }


# ── File I/O ───────────────────────────────────────────────────


def write_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {path.relative_to(PROJECT_ROOT)}")


# ── Main ───────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize Python mock data to MySQL-compatible seed JSON (Phase 1)."
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
    parser.add_argument(
        "--output-dir",
        default=str(SEED_DIR),
        help=f"Output directory (default: {SEED_DIR})",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    print("=" * 60)
    print("  normalize_mock_data_for_db.py  —  Phase 1")
    print("=" * 60)
    print(f"  Mock data dir : {MOCK_DATA_DIR}")
    print(f"  Output dir    : {output_dir}")
    print(f"  Dry-run       : {args.dry_run}")
    print()

    # ── Step 1: Shops ────────────────────────────────────────
    print("[1/3] Normalizing shops.json → normalized_shops.json")
    shop_rows, shop_mapping, shop_report = normalize_shops()
    print(f"       {len(shop_rows)} shops normalized")
    skipped = shop_report.get("skipped_shop_fields", [])
    if skipped:
        print(f"       skipped fields: {', '.join(str(s) for s in skipped)}")
    if shop_report.get("manual_review"):
        print(f"       manual review: {len(shop_report['manual_review'])} item(s)")
    print()

    # ── Step 2: Vouchers ────────────────────────────────────
    print("[2/3] Normalizing coupons.json → normalized_vouchers.json")
    voucher_rows, voucher_mapping, voucher_report = normalize_vouchers(shop_mapping)
    print(f"       {len(voucher_rows)} vouchers normalized")
    if voucher_report.get("manual_review"):
        print(f"       manual review: {len(voucher_report['manual_review'])} item(s)")
    print()

    # ── Step 3: Report ───────────────────────────────────────
    print("[3/3] Compiling seed report")
    report = compile_report(
        shop_rows, voucher_rows,
        shop_report, voucher_report,
        shop_mapping, voucher_mapping,
    )
    print(f"       shops: {report['summary']['shop_count']}, "
          f"vouchers: {report['summary']['voucher_count']}, "
          f"manual review: {report['summary']['manual_review_count']}, "
          f"warnings: {report['summary']['warning_count']}")
    print()

    # ── Write outputs (unless dry-run) ───────────────────────
    if args.dry_run:
        print("[dry-run] Skipping file writes. Pass --no-dry-run to write.")
    else:
        print("[write] Writing output files …")
        write_json(shop_rows, output_dir / "normalized_shops.json")
        write_json(shop_mapping, output_dir / "normalized_shop_id_mapping.json")
        write_json(voucher_rows, output_dir / "normalized_vouchers.json")
        write_json(voucher_mapping, output_dir / "normalized_coupon_id_mapping.json")
        write_json(report, output_dir / "normalized_seed_report.json")
        print()

    # ── Summary ──────────────────────────────────────────────
    print("─" * 60)
    print("  Shop ID mapping (sample):")
    for mid in list(shop_mapping.keys())[:3]:
        print(f"    {mid} → {shop_mapping[mid]}")
    if len(shop_mapping) > 3:
        print(f"    … ({len(shop_mapping) - 3} more)")

    print("  Coupon ID mapping (sample):")
    for mid in list(voucher_mapping.keys())[:3]:
        print(f"    {mid} → {voucher_mapping[mid]}")
    if len(voucher_mapping) > 3:
        print(f"    … ({len(voucher_mapping) - 3} more)")

    print()
    print("  Skipped fields:")
    for category, fields in report["skipped_fields"].items():
        for field, reason in fields.items():
            if field.startswith("_"):
                continue
            print(f"    [{category}] {field}: {reason[:80]}…" if len(reason) > 80 else f"    [{category}] {field}: {reason}")

    if report["manual_review_items"]:
        print()
        print("  Manual review items:")
        for item in report["manual_review_items"]:
            print(f"    {item['mock_id']}: {item.get('field', '?')} — {item.get('reason', '')}")

    print()
    print("─" * 60)
    print("  Phase 1 complete. Run tests:")
    print("    python -m pytest local_life_agent/tests/test_mock_data_normalization.py -q")
    print("=" * 60)


if __name__ == "__main__":
    main()
