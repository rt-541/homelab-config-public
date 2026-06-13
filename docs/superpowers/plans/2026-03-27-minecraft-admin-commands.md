# Minecraft Admin Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/mc-allowlist` and `/mc-ops` Discord slash commands so users with the Admin or Minecraft Admin role can add/remove players from the Minecraft server allowlist and ops files.

**Architecture:** New `mc_admin.py` module holds all utility functions (UUID normalization, file I/O, Mojang API lookup, allowlist/ops operations) and the slash command groups. The existing `can_access()` function in `bot_commands.py` gates access by checking whether the caller can access the `mcatm9s` container — both ROLE_ADMIN (`*`) and the new ROLE_MCADMIN (`mcatm9s`) satisfy this check automatically. `register_mc_commands()` is called from inside `register_commands()` and uses a lazy import of `can_access` to avoid a circular import.

**Tech Stack:** Python 3.12, discord.py 2.3.2 (`app_commands.Group` for subcommands), aiohttp 3.9.5 (Mojang API), pytest for tests.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `composed-apps/nemesis-bot/mc_admin.py` | Create | UUID normalization, file I/O, Mojang lookup, allowlist/ops operations, slash command groups |
| `composed-apps/nemesis-bot/tests/__init__.py` | Create | Empty — marks tests as a package |
| `composed-apps/nemesis-bot/tests/test_mc_admin.py` | Create | Unit tests for all utility functions |
| `composed-apps/nemesis-bot/bot_commands.py` | Modify | Import and call `register_mc_commands` at end of `register_commands()` |
| `composed-apps/nemesis-bot/docker-compose.yml` | Modify | Add ROLE_MCADMIN env vars, MC_*_PATH env vars, file volume mounts |
| `composed-apps/nemesis-bot/.env.example` | Modify | Document `ROLE_MCADMIN_ID` |

---

### Task 1: Configure environment and file mounts

**Files:**
- Modify: `composed-apps/nemesis-bot/.env.example`
- Modify: `composed-apps/nemesis-bot/docker-compose.yml`

- [ ] **Step 1: Add ROLE_MCADMIN_ID to .env.example**

In `.env.example`, add after the `ROLE_MINECRAFT_ID=` line:
```
ROLE_MCADMIN_ID=
```

- [ ] **Step 2: Update docker-compose.yml — environment section**

In the bot's `environment:` block, after the `ROLE_MINECRAFT_*` lines, add:
```yaml
      ROLE_MCADMIN_ID: "${ROLE_MCADMIN_ID}"
      ROLE_MCADMIN_NAME: "Minecraft Admin"
      ROLE_MCADMIN_CONTAINERS: "mcatm9s"

      MC_ALLOWLIST_PATH: "/mc/allowed_users.json"
      MC_OPS_PATH: "/mc/ops.json"
```

- [ ] **Step 3: Update docker-compose.yml — volumes section**

In the bot's `volumes:` block, add:
```yaml
      - /docker/nemesis-configs/composed-apps/minecraft-atm9-survival/allowed_users.json:/mc/allowed_users.json
      - /docker/game/minecraft/minecraftatm9s_data/ops.json:/mc/ops.json
```

- [ ] **Step 4: Commit**
```bash
git add composed-apps/nemesis-bot/.env.example composed-apps/nemesis-bot/docker-compose.yml
git commit -m "feat(nemesis-bot): add Minecraft Admin role config and file mounts"
```

---

### Task 2: Core utilities — UUID normalization and file I/O

**Files:**
- Create: `composed-apps/nemesis-bot/tests/__init__.py`
- Create: `composed-apps/nemesis-bot/tests/test_mc_admin.py`
- Create: `composed-apps/nemesis-bot/mc_admin.py`

- [ ] **Step 1: Install test dependencies locally**
```bash
pip install pytest pytest-asyncio
```

- [ ] **Step 2: Create tests directory**

Create `composed-apps/nemesis-bot/tests/__init__.py` as an empty file.

- [ ] **Step 3: Write failing tests**

Create `composed-apps/nemesis-bot/tests/test_mc_admin.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they fail**
```bash
cd composed-apps/nemesis-bot && pytest tests/test_mc_admin.py::TestNormalizeUuid tests/test_mc_admin.py::TestFileIO -v
```
Expected: `ModuleNotFoundError: No module named 'mc_admin'`

- [ ] **Step 5: Create mc_admin.py with core utilities**

Create `composed-apps/nemesis-bot/mc_admin.py`:
```python
import json
import os
import tempfile

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands


# ── Paths ──────────────────────────────────────────────────────────────────

def _allowlist_path() -> str:
    return os.environ.get("MC_ALLOWLIST_PATH", "/mc/allowed_users.json")


