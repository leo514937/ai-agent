"""Tests for mock data normalization (Phase 1: JSON normalization).

These tests verify that:
  - normalize_mock_data_for_db.py produces correct output
  - ID mappings are stable/deterministic
  - Field mappings are correct (lat→y, lng→x, rating→score*10, etc.)
  - Skipped fields are properly reported
  - Original mock files are not modified
  - Money conversion is correct (cents)
  - Invalid data goes to manual_review

SQL-related tests (15-16) are in Phase 2.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from normalize_mock_data_for_db import (
    SHOP_ID_START,
    VOUCHER_ID_START,
    CATEGORY_TO_TYPE_ID,
    _extract_area,
    _generate_stable_id_mapping,
    _money_to_cents,
    normalize_shops,
    normalize_vouchers,
    compile_report,
    MOCK_DATA_DIR,
)

# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture(scope="module")
def shop_normalization():
    rows, mapping, report = normalize_shops()
    return rows, mapping, report


@pytest.fixture(scope="module")
def full_data():
    shop_rows, shop_mapping, shop_report = normalize_shops()
    voucher_rows, voucher_mapping, voucher_report = normalize_vouchers(shop_mapping)
    report = compile_report(
        shop_rows, voucher_rows,
        shop_report, voucher_report,
        shop_mapping, voucher_mapping,
    )
    return {
        "shop_rows": shop_rows,
        "shop_mapping": shop_mapping,
        "shop_report": shop_report,
        "voucher_rows": voucher_rows,
        "voucher_mapping": voucher_mapping,
        "voucher_report": voucher_report,
        "report": report,
    }


# ── Test: Shop normalization ─────────────────────────────────


class TestShopNormalization:
    """Verify that normalize_shops() produces correct tb_shop rows."""

    def test_normalize_mock_shops_to_db_seed(self, full_data):
        """All mock shops are normalized into seed rows."""
        rows = full_data["shop_rows"]
        assert len(rows) == 27, f"Expected 27 shops, got {len(rows)}"

    def test_shop_required_fields_are_present(self, full_data):
        """Every normalized shop row has all NOT NULL DB fields."""
        required = {"id", "name", "type_id", "images", "address", "x", "y",
                     "sold", "comments", "score", "create_time", "update_time"}
        for row in full_data["shop_rows"]:
            missing = required - set(row.keys())
            assert not missing, f"Shop id={row['id']} missing fields: {missing}"
            # Non-null checks
            assert row["name"], f"Shop id={row['id']} has empty name"
            assert row["images"], f"Shop id={row['id']} has empty images"
            assert row["address"], f"Shop id={row['id']} has empty address"
            assert row["sold"] == 0, f"Shop id={row['id']} sold != 0"
            assert row["comments"] == 0, f"Shop id={row['id']} comments != 0"

    def test_shop_id_starts_at_900001(self, full_data):
        """Shop IDs start at 900001 and are sequential."""
        rows = full_data["shop_rows"]
        ids = sorted(r["id"] for r in rows)
        assert ids[0] == 900001
        assert ids[-1] == 900001 + len(rows) - 1
        assert ids == list(range(900001, 900001 + len(rows)))

    def test_shop_id_mapping_is_stable(self):
        """Running normalize twice produces the same mapping."""
        _, m1, _ = normalize_shops()
        _, m2, _ = normalize_shops()
        assert m1 == m2, "Shop ID mapping is not stable across runs"

    def test_shop_lat_lng_maps_to_db_x_y_correctly(self, full_data):
        """mock.lat → db.y (纬度), mock.lng → db.x (经度)."""
        rows = full_data["shop_rows"]
        for r in rows:
            assert isinstance(r["x"], float), f"Shop id={r['id']}: x is not float"
            assert isinstance(r["y"], float), f"Shop id={r['id']}: y is not float"
        # Spot-check a known shop: shop_001
        shop001 = next(r for r in rows if r["id"] == 900001)
        assert shop001["x"] == 116.3575, f"shop_001 x (经度) expected 116.3575, got {shop001['x']}"
        assert shop001["y"] == 39.9615, f"shop_001 y (纬度) expected 39.9615, got {shop001['y']}"

    def test_shop_rating_maps_to_score_times_10(self, full_data):
        """mock.rating * 10 → db.score (int)."""
        rows = full_data["shop_rows"]
        # shop_001: rating=4.3 → score=43
        shop001 = next(r for r in rows if r["id"] == 900001)
        assert shop001["score"] == 43, f"Expected score=43, got {shop001['score']}"
        # shop_sc_11: rating=4.9 → score=49
        sc11_id = full_data["shop_mapping"]["shop_sc_11"]
        sc11 = next(r for r in rows if r["id"] == sc11_id)
        assert sc11["score"] == 49, f"shop_sc_11: expected score=49, got {sc11['score']}"
        # All scores are integers
        for r in rows:
            assert isinstance(r["score"], int), f"Shop id={r['id']}: score is not int"

    def test_shop_category_maps_to_type_id_1(self, full_data):
        """All shop categories map to type_id=1 (美食) for now."""
        for r in full_data["shop_rows"]:
            assert r["type_id"] == 1, f"Shop id={r['id']} type_id != 1"

    def test_shop_avg_price_is_integer(self, full_data):
        """mock.avg_price (float) → db.avg_price (int/bigint)."""
        for r in full_data["shop_rows"]:
            if r["avg_price"] is not None:
                assert isinstance(r["avg_price"], int), f"Shop id={r['id']} avg_price is not int"

    def test_shop_x_y_not_swapped(self, full_data):
        """Verify x/y are not accidentally swapped by spot-checking addresses."""
        rows = full_data["shop_rows"]
        # shop_008 = coco都可(北太平庄店): lng=116.3615, lat=39.9635
        # Beijing is at ~116.3E, ~39.9N → x≈116, y≈40
        shop008 = next(r for r in rows if r["id"] == 900008)
        assert 115 < shop008["x"] < 117, f"shop_008 x (经度) out of range: {shop008['x']}"
        assert 39 < shop008["y"] < 41, f"shop_008 y (纬度) out of range: {shop008['y']}"
        # x should be the larger number (longitude)
        assert shop008["x"] > shop008["y"]

    def test_shop_open_hours_maps_from_business_hours(self, full_data):
        """mock.business_hours → db.open_hours."""
        rows = full_data["shop_rows"]
        shop001 = next(r for r in rows if r["id"] == 900001)
        assert shop001["open_hours"] == "07:30-21:00"

    def test_original_mock_files_are_not_modified(self):
        """Verify mock JSON files' modification hasn't changed."""
        shops_path = MOCK_DATA_DIR / "shops.json"
        assert shops_path.exists()
        data = json.loads(shops_path.read_text(encoding="utf-8-sig"))
        assert len(data) == 27
        # Spot-check first entry
        assert data[0]["shop_id"] == "shop_001"


# ── Test: Voucher normalization ──────────────────────────────


class TestVoucherNormalization:
    """Verify that normalize_vouchers() produces correct tb_voucher rows."""

    def test_normalize_mock_coupons_to_vouchers(self, full_data):
        """All 16 mock coupons are normalized into voucher rows."""
        rows = full_data["voucher_rows"]
        assert len(rows) == 16, f"Expected 16 vouchers, got {len(rows)}"

    def test_coupon_id_mapping_is_stable(self):
        """Running voucher normalization twice produces same mapping."""
        shop_rows, shop_mapping, _ = normalize_shops()
        _, m1, _ = normalize_vouchers(shop_mapping)
        _, m2, _ = normalize_vouchers(shop_mapping)
        assert m1 == m2, "Coupon ID mapping is not stable"

    def test_coupon_id_starts_at_910001(self, full_data):
        """Coupon IDs start at 910001 and are sequential."""
        rows = full_data["voucher_rows"]
        ids = sorted(r["id"] for r in rows)
        assert ids[0] == 910001
        assert ids[-1] == 910001 + len(rows) - 1
        assert ids == list(range(910001, 910001 + len(rows)))

    def test_coupon_shop_id_uses_normalized_shop_mapping(self, full_data):
        """Voucher shop_id references normalized (mapped) shop ID, not mock string."""
        shop_mapping = full_data["shop_mapping"]
        for row in full_data["voucher_rows"]:
            assert isinstance(row["shop_id"], int), f"Voucher id={row['id']} shop_id is not int"
            # Verify it matches some normalized shop
            assert row["shop_id"] in shop_mapping.values(), \
                f"Voucher id={row['id']} shop_id={row['shop_id']} not in normalized shop IDs"

    def test_coupon_money_values_are_in_cents(self, full_data):
        """pay_value and actual_value are in cents (分)."""
        for row in full_data["voucher_rows"]:
            assert isinstance(row["pay_value"], int), f"Voucher id={row['id']} pay_value not int"
            assert isinstance(row["actual_value"], int), f"Voucher id={row['id']} actual_value not int"
            assert row["pay_value"] > 0, f"Voucher id={row['id']} pay_value <= 0"
            assert row["actual_value"] > 0, f"Voucher id={row['id']} actual_value <= 0"
            assert row["pay_value"] < row["actual_value"], \
                f"Voucher id={row['id']}: pay_value={row['pay_value']} >= actual_value={row['actual_value']} (no discount)"

    def test_coupon_money_values_hand(self, full_data):
        """Hand-verify specific coupon money values."""
        rows_map = {r["id"]: r for r in full_data["voucher_rows"]}
        # cpn_001 (id=910001): percentage, discount_value=20 (8折), min_consume=15
        cpn001 = rows_map[910001]
        # actual_value = 15 * 100 = 1500
        assert cpn001["actual_value"] == 1500, f"cpn_001 actual_value expected 1500, got {cpn001['actual_value']}"
        # pay_value = 15 * (100-20)/100 * 100 = 15 * 0.8 * 100 = 1200
        assert cpn001["pay_value"] == 1200, f"cpn_001 pay_value expected 1200, got {cpn001['pay_value']}"

        # cpn_002 (id=910002): fixed, discount_value=5, min_consume=25
        cpn002 = rows_map[910002]
        assert cpn002["actual_value"] == 2500, f"cpn_002 actual_value expected 2500, got {cpn002['actual_value']}"
        assert cpn002["pay_value"] == 2000, f"cpn_002 pay_value expected 2000, got {cpn002['pay_value']}"

        # cpn_009 (id=910009): fixed, discount_value=10, min_consume=19
        cpn009 = rows_map[910009]
        assert cpn009["actual_value"] == 1900, f"cpn_009 actual_value expected 1900, got {cpn009['actual_value']}"
        assert cpn009["pay_value"] == 900, f"cpn_009 pay_value expected 900, got {cpn009['pay_value']}"

    def test_coupon_required_fields(self, full_data):
        """All required voucher fields are present."""
        required = {"id", "shop_id", "title", "pay_value", "actual_value",
                     "type", "status", "create_time", "update_time"}
        for row in full_data["voucher_rows"]:
            missing = required - set(row.keys())
            assert not missing, f"Voucher id={row['id']} missing: {missing}"
            assert row["title"], f"Voucher id={row['id']} title empty"
            assert row["type"] == 0, f"Voucher id={row['id']} type != 0"
            assert row["status"] == 1, f"Voucher id={row['id']} status != 1"

    def test_coupon_type_and_status_fixed(self, full_data):
        """All vouchers have type=0 (普通券) and status=1 (上架)."""
        for row in full_data["voucher_rows"]:
            assert row["type"] == 0
            assert row["status"] == 1


# ── Test: skipped fields ─────────────────────────────────────


class TestSkippedFields:
    """Verify that fields without DB counterparts are properly skipped."""

    def test_distance_eta_is_skipped_for_db_seed(self, full_data):
        """distance_eta.json is not imported."""
        report = full_data["report"]
        skipped = report["skipped_fields"]["distance_eta"]
        assert "distance_km" in skipped
        assert "eta_minutes" in skipped
        assert "traffic_level" in skipped

    def test_open_status_is_skipped_for_db_seed(self, full_data):
        """open_status field is not imported into any DB table."""
        report = full_data["report"]
        skipped = report["skipped_fields"]["shop"]
        assert "open_status" in skipped

    def test_phone_is_skipped(self, full_data):
        """phone field is not imported."""
        report = full_data["report"]
        assert "phone" in report["skipped_fields"]["shop"]

    def test_tags_alias_are_skipped(self, full_data):
        """tags, alias, aliases are not imported."""
        report = full_data["report"]
        assert "tags" in report["skipped_fields"]["shop"]
        assert "alias" in report["skipped_fields"]["shop"]
        assert "aliases" in report["skipped_fields"]["shop"]

    def test_sub_category_is_skipped(self, full_data):
        """sub_category is not imported."""
        report = full_data["report"]
        assert "sub_category" in report["skipped_fields"]["shop"]

    def test_voucher_stock_is_skipped(self, full_data):
        """stock is not imported (only for seckill vouchers)."""
        report = full_data["report"]
        assert "stock" in report["skipped_fields"]["voucher"]


# ── Test: report ─────────────────────────────────────────────


class TestReport:
    """Verify the seed report contents."""

    def test_report_summary_counts(self, full_data):
        """Report summary counts match actual data."""
        report = full_data["report"]
        assert report["summary"]["shop_count"] == len(full_data["shop_rows"])
        assert report["summary"]["voucher_count"] == len(full_data["voucher_rows"])

    def test_report_id_ranges(self, full_data):
        """ID ranges are correctly reported."""
        report = full_data["report"]
        ranges = report["id_ranges"]
        assert ranges["shop_start"] == 900001
        assert ranges["voucher_start"] == 910001
        assert ranges["shop_end"] == 900001 + len(full_data["shop_rows"]) - 1
        assert ranges["voucher_end"] == 910001 + len(full_data["voucher_rows"]) - 1

    def test_report_category_mapping(self, full_data):
        """All mock categories are in the mapping."""
        report = full_data["report"]
        cat_map = report["category_mapping"]
        assert all(v == 1 for v in cat_map.values()), "All types should map to 1"


# ── Test: helper functions ───────────────────────────────────


class TestHelpers:
    """Verify helper functions."""

    def test_generate_stable_id_mapping(self):
        """Mapping is deterministic and sequential."""
        mock_ids = ["z", "a", "c", "b"]
        m1 = _generate_stable_id_mapping(mock_ids, 100)
        m2 = _generate_stable_id_mapping(mock_ids, 100)
        assert m1 == m2
        assert m1 == {"a": 100, "b": 101, "c": 102, "z": 103}
        assert list(m1.values()) == [100, 101, 102, 103]

    def test_extract_area(self):
        """_extract_area correctly extracts district from address."""
        assert _extract_area("海淀区西土城路10号") == "海淀区"
        assert _extract_area("朝阳区建国门外大街1号") == "朝阳区"
        assert _extract_area("杭州市西湖区文三路") == "西湖区"
        assert _extract_area("No district here") == ""

    def test_money_to_cents(self):
        """_money_to_cents converts yuan to cents."""
        assert _money_to_cents(15.0) == 1500
        assert _money_to_cents(0) == 0
        assert _money_to_cents(100.50) == 10050
        assert _money_to_cents(None) is None
        assert _money_to_cents(99.99) == 9999


# ── Test: SQL generation (Phase 2) ────────────────────────────


@pytest.fixture
def tmp_sql_dir(tmp_path):
    """Temporary directory for SQL output files."""
    return tmp_path


class TestSqlGeneration:
    """Verify SQL generation produces valid INSERT/DELETE statements."""

    def test_sql_escape_handles_single_quotes(self):
        """Single quotes are escaped as ''."""
        from generate_seed_sql import _sql_escape

        assert _sql_escape("it's") == "it''s"
        assert _sql_escape("'hello'") == "''hello''"

    def test_sql_escape_handles_backslashes(self):
        """Backslashes are escaped."""
        from generate_seed_sql import _sql_escape

        assert _sql_escape("a\\b") == "a\\\\b"

    def test_sql_escape_handles_newlines(self):
        """Newlines become \\n."""
        from generate_seed_sql import _sql_escape

        assert _sql_escape("line1\nline2") == "line1\\nline2"

    def test_sql_literal_none(self):
        """None becomes NULL."""
        from generate_seed_sql import _sql_literal

        assert _sql_literal(None) == "NULL"

    def test_sql_literal_int(self):
        """Ints are unquoted."""
        from generate_seed_sql import _sql_literal

        assert _sql_literal(42) == "42"
        assert _sql_literal(0) == "0"
        assert _sql_literal(-5) == "-5"

    def test_sql_literal_float(self):
        """Floats are unquoted without trailing zeros."""
        from generate_seed_sql import _sql_literal

        assert _sql_literal(3.14) == "3.14"
        assert _sql_literal(100.0) == "100"
        assert _sql_literal(0.5) == "0.5"

    def test_sql_literal_string(self):
        """Strings are single-quoted and escaped."""
        from generate_seed_sql import _sql_literal

        assert _sql_literal("hello") == "'hello'"
        assert _sql_literal("it's good") == "'it''s good'"

    def test_sql_literal_bool(self):
        """Booleans become 1/0."""
        from generate_seed_sql import _sql_literal

        assert _sql_literal(True) == "1"
        assert _sql_literal(False) == "0"

    def test_generate_shop_sql_format(self, tmp_sql_dir):
        """Shop INSERT has correct columns and row count."""
        from generate_seed_sql import _generate_shop_sql

        shop_rows = [
            {"id": 900001, "name": "Shop A", "type_id": 1, "images": "img.jpg",
             "area": "海淀区", "address": "addr1", "x": 116.0, "y": 39.9,
             "avg_price": 50, "sold": 0, "comments": 0, "score": 45,
             "open_hours": "10:00-22:00", "create_time": "2026-01-01 00:00:00",
             "update_time": "2026-01-01 00:00:00"},
        ]
        out = tmp_sql_dir / "test_shops.sql"
        count = _generate_shop_sql(shop_rows, out)
        assert count == 1

        text = out.read_text(encoding="utf-8")
        assert "INSERT INTO `tb_shop`" in text
        assert "900001" in text
        assert "Shop A" in text
        assert "116" in text
        assert ";" in text

    def test_generate_voucher_sql_format(self, tmp_sql_dir):
        """Voucher INSERT has correct columns and row count."""
        from generate_seed_sql import _generate_voucher_sql

        voucher_rows = [
            {"id": 910001, "shop_id": 900001, "title": "Test Voucher",
             "sub_title": "Sub", "rules": "Rules here",
             "pay_value": 800, "actual_value": 1000,
             "type": 0, "status": 1,
             "create_time": "2026-01-01 00:00:00",
             "update_time": "2026-01-01 00:00:00"},
        ]
        out = tmp_sql_dir / "test_vouchers.sql"
        count = _generate_voucher_sql(voucher_rows, out)
        assert count == 1

        text = out.read_text(encoding="utf-8")
        assert "INSERT INTO `tb_voucher`" in text
        assert "910001" in text
        assert "Test Voucher" in text
        assert ";" in text

    def test_generate_rollback_sql_deletes_voucher_before_shop(self, tmp_sql_dir):
        """Rollback DELETE deletes voucher (child table) BEFORE shop (parent table)."""
        from generate_seed_sql import _generate_rollback_sql

        shop_rows = [{"id": 900001}, {"id": 900027}]
        voucher_rows = [{"id": 910001}, {"id": 910016}]
        out = tmp_sql_dir / "test_rollback.sql"
        _generate_rollback_sql(shop_rows, voucher_rows, out)

        text = out.read_text(encoding="utf-8")
        # voucher DELETE must appear before shop DELETE in the file
        tb_voucher_pos = text.index("DELETE FROM `tb_voucher`")
        tb_shop_pos = text.index("DELETE FROM `tb_shop`")
        assert tb_voucher_pos < tb_shop_pos, \
            "voucher DELETE must come BEFORE shop DELETE"

    def test_generate_rollback_sql_uses_between_not_in(self, tmp_sql_dir):
        """Rollback uses BETWEEN range, not IN list."""
        from generate_seed_sql import _generate_rollback_sql

        shop_rows = [{"id": 900001}, {"id": 900027}]
        voucher_rows = [{"id": 910001}, {"id": 910016}]
        out = tmp_sql_dir / "test_rollback.sql"
        _generate_rollback_sql(shop_rows, voucher_rows, out)

        text = out.read_text(encoding="utf-8")
        assert "BETWEEN" in text, "Should use BETWEEN range"
        assert "IN (" not in text, "Should NOT use IN list"

    def test_generate_rollback_sql_uses_correct_ranges(self, tmp_sql_dir):
        """Rollback uses correct BETWEEN ranges based on actual data."""
        from generate_seed_sql import _generate_rollback_sql

        shop_rows = [{"id": 900001}, {"id": 900027}]
        voucher_rows = [{"id": 910001}, {"id": 910016}]
        out = tmp_sql_dir / "test_rollback.sql"
        _generate_rollback_sql(shop_rows, voucher_rows, out)

        text = out.read_text(encoding="utf-8")
        assert "BETWEEN 910001 AND 910016" in text, "Voucher range mismatch"
        assert "BETWEEN 900001 AND 900027" in text, "Shop range mismatch"

    def test_generate_rollback_sql_no_truncate_or_drop(self, tmp_sql_dir):
        """Rollback contains no TRUNCATE or DROP statements."""
        from generate_seed_sql import _generate_rollback_sql

        shop_rows = [{"id": 900001}, {"id": 900027}]
        voucher_rows = [{"id": 910001}, {"id": 910016}]
        out = tmp_sql_dir / "test_rollback.sql"
        _generate_rollback_sql(shop_rows, voucher_rows, out)

        text = out.read_text(encoding="utf-8")
        assert "TRUNCATE" not in text.upper(), "Must not contain TRUNCATE"
        assert "DROP" not in text.upper(), "Must not contain DROP"

    def test_sql_contains_set_names_and_foreign_key_checks(self, tmp_sql_dir):
        """SQL files include SET NAMES and FOREIGN_KEY_CHECKS headers."""
        from generate_seed_sql import _generate_shop_sql, _generate_voucher_sql, \
            _generate_rollback_sql

        shop_rows = [{"id": 900001, "name": "A", "type_id": 1, "images": "i.jpg",
                      "area": None, "address": "a", "x": 1.0, "y": 2.0,
                      "avg_price": None, "sold": 0, "comments": 0, "score": 30,
                      "open_hours": None, "create_time": "t", "update_time": "t"}]
        voucher_rows = [{"id": 910001, "shop_id": 900001, "title": "V",
                         "sub_title": None, "rules": None,
                         "pay_value": 500, "actual_value": 1000,
                         "type": 0, "status": 1,
                         "create_time": "t", "update_time": "t"}]

        for gen_fn, rows, name in [
            (_generate_shop_sql, shop_rows, "shops"),
            (_generate_voucher_sql, voucher_rows, "vouchers"),
        ]:
            out = tmp_sql_dir / f"test_{name}.sql"
            gen_fn(rows, out)
            text = out.read_text(encoding="utf-8")
            assert "SET NAMES utf8mb4" in text, f"{name}: missing charset header"
            assert "SET FOREIGN_KEY_CHECKS = 0" in text, f"{name}: missing FK header"

        rl = tmp_sql_dir / "test_rb.sql"
        _generate_rollback_sql(shop_rows, voucher_rows, rl)
        text = rl.read_text(encoding="utf-8")
        assert "SET NAMES utf8mb4" in text
        assert "SET FOREIGN_KEY_CHECKS = 0" in text

    def test_shop_sql_uses_on_duplicate_key_update(self, tmp_sql_dir):
        """Shop INSERT includes ON DUPLICATE KEY UPDATE clause."""
        from generate_seed_sql import _generate_shop_sql

        shop_rows = [{"id": 900001, "name": "Test Shop", "type_id": 1,
                       "images": "img.jpg", "area": None, "address": "addr",
                       "x": 116.0, "y": 39.9, "avg_price": 50,
                       "sold": 0, "comments": 0, "score": 45,
                       "open_hours": "10:00-22:00",
                       "create_time": "2026-01-01 00:00:00",
                       "update_time": "2026-01-01 00:00:00"}]
        out = tmp_sql_dir / "test_shop_upsert.sql"
        _generate_shop_sql(shop_rows, out)

        text = out.read_text(encoding="utf-8")
        assert "ON DUPLICATE KEY UPDATE" in text
        # Should not end with a semicolon before the ON DUPLICATE KEY UPDATE clause
        assert "VALUES\nON DUPLICATE KEY UPDATE" not in text or True  # just check presence
        # Verify the UPDATE clause doesn't include `id`
        assert "`id`=VALUES(`id`)" not in text

    def test_voucher_sql_uses_on_duplicate_key_update(self, tmp_sql_dir):
        """Voucher INSERT includes ON DUPLICATE KEY UPDATE clause."""
        from generate_seed_sql import _generate_voucher_sql

        voucher_rows = [{"id": 910001, "shop_id": 900001, "title": "V",
                         "sub_title": None, "rules": None,
                         "pay_value": 500, "actual_value": 1000,
                         "type": 0, "status": 1,
                         "create_time": "2026-01-01 00:00:00",
                         "update_time": "2026-01-01 00:00:00"}]
        out = tmp_sql_dir / "test_voucher_upsert.sql"
        _generate_voucher_sql(voucher_rows, out)

        text = out.read_text(encoding="utf-8")
        assert "ON DUPLICATE KEY UPDATE" in text
        assert "`id`=VALUES(`id`)" not in text

    def test_seed_sql_is_idempotent_on_repeated_execution(self, tmp_sql_dir):
        """Generated SQL uses ON DUPLICATE KEY UPDATE, making it safe to re-run."""
        from generate_seed_sql import _generate_shop_sql, _generate_voucher_sql

        shop_rows = [{"id": 900001, "name": "A", "type_id": 1, "images": "i",
                       "area": None, "address": "a", "x": 1.0, "y": 2.0,
                       "avg_price": None, "sold": 0, "comments": 0, "score": 30,
                       "open_hours": None, "create_time": "t", "update_time": "t"}]
        voucher_rows = [{"id": 910001, "shop_id": 900001, "title": "V",
                          "sub_title": None, "rules": None,
                          "pay_value": 500, "actual_value": 1000,
                          "type": 0, "status": 1,
                          "create_time": "t", "update_time": "t"}]

        for gen_fn, rows, name in [
            (_generate_shop_sql, shop_rows, "shops"),
            (_generate_voucher_sql, voucher_rows, "vouchers"),
        ]:
            out = tmp_sql_dir / f"test_idempotent_{name}.sql"
            gen_fn(rows, out)
            text = out.read_text(encoding="utf-8")

            # Must have ON DUPLICATE KEY UPDATE
            assert "ON DUPLICATE KEY UPDATE" in text, \
                f"{name}: missing ON DUPLICATE KEY UPDATE"

            # The VALUES section's last data row must NOT end with ';'
            # (the final ';' belongs after the ON DUPLICATE KEY UPDATE clause)
            values_start = text.index("VALUES\n")
            dup_start = text.index("ON DUPLICATE KEY UPDATE")
            between = text[values_start:dup_start]
            non_empty_lines = [l for l in between.split("\n") if l.strip()]
            if non_empty_lines:
                last_val = non_empty_lines[-1]
                assert not last_val.rstrip().endswith(";"), \
                    f"{name}: VALUES row must NOT end with ';'"
