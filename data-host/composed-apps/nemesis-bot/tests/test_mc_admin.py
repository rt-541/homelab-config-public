import json
import os
import sys
import pytest

# Set env vars before import so mc_admin module-level path functions see them
os.environ.setdefault("MC_ALLOWLIST_PATH", "/tmp/test_allowlist.json")
os.environ.setdefault("MC_OPS_PATH", "/tmp/test_ops.json")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mc_admin import normalize_uuid, read_json_file, write_json_file


class TestNormalizeUuid:
    def test_dashed_passthrough(self):
        assert normalize_uuid("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97") == "0ce04728-e1b8-4f2b-a206-7a7ec18c7e97"

    def test_undashed_normalized(self):
        assert normalize_uuid("0ce04728e1b84f2ba2067a7ec18c7e97") == "0ce04728-e1b8-4f2b-a206-7a7ec18c7e97"

    def test_uppercase_normalized(self):
        assert normalize_uuid("0CE04728-E1B8-4F2B-A206-7A7EC18C7E97") == "0ce04728-e1b8-4f2b-a206-7a7ec18c7e97"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            normalize_uuid("not-a-uuid")

    def test_too_short_raises(self):
        with pytest.raises(ValueError):
            normalize_uuid("abcd")


class TestFileIO:
    def test_read_missing_file_returns_empty_list(self, tmp_path):
        result = read_json_file(str(tmp_path / "missing.json"))
        assert result == []

    def test_write_creates_file(self, tmp_path):
        path = str(tmp_path / "data.json")
        write_json_file(path, [{"uuid": "abc"}])
        assert os.path.exists(path)

    def test_write_and_read_roundtrip(self, tmp_path):
        path = str(tmp_path / "data.json")
        data = [{"uuid": "abc", "name": "Test"}]
        write_json_file(path, data)
        assert read_json_file(path) == data

    def test_write_is_valid_json(self, tmp_path):
        path = str(tmp_path / "data.json")
        write_json_file(path, [{"uuid": "abc"}])
        with open(path) as f:
            parsed = json.load(f)
        assert parsed == [{"uuid": "abc"}]


import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class TestLookupPlayerName:
    def _run(self, coro):
        return asyncio.run(coro)

    def _make_mock_session(self, status, json_data=None):
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.json = AsyncMock(return_value=json_data or {})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        return mock_session

    def test_success_returns_player_name(self):
        session = self._make_mock_session(
            200, {"id": "0ce04728e1b84f2ba2067a7ec18c7e97", "name": "Rizmore"}
        )
        with patch("mc_admin.aiohttp.ClientSession", return_value=session):
            from mc_admin import lookup_player_name
            result = self._run(lookup_player_name("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97"))
        assert result == "Rizmore"

    def test_not_found_204_raises_value_error(self):
        session = self._make_mock_session(204)
        with patch("mc_admin.aiohttp.ClientSession", return_value=session):
            from mc_admin import lookup_player_name
            with pytest.raises(ValueError, match="not found"):
                self._run(lookup_player_name("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97"))

    def test_api_error_raises_runtime_error(self):
        session = self._make_mock_session(500)
        with patch("mc_admin.aiohttp.ClientSession", return_value=session):
            from mc_admin import lookup_player_name
            with pytest.raises(RuntimeError, match="Mojang API error"):
                self._run(lookup_player_name("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97"))


class TestAllowlistOps:
    def test_add_new_player(self, tmp_path, monkeypatch):
        path = str(tmp_path / "allowlist.json")
        monkeypatch.setenv("MC_ALLOWLIST_PATH", path)
        from mc_admin import allowlist_add
        assert allowlist_add("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97", "Rizmore") is True
        assert read_json_file(path) == [{"uuid": "0ce04728-e1b8-4f2b-a206-7a7ec18c7e97", "name": "Rizmore"}]

    def test_add_duplicate_returns_false(self, tmp_path, monkeypatch):
        path = str(tmp_path / "allowlist.json")
        write_json_file(path, [{"uuid": "0ce04728-e1b8-4f2b-a206-7a7ec18c7e97", "name": "Rizmore"}])
        monkeypatch.setenv("MC_ALLOWLIST_PATH", path)
        from mc_admin import allowlist_add
        assert allowlist_add("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97", "Rizmore") is False

    def test_remove_existing_returns_name(self, tmp_path, monkeypatch):
        path = str(tmp_path / "allowlist.json")
        write_json_file(path, [{"uuid": "0ce04728-e1b8-4f2b-a206-7a7ec18c7e97", "name": "Rizmore"}])
        monkeypatch.setenv("MC_ALLOWLIST_PATH", path)
        from mc_admin import allowlist_remove
        assert allowlist_remove("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97") == "Rizmore"
        assert read_json_file(path) == []

    def test_remove_missing_returns_none(self, tmp_path, monkeypatch):
        path = str(tmp_path / "allowlist.json")
        monkeypatch.setenv("MC_ALLOWLIST_PATH", path)
        from mc_admin import allowlist_remove
        assert allowlist_remove("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97") is None


class TestOpsFileOps:
    def test_add_new_op(self, tmp_path, monkeypatch):
        path = str(tmp_path / "ops.json")
        monkeypatch.setenv("MC_OPS_PATH", path)
        from mc_admin import ops_add
        assert ops_add("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97", "Rizmore") is True
        assert read_json_file(path) == [{
            "uuid": "0ce04728-e1b8-4f2b-a206-7a7ec18c7e97",
            "name": "Rizmore",
            "level": 4,
            "bypassesPlayerLimit": False,
        }]

    def test_add_duplicate_op_returns_false(self, tmp_path, monkeypatch):
        path = str(tmp_path / "ops.json")
        write_json_file(path, [{"uuid": "0ce04728-e1b8-4f2b-a206-7a7ec18c7e97", "name": "Rizmore", "level": 4, "bypassesPlayerLimit": False}])
        monkeypatch.setenv("MC_OPS_PATH", path)
        from mc_admin import ops_add
        assert ops_add("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97", "Rizmore") is False

    def test_remove_op_returns_name(self, tmp_path, monkeypatch):
        path = str(tmp_path / "ops.json")
        write_json_file(path, [{"uuid": "0ce04728-e1b8-4f2b-a206-7a7ec18c7e97", "name": "Rizmore", "level": 4, "bypassesPlayerLimit": False}])
        monkeypatch.setenv("MC_OPS_PATH", path)
        from mc_admin import ops_remove
        assert ops_remove("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97") == "Rizmore"
        assert read_json_file(path) == []

    def test_remove_missing_op_returns_none(self, tmp_path, monkeypatch):
        path = str(tmp_path / "ops.json")
        monkeypatch.setenv("MC_OPS_PATH", path)
        from mc_admin import ops_remove
        assert ops_remove("0ce04728-e1b8-4f2b-a206-7a7ec18c7e97") is None