def _ops_path() -> str:
    return os.environ.get("MC_OPS_PATH", "/mc/ops.json")


# ── UUID utilities ─────────────────────────────────────────────────────────

def normalize_uuid(raw: str) -> str:
    """Return UUID in lowercase dashed format regardless of input format."""
    clean = raw.replace("-", "").lower()
    if len(clean) != 32 or not all(c in "0123456789abcdef" for c in clean):
        raise ValueError(f"Invalid UUID: {raw!r}")
    return f"{clean[0:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:32]}"


# ── File I/O ───────────────────────────────────────────────────────────────

def read_json_file(path: str) -> list:
    """Read JSON list from path. Returns [] if file does not exist."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def write_json_file(path: str, data: list) -> None:
    """Atomically write data as JSON to path."""
    dir_ = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as f:
        json.dump(data, f, indent=2)
        tmp = f.name
    os.replace(tmp, path)
```

- [ ] **Step 6: Run tests to verify they pass**
```bash
cd composed-apps/nemesis-bot && pytest tests/test_mc_admin.py::TestNormalizeUuid tests/test_mc_admin.py::TestFileIO -v
```
Expected: All 9 tests PASS.

- [ ] **Step 7: Commit**
```bash
git add composed-apps/nemesis-bot/mc_admin.py composed-apps/nemesis-bot/tests/
git commit -m "feat(nemesis-bot): add mc_admin core utilities with tests"
```

---

### Task 3: Mojang API lookup

**Files:**
- Modify: `composed-apps/nemesis-bot/tests/test_mc_admin.py`
- Modify: `composed-apps/nemesis-bot/mc_admin.py`

- [ ] **Step 1: Write failing tests for lookup_player_name**

Append to the bottom of `tests/test_mc_admin.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**
```bash
cd composed-apps/nemesis-bot && pytest tests/test_mc_admin.py::TestLookupPlayerName -v
```
Expected: `ImportError` or `AttributeError: module 'mc_admin' has no attribute 'lookup_player_name'`

- [ ] **Step 3: Add lookup_player_name to mc_admin.py**

Add after `write_json_file`:
```python
# ── Mojang API ─────────────────────────────────────────────────────────────

async def lookup_player_name(uuid: str) -> str:
    """Fetch Minecraft player name from Mojang API by UUID.

    Raises ValueError if the player does not exist.
    Raises RuntimeError on unexpected API errors or if unreachable.
    """
    no_dashes = uuid.replace("-", "")
    url = f"https://sessionserver.mojang.com/session/minecraft/profile/{no_dashes}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status in (204, 404):
                raise ValueError(f"UUID {uuid!r} not found on Mojang servers.")
            if resp.status != 200:
                raise RuntimeError(f"Mojang API error: HTTP {resp.status}")
            data = await resp.json()
            return data["name"]
```

- [ ] **Step 4: Run tests to verify they pass**
```bash
cd composed-apps/nemesis-bot && pytest tests/test_mc_admin.py::TestLookupPlayerName -v
```
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**
```bash
git add composed-apps/nemesis-bot/mc_admin.py composed-apps/nemesis-bot/tests/test_mc_admin.py
git commit -m "feat(nemesis-bot): add Mojang API UUID lookup with tests"
```

---

### Task 4: Allowlist and ops file operations

**Files:**
- Modify: `composed-apps/nemesis-bot/tests/test_mc_admin.py`
- Modify: `composed-apps/nemesis-bot/mc_admin.py`

- [ ] **Step 1: Write failing tests for allowlist and ops operations**

Append to `tests/test_mc_admin.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**
```bash
cd composed-apps/nemesis-bot && pytest tests/test_mc_admin.py::TestAllowlistOps tests/test_mc_admin.py::TestOpsFileOps -v
```
Expected: `ImportError: cannot import name 'allowlist_add' from 'mc_admin'`

- [ ] **Step 3: Add allowlist and ops functions to mc_admin.py**

Add after `lookup_player_name`:
```python
# ── Allowlist operations ───────────────────────────────────────────────────

def allowlist_add(uuid: str, name: str) -> bool:
    """Add player to allowlist. Returns False if already present."""
    path = _allowlist_path()
    entries = read_json_file(path)
    if any(e["uuid"] == uuid for e in entries):
        return False
    entries.append({"uuid": uuid, "name": name})
    write_json_file(path, entries)
    return True


def allowlist_remove(uuid: str) -> str | None:
    """Remove player by UUID. Returns player name if removed, None if not found."""
    path = _allowlist_path()
    entries = read_json_file(path)
    for i, e in enumerate(entries):
        if e["uuid"] == uuid:
            removed = entries.pop(i)
            write_json_file(path, entries)
            return removed["name"]
    return None


def allowlist_list() -> list[dict]:
    """Return all allowlist entries."""
    return read_json_file(_allowlist_path())


# ── Ops operations ─────────────────────────────────────────────────────────

def ops_add(uuid: str, name: str) -> bool:
    """Add player to ops (level 4). Returns False if already present."""
    path = _ops_path()
    entries = read_json_file(path)
    if any(e["uuid"] == uuid for e in entries):
        return False
    entries.append({"uuid": uuid, "name": name, "level": 4, "bypassesPlayerLimit": False})
    write_json_file(path, entries)
    return True


def ops_remove(uuid: str) -> str | None:
    """Remove op by UUID. Returns player name if removed, None if not found."""
    path = _ops_path()
    entries = read_json_file(path)
    for i, e in enumerate(entries):
        if e["uuid"] == uuid:
            removed = entries.pop(i)
            write_json_file(path, entries)
            return removed["name"]
    return None


def ops_list() -> list[dict]:
    """Return all ops entries."""
    return read_json_file(_ops_path())
```

- [ ] **Step 4: Run all tests to verify they pass**
```bash
cd composed-apps/nemesis-bot && pytest tests/ -v
```
Expected: All tests PASS.

- [ ] **Step 5: Commit**
```bash
git add composed-apps/nemesis-bot/mc_admin.py composed-apps/nemesis-bot/tests/test_mc_admin.py
git commit -m "feat(nemesis-bot): add allowlist and ops file operations with tests"
```

---

### Task 5: Slash commands and registration

**Files:**
- Modify: `composed-apps/nemesis-bot/mc_admin.py`
- Modify: `composed-apps/nemesis-bot/bot_commands.py`

- [ ] **Step 1: Add register_mc_commands() to the bottom of mc_admin.py**

Append to `composed-apps/nemesis-bot/mc_admin.py`:
```python
# ── Slash commands ─────────────────────────────────────────────────────────

def register_mc_commands(bot: commands.Bot) -> None:
    """Register /mc-allowlist and /mc-ops command groups on the bot tree."""
    # Lazy import avoids circular import: bot_commands imports mc_admin,
    # mc_admin imports can_access only when register_mc_commands() is called.
    from bot_commands import can_access

    mc_allowlist = app_commands.Group(
        name="mc-allowlist", description="Manage Minecraft server allowlist"
    )
    mc_ops_grp = app_commands.Group(
        name="mc-ops", description="Manage Minecraft server ops"
    )

    # ── /mc-allowlist add ──────────────────────────────────────────────────
    @mc_allowlist.command(name="add", description="Add a player to the allowlist by UUID")
    async def allowlist_add_cmd(interaction: discord.Interaction, uuid: str):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            norm = normalize_uuid(uuid)
        except ValueError:
            await interaction.followup.send(f"`{uuid}` is not a valid UUID.", ephemeral=True)
            return
        try:
            name = await lookup_player_name(norm)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except RuntimeError as e:
            await interaction.followup.send(f"Mojang API unavailable: {e}", ephemeral=True)
            return
        if not allowlist_add(norm, name):
            await interaction.followup.send(
                f"**{name}** (`{norm}`) is already on the allowlist.", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"{interaction.user.display_name} added **{name}** (`{norm}`) to the allowlist."
        )

    # ── /mc-allowlist remove ───────────────────────────────────────────────
    @mc_allowlist.command(name="remove", description="Remove a player from the allowlist by UUID")
    async def allowlist_remove_cmd(interaction: discord.Interaction, uuid: str):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        try:
            norm = normalize_uuid(uuid)
        except ValueError:
            await interaction.response.send_message(f"`{uuid}` is not a valid UUID.", ephemeral=True)
            return
        removed_name = allowlist_remove(norm)
        if removed_name is None:
            await interaction.response.send_message(
                f"UUID `{norm}` was not found on the allowlist.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"{interaction.user.display_name} removed **{removed_name}** (`{norm}`) from the allowlist."
        )

    # ── /mc-allowlist list ─────────────────────────────────────────────────
    @mc_allowlist.command(name="list", description="Show all players on the allowlist")
    async def allowlist_list_cmd(interaction: discord.Interaction):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        entries = allowlist_list()
        if not entries:
            await interaction.response.send_message("The allowlist is empty.", ephemeral=True)
            return
        lines = [f"`{e['uuid']}` — **{e['name']}**" for e in entries]
        embed = discord.Embed(
            title=f"Minecraft Allowlist ({len(entries)} players)",
            description="\n".join(lines),
            color=0x57F287,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /mc-ops add ────────────────────────────────────────────────────────
    @mc_ops_grp.command(name="add", description="Add a player to ops by UUID")
    async def ops_add_cmd(interaction: discord.Interaction, uuid: str):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            norm = normalize_uuid(uuid)
        except ValueError:
            await interaction.followup.send(f"`{uuid}` is not a valid UUID.", ephemeral=True)
            return
        try:
            name = await lookup_player_name(norm)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except RuntimeError as e:
            await interaction.followup.send(f"Mojang API unavailable: {e}", ephemeral=True)
            return
        if not ops_add(norm, name):
            await interaction.followup.send(
                f"**{name}** (`{norm}`) is already an op.", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"{interaction.user.display_name} added **{name}** (`{norm}`) to ops."
            f"\n> Changes take effect after the server is restarted (`/restart mcatm9s`)."
        )

    # ── /mc-ops remove ─────────────────────────────────────────────────────
    @mc_ops_grp.command(name="remove", description="Remove a player from ops by UUID")
    async def ops_remove_cmd(interaction: discord.Interaction, uuid: str):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        try:
            norm = normalize_uuid(uuid)
        except ValueError:
            await interaction.response.send_message(f"`{uuid}` is not a valid UUID.", ephemeral=True)
            return
        removed_name = ops_remove(norm)
        if removed_name is None:
            await interaction.response.send_message(
                f"UUID `{norm}` was not found in ops.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"{interaction.user.display_name} removed **{removed_name}** (`{norm}`) from ops."
            f"\n> Changes take effect after the server is restarted (`/restart mcatm9s`)."
        )

    # ── /mc-ops list ───────────────────────────────────────────────────────
    @mc_ops_grp.command(name="list", description="Show all current ops")
    async def ops_list_cmd(interaction: discord.Interaction):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        entries = ops_list()
        if not entries:
            await interaction.response.send_message("The ops list is empty.", ephemeral=True)
            return
        lines = [f"`{e['uuid']}` — **{e['name']}** (level {e.get('level', 4)})" for e in entries]
        embed = discord.Embed(
            title=f"Minecraft Ops ({len(entries)} operators)",
            description="\n".join(lines),
            color=0xFEE75C,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    bot.tree.add_command(mc_allowlist)
    bot.tree.add_command(mc_ops_grp)
```

- [ ] **Step 2: Wire register_mc_commands into bot_commands.py**

At the top of `composed-apps/nemesis-bot/bot_commands.py`, after the existing imports, add:
```python
from mc_admin import register_mc_commands
```

At the very end of the `register_commands(bot)` function body (after all `@bot.tree.command` definitions, before the function closes), add:
```python
    register_mc_commands(bot)
```

- [ ] **Step 3: Run all tests to confirm nothing is broken**
```bash
cd composed-apps/nemesis-bot && pytest tests/ -v
```
Expected: All tests PASS.

- [ ] **Step 4: Commit**
```bash
git add composed-apps/nemesis-bot/mc_admin.py composed-apps/nemesis-bot/bot_commands.py
git commit -m "feat(nemesis-bot): add /mc-allowlist and /mc-ops slash commands"
```

---

### Task 6: Create Discord role, deploy, and smoke test

**Files:** No file changes (`.env` edit only — not committed).

- [ ] **Step 1: Create the Minecraft Admin role in Discord**

In your Discord server:
1. Go to Server Settings > Roles > Create Role
2. Name it `Minecraft Admin`
3. Enable Developer Mode if needed: User Settings > Advanced > Developer Mode
4. Right-click the new role > Copy Role ID

- [ ] **Step 2: Add ROLE_MCADMIN_ID to .env**

In `composed-apps/nemesis-bot/.env`, add:
```
ROLE_MCADMIN_ID=<paste role ID here>
```

- [ ] **Step 3: Rebuild and restart the bot**
```bash
cd /docker/nemesis-configs/composed-apps/nemesis-bot
sudo docker compose down && sudo docker compose build && sudo docker compose up -d
```

- [ ] **Step 4: Check logs for startup errors**
```bash
sudo docker compose logs --tail=40 nemesis-bot
```
Expected: `Bot online as ...`, `Slash commands synced`, no tracebacks.

- [ ] **Step 5: Smoke test in Discord**

Run the following in a Discord channel where the bot is present:
1. `/mc-allowlist list` — should show current allowlist as an ephemeral embed (10 players)
2. `/mc-allowlist add` with a valid UUID — should look up the name, post publicly confirming the add
3. `/mc-allowlist remove` with that same UUID — should post publicly confirming the remove
4. `/mc-ops list` — should show empty list or current ops
5. `/mc-ops add` with a valid UUID — should add to ops and remind you to restart for changes to take effect

- [ ] **Step 6: Verify files on disk**
```bash
cat /docker/nemesis-configs/composed-apps/minecraft-atm9-survival/allowed_users.json
cat /docker/game/minecraft/minecraftatm9s_data/ops.json
```
Confirm that add/remove operations were reflected in both files correctly.
