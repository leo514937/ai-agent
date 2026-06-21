"""Tests for import_mock_seed_to_mysql.py (Phase 3: DB import).

All tests use monkeypatching / mocking to avoid real database connections.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _set_minimal_db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMDP_MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("HMDP_MYSQL_PORT", "3306")
    monkeypatch.setenv("HMDP_MYSQL_DATABASE", "hmdp_test")
    monkeypatch.setenv("HMDP_MYSQL_USER", "test_user")
    monkeypatch.setenv("HMDP_MYSQL_PASSWORD", "s3cret!")


def _main_argv(monkeypatch, argv: list[str]) -> None:
    monkeypatch.setattr("sys.argv", argv)


# ── Helpers ─────────────────────────────────────────────────


class TestImportHelpers:

    def test_mask_password_empty(self):
        from import_mock_seed_to_mysql import _mask_password
        assert _mask_password("") == "(empty)"

    def test_mask_password_short(self):
        from import_mock_seed_to_mysql import _mask_password
        assert _mask_password("ab") == "**"
        assert _mask_password("abc") == "***"
        assert _mask_password("abcd") == "****"

    def test_mask_password_normal(self):
        from import_mock_seed_to_mysql import _mask_password
        # 7 chars: keep first 2, last 2, mask middle 3
        masked = _mask_password("s3cret!")
        assert masked == "s3***t!"

    def test_get_db_config_minimal(self, monkeypatch):
        from import_mock_seed_to_mysql import _get_db_config
        _set_minimal_db_env(monkeypatch)
        config = _get_db_config()
        assert config["host"] == "127.0.0.1"
        assert config["port"] == 3306
        assert config["database"] == "hmdp_test"
        assert config["user"] == "test_user"
        assert config["password"] == "s3cret!"
        assert config["_missing"] == []

    def test_get_db_config_missing(self, monkeypatch):
        from import_mock_seed_to_mysql import _get_db_config
        monkeypatch.delenv("HMDP_MYSQL_HOST", raising=False)
        monkeypatch.delenv("HMDP_MYSQL_DATABASE", raising=False)
        monkeypatch.delenv("HMDP_MYSQL_USER", raising=False)
        assert len(_get_db_config()["_missing"]) == 3


# ── Dry-run ─────────────────────────────────────────────────


class TestImportDryRun:

    def test_default_is_dry_run(self, monkeypatch):
        """Default execution (no --apply/--rollback) must NOT call execute_sql_files."""
        from import_mock_seed_to_mysql import main
        _set_minimal_db_env(monkeypatch)
        _main_argv(monkeypatch, ["import.py"])
        with patch("import_mock_seed_to_mysql.execute_sql_files") as mock_exec:
            main()
        mock_exec.assert_not_called()

    def test_dry_run_without_db_config_succeeds(self, monkeypatch):
        """Dry-run does not need database config."""
        from import_mock_seed_to_mysql import main
        monkeypatch.delenv("HMDP_MYSQL_HOST", raising=False)
        monkeypatch.delenv("HMDP_MYSQL_DATABASE", raising=False)
        monkeypatch.delenv("HMDP_MYSQL_USER", raising=False)
        _main_argv(monkeypatch, ["import.py"])
        main()  # should not raise

    def test_dry_run_prints_file_stats(self, monkeypatch, capsys):
        from import_mock_seed_to_mysql import main
        monkeypatch.delenv("HMDP_MYSQL_HOST", raising=False)
        monkeypatch.delenv("HMDP_MYSQL_DATABASE", raising=False)
        monkeypatch.delenv("HMDP_MYSQL_USER", raising=False)
        _main_argv(monkeypatch, ["import.py"])
        main()
        out = capsys.readouterr().out
        assert "dry-run" in out
        assert "seed_shops.sql" in out
        assert "No SQL was executed" in out

    def test_dry_run_no_db_config_does_not_connect(self, monkeypatch):
        """Even with DB env set, dry-run must NOT connect to database."""
        from import_mock_seed_to_mysql import main
        _set_minimal_db_env(monkeypatch)
        _main_argv(monkeypatch, ["import.py"])
        with patch("import_mock_seed_to_mysql.execute_sql_files") as mock_exec:
            main()
        mock_exec.assert_not_called()

    def test_dry_run_password_masked(self, monkeypatch, capsys):
        from import_mock_seed_to_mysql import main
        _set_minimal_db_env(monkeypatch)
        _main_argv(monkeypatch, ["import.py"])
        with patch("import_mock_seed_to_mysql.execute_sql_files") as mock_exec:
            main()
        mock_exec.assert_not_called()
        out = capsys.readouterr().out
        assert "s3cret!" not in out


# ── --apply / --rollback ────────────────────────────────────


class TestImportApplyAndRollback:

    def test_apply_and_rollback_mutually_exclusive(self, monkeypatch):
        from import_mock_seed_to_mysql import main
        _main_argv(monkeypatch, ["import.py", "--apply", "--rollback"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    def test_apply_calls_execute_sql_files_with_seed_files(self, monkeypatch):
        from import_mock_seed_to_mysql import main, SEED_FILES
        _set_minimal_db_env(monkeypatch)
        _main_argv(monkeypatch, ["import.py", "--apply"])
        with patch("import_mock_seed_to_mysql.execute_sql_files") as mock_exec:
            main()
        mock_exec.assert_called_once()
        assert mock_exec.call_args[0][0] == SEED_FILES

    def test_rollback_calls_execute_sql_files_with_rollback_file(self, monkeypatch):
        from import_mock_seed_to_mysql import main, ROLLBACK_FILES
        _set_minimal_db_env(monkeypatch)
        _main_argv(monkeypatch, ["import.py", "--rollback"])
        with patch("import_mock_seed_to_mysql.execute_sql_files") as mock_exec:
            main()
        mock_exec.assert_called_once()
        assert mock_exec.call_args[0][0] == ROLLBACK_FILES

    def test_apply_without_db_config_fails(self, monkeypatch):
        from import_mock_seed_to_mysql import main
        monkeypatch.delenv("HMDP_MYSQL_HOST", raising=False)
        monkeypatch.delenv("HMDP_MYSQL_DATABASE", raising=False)
        monkeypatch.delenv("HMDP_MYSQL_USER", raising=False)
        _main_argv(monkeypatch, ["import.py", "--apply"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    def test_rollback_without_db_config_fails(self, monkeypatch):
        from import_mock_seed_to_mysql import main
        monkeypatch.delenv("HMDP_MYSQL_HOST", raising=False)
        monkeypatch.delenv("HMDP_MYSQL_DATABASE", raising=False)
        monkeypatch.delenv("HMDP_MYSQL_USER", raising=False)
        _main_argv(monkeypatch, ["import.py", "--rollback"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    def test_apply_hides_password(self, monkeypatch, capsys):
        from import_mock_seed_to_mysql import main
        _set_minimal_db_env(monkeypatch)
        _main_argv(monkeypatch, ["import.py", "--apply"])
        with patch("import_mock_seed_to_mysql.execute_sql_files"):
            main()
        assert "s3cret!" not in capsys.readouterr().out


# ── execute_sql_files ───────────────────────────────────────


class TestExecuteSqlFiles:

    def test_requires_config(self):
        from import_mock_seed_to_mysql import execute_sql_files
        with pytest.raises(RuntimeError, match="Database not configured"):
            execute_sql_files([], {"_missing": ["HMDP_MYSQL_HOST"]})

    def test_raises_on_missing_file(self):
        from import_mock_seed_to_mysql import execute_sql_files
        cfg = {"_missing": [], "host": "x", "port": 3306, "database": "x", "user": "x", "password": ""}
        # Properly mock mysql and mysql.connector for the import statement
        mysql_mock = MagicMock()
        mysql_mock.connector = MagicMock()
        with patch.dict("sys.modules", {"mysql": mysql_mock, "mysql.connector": mysql_mock.connector}):
            with pytest.raises(FileNotFoundError):
                execute_sql_files(["nonexistent.sql"], cfg)


# ── Generated SQL file spot-checks ──────────────────────────


class TestGeneratedSqlFiles:

    SEED_DIR = Path(__file__).resolve().parent.parent.parent / "db" / "seed" / "local_life"

    def test_seed_shops_has_on_duplicate_key_update(self):
        text = (self.SEED_DIR / "seed_shops.sql").read_text(encoding="utf-8")
        assert "ON DUPLICATE KEY UPDATE" in text

    def test_seed_vouchers_has_on_duplicate_key_update(self):
        text = (self.SEED_DIR / "seed_vouchers.sql").read_text(encoding="utf-8")
        assert "ON DUPLICATE KEY UPDATE" in text

    def test_rollback_deletes_voucher_before_shop(self):
        text = (self.SEED_DIR / "rollback.sql").read_text(encoding="utf-8")
        assert text.index("DELETE FROM `tb_voucher`") < text.index("DELETE FROM `tb_shop`")

    def test_rollback_uses_between(self):
        text = (self.SEED_DIR / "rollback.sql").read_text(encoding="utf-8")
        assert "BETWEEN" in text
        assert "IN (" not in text

    def test_rollback_no_truncate_or_drop(self):
        text = (self.SEED_DIR / "rollback.sql").read_text(encoding="utf-8")
        assert "TRUNCATE" not in text.upper()
        assert "DROP" not in text.upper()

    def test_rollback_only_deletes_seed_ranges(self):
        text = (self.SEED_DIR / "rollback.sql").read_text(encoding="utf-8")
        assert "BETWEEN 910001 AND 910016" in text
        assert "BETWEEN 900001 AND 900027" in text

    def test_seed_shops_no_forbidden_fields(self):
        text = (self.SEED_DIR / "seed_shops.sql").read_text(encoding="utf-8")
        for field in ["open_status", "tags", "alias", "aliases", "phone"]:
            assert field not in text, f"Forbidden field '{field}' found"

    def test_seed_vouchers_no_forbidden_fields(self):
        text = (self.SEED_DIR / "seed_vouchers.sql").read_text(encoding="utf-8")
        for field in ["coupon_id", "discount_type", "discount_value", "stock", "valid_from", "valid_until"]:
            assert field not in text, f"Forbidden field '{field}' found"
