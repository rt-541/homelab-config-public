#!/usr/bin/env python3
"""
zomboid-b42-migration/migrate.py

Migrates player data, vehicles, and chunk files from a B42.15 backup into a
fresh B42.16 save directory.

Usage:
    sudo python3 migrate.py --backup-dir /docker/game/zomboid/manual-backups \
                            --save-dir <fresh-b42-save-path> \
                            [--dry-run]
"""

import argparse
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLAYER_TABLE = "networkPlayers"
EXPECTED_PLAYER_COUNT = 8
EXPECTED_VEHICLE_COUNT = 48
EXPECTED_CHUNK_COUNT = 22

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def find_file_in_save(save_dir: Path, filename: str) -> Optional[Path]:
    """Search for *filename* in save_dir (flat) then one level deep."""
    candidate = save_dir / filename
    if candidate.exists():
        return candidate
    for child in save_dir.iterdir():
        if child.is_dir():
            deep = child / filename
            if deep.exists():
                return deep
    return None


def find_chunkdata_dir(save_dir: Path) -> Optional[Path]:
    """Return the chunkdata/ directory inside save_dir, or None."""
    candidate = save_dir / "chunkdata"
    if candidate.is_dir():
        return candidate
    for child in save_dir.iterdir():
        if child.is_dir():
            deep = child / "chunkdata"
            if deep.is_dir():
                return deep
    return None


def get_table_info(conn: sqlite3.Connection, table: str) -> list[dict]:
    """Return PRAGMA table_info rows as dicts."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    keys = [d[0] for d in cur.description]
    return [dict(zip(keys, row)) for row in cur.fetchall()]


def read_magic(path: Path) -> bytes:
    """Read first 4 bytes of a file."""
    with open(path, "rb") as fh:
        return fh.read(4)


# ---------------------------------------------------------------------------
# Report accumulator
# ---------------------------------------------------------------------------


class Report:
    def __init__(self, dry_run: bool):
        self.lines: list[str] = []
        self.dry_run = dry_run
        self.overall_pass = True

    def add(self, msg: str = "") -> None:
        print(msg)
        self.lines.append(msg)

    def fail(self, msg: str) -> None:
        self.add(f"FAIL: {msg}")
        self.overall_pass = False

    def warn(self, msg: str) -> None:
        self.add(f"WARNING: {msg}")

    def info(self, msg: str) -> None:
        self.add(f"  {msg}")

    def section(self, title: str) -> None:
        self.add()
        self.add(f"{'='*60}")
        self.add(f"  {title}")
        self.add(f"{'='*60}")

    def write(self, script_dir: Path) -> None:
        if self.dry_run:
            return
        report_path = script_dir / "migration_report.txt"
        report_path.write_text("\n".join(self.lines))
        print(f"\nReport written to: {report_path}")


# ---------------------------------------------------------------------------
# Phase 1 — Players
# ---------------------------------------------------------------------------


def phase_players(
    backup_dir: Path,
    save_dir: Path,
    report: Report,
    dry_run: bool,
) -> None:
    report.section("Phase 1 — Players")

    # Locate players.db in backup dir
    backup_db_path = find_file_in_save(backup_dir, "players.db")
    if backup_db_path is None:
        report.fail(
            f"players.db not found in backup-dir '{backup_dir}' or one level deep. "
            "Expected location: <backup-dir>/players.db (or a subdirectory). "
            "Ensure the ZomboidConfig Saves directory was included in the backup."
        )
        return

    # Locate players.db in fresh save
    fresh_db_path = find_file_in_save(save_dir, "players.db")
    if fresh_db_path is None:
        report.fail(
            f"players.db not found in save-dir '{save_dir}' or one level deep."
        )
        return

    report.info(f"Backup players.db : {backup_db_path}")
    report.info(f"Fresh  players.db : {fresh_db_path}")

    backup_conn = sqlite3.connect(f"file:{backup_db_path}?mode=ro", uri=True)
    if dry_run:
        fresh_conn = sqlite3.connect(f"file:{fresh_db_path}?mode=ro", uri=True)
    else:
        fresh_conn = sqlite3.connect(str(fresh_db_path))

    try:
        # Schema comparison
        backup_cols_info = get_table_info(backup_conn, PLAYER_TABLE)
        fresh_cols_info = get_table_info(fresh_conn, PLAYER_TABLE)

        if not backup_cols_info:
            report.fail(f"Table '{PLAYER_TABLE}' not found in backup players.db.")
            return
        if not fresh_cols_info:
            report.fail(f"Table '{PLAYER_TABLE}' not found in fresh players.db.")
            return

        backup_col_names = {r["name"] for r in backup_cols_info}
        fresh_col_names = {r["name"] for r in fresh_cols_info}

        shared_cols = sorted(backup_col_names & fresh_col_names)
        backup_only = sorted(backup_col_names - fresh_col_names)
        fresh_only = sorted(fresh_col_names - backup_col_names)

        report.add()
        report.add(f"  Table: {PLAYER_TABLE}")
        report.add(f"  Shared columns ({len(shared_cols)}): {', '.join(shared_cols)}")
        if backup_only:
            report.add(f"  Backup-only columns ({len(backup_only)}): {', '.join(backup_only)}")
        if fresh_only:
            report.add(f"  B42.16-only columns ({len(fresh_only)}): {', '.join(fresh_only)}")

        # Check for NOT NULL without default blockers in fresh-only columns
        fresh_col_map = {r["name"]: r for r in fresh_cols_info}
        blockers = [
            name
            for name in fresh_only
            if fresh_col_map[name]["notnull"] == 1
            and fresh_col_map[name]["dflt_value"] is None
        ]
        if blockers:
            report.fail(
                f"B42.16-only NOT NULL columns with no default (cannot INSERT without them): "
                f"{', '.join(blockers)}. Aborting Phase 1."
            )
            return

        # Count rows in backup
        (backup_count,) = backup_conn.execute(
            f"SELECT COUNT(*) FROM {PLAYER_TABLE}"
        ).fetchone()
        report.add()
        report.add(f"  Backup row count : {backup_count}")

        if dry_run:
            report.add(
                f"  [dry-run] Would INSERT OR REPLACE {backup_count} rows using columns: "
                f"{', '.join(shared_cols)}"
            )
            report.add(f"  [dry-run] Expected post-insert count: {EXPECTED_PLAYER_COUNT}")
            return

        # Perform INSERT OR REPLACE for each row
        col_list = ", ".join(shared_cols)
        placeholders = ", ".join("?" for _ in shared_cols)
        insert_sql = (
            f"INSERT OR REPLACE INTO {PLAYER_TABLE} ({col_list}) "
            f"VALUES ({placeholders})"
        )

        rows = backup_conn.execute(
            f"SELECT {col_list} FROM {PLAYER_TABLE}"
        ).fetchall()

        try:
            fresh_conn.execute("BEGIN")
            fresh_conn.executemany(insert_sql, rows)
            fresh_conn.commit()
        except Exception:
            fresh_conn.rollback()
            raise
        inserted = len(rows)

        (final_count,) = fresh_conn.execute(
            f"SELECT COUNT(*) FROM {PLAYER_TABLE}"
        ).fetchone()

        report.add(f"  Rows inserted    : {inserted}")
        report.add(f"  Post-insert count: {final_count} (expected {EXPECTED_PLAYER_COUNT})")

        if final_count != EXPECTED_PLAYER_COUNT:
            report.fail(
                f"Player count mismatch: got {final_count}, expected {EXPECTED_PLAYER_COUNT}."
            )
        else:
            report.add("  Player import: OK")

    finally:
        backup_conn.close()
        fresh_conn.close()


# ---------------------------------------------------------------------------
# Phase 2 — Vehicles
# ---------------------------------------------------------------------------


def phase_vehicles(
    backup_dir: Path,
    save_dir: Path,
    report: Report,
    dry_run: bool,
) -> None:
    report.section("Phase 2 — Vehicles")

    sql_path = backup_dir / "firestation-chunk-backup" / "vehicles_base.sql"
    if not sql_path.exists():
        report.fail(f"vehicles_base.sql not found at expected path: {sql_path}")
        return

    fresh_db_path = find_file_in_save(save_dir, "vehicles.db")
    if fresh_db_path is None:
        report.fail(f"vehicles.db not found in save-dir '{save_dir}' or one level deep.")
        return

    report.info(f"SQL source  : {sql_path}")
    report.info(f"vehicles.db : {fresh_db_path}")

    # Parse INSERT statements from file, extract IDs
    insert_pattern = re.compile(
        r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+vehicles\s*\([^)]*\)\s*VALUES\s*\((\d+)",
        re.IGNORECASE,
    )

    parsed_rows: list[tuple[int, str]] = []  # (id, full_line)
    with open(sql_path, "r") as fh:
        for line in fh:
            m = insert_pattern.match(line)
            if m:
                vid = int(m.group(1))
                parsed_rows.append((vid, line.rstrip()))

    report.add()
    report.add(f"  Parsed vehicle rows: {len(parsed_rows)} (expected {EXPECTED_VEHICLE_COUNT})")
    if len(parsed_rows) != EXPECTED_VEHICLE_COUNT:
        report.warn(
            f"Expected {EXPECTED_VEHICLE_COUNT} vehicle rows but parsed {len(parsed_rows)}."
        )

    parsed_ids = [vid for vid, _ in parsed_rows]

    if dry_run:
        fresh_conn = sqlite3.connect(f"file:{fresh_db_path}?mode=ro", uri=True)
    else:
        fresh_conn = sqlite3.connect(str(fresh_db_path))

    try:
        # Check for ID conflicts in fresh db
        if parsed_ids:
            placeholders = ",".join("?" for _ in parsed_ids)
            conflict_rows = fresh_conn.execute(
                f"SELECT id FROM vehicles WHERE id IN ({placeholders})", parsed_ids
            ).fetchall()
            conflict_ids = [r[0] for r in conflict_rows]
        else:
            conflict_ids = []

        if conflict_ids:
            report.warn(
                f"IDs already present in fresh vehicles.db that will be skipped "
                f"(INSERT OR IGNORE): {conflict_ids}"
            )
        else:
            report.add("  No ID conflicts in fresh vehicles.db.")

        if dry_run:
            report.add(
                f"  [dry-run] Would execute {len(parsed_rows)} INSERT OR IGNORE statements."
            )
            return

        # Execute inserts row-by-row using cursor.execute(), not executescript()
        cursor = fresh_conn.cursor()
        fresh_conn.execute("BEGIN")
        inserted = 0
        for vid, line in parsed_rows:
            # Rewrite INSERT OR REPLACE -> INSERT OR IGNORE per spec
            insert_line = re.sub(
                r"INSERT\s+OR\s+REPLACE",
                "INSERT OR IGNORE",
                line,
                flags=re.IGNORECASE,
            )
            cursor.execute(insert_line)
            inserted += 1
        fresh_conn.commit()

        id_placeholders = ",".join("?" * len(parsed_ids))
        cursor.execute(f"SELECT COUNT(*) FROM vehicles WHERE id IN ({id_placeholders})", parsed_ids)
        final_count = cursor.fetchone()[0]
        report.add(f"  Statements executed: {inserted}")
        report.add(f"  Post-insert count: {final_count} (expected {EXPECTED_VEHICLE_COUNT})")

        if final_count != EXPECTED_VEHICLE_COUNT:
            report.warn(
                f"Vehicle count {final_count} != expected {EXPECTED_VEHICLE_COUNT}. "
                "Some rows may have been skipped due to INSERT OR IGNORE conflicts."
            )
        else:
            report.add("  Vehicle import: OK")

    finally:
        fresh_conn.close()


# ---------------------------------------------------------------------------
# Phase 3 — Chunks
# ---------------------------------------------------------------------------


def phase_chunks(
    backup_dir: Path,
    save_dir: Path,
    report: Report,
    dry_run: bool,
) -> None:
    report.section("Phase 3 — Chunks")

    chunk_backup_dir = backup_dir / "firestation-chunk-backup"
    backup_chunks = sorted(chunk_backup_dir.glob("chunkdata_*.bin"))

    if not backup_chunks:
        report.fail(f"No chunkdata_*.bin files found under {chunk_backup_dir}")
        return

    report.add(f"  Backup chunk files: {len(backup_chunks)} (expected {EXPECTED_CHUNK_COUNT})")
    if len(backup_chunks) != EXPECTED_CHUNK_COUNT:
        report.warn(
            f"Expected {EXPECTED_CHUNK_COUNT} chunk files but found {len(backup_chunks)}."
        )

    chunkdata_dir = find_chunkdata_dir(save_dir)
    if chunkdata_dir is None:
        report.fail(f"chunkdata/ directory not found in save-dir '{save_dir}'.")
        return

    report.info(f"Target chunkdata/: {chunkdata_dir}")

    # Magic-byte compatibility check
    fresh_bin_files = sorted(chunkdata_dir.glob("chunkdata_*.bin"))

    if fresh_bin_files:
        backup_magic = read_magic(backup_chunks[0])
        fresh_ref = fresh_bin_files[0]
        fresh_magic = read_magic(fresh_ref)
        report.add()
        report.add(f"  Magic byte check:")
        report.add(f"    Backup  ({backup_chunks[0].name}): {backup_magic.hex()}")
        report.add(f"    Fresh   ({fresh_ref.name}): {fresh_magic.hex()}")
        if backup_magic != fresh_magic:
            for bc in backup_chunks:
                bm = read_magic(bc)
                if bm != fresh_magic:
                    report.warn(
                        f"DATA LOSS WARNING: {bc.name} has magic {bm.hex()} but fresh "
                        f"world uses {fresh_magic.hex()}. Format incompatibility detected."
                    )
        else:
            report.add("    Magic bytes match — format compatible.")
    else:
        report.add()
        report.add(
            "  Magic byte check skipped: no chunkdata_*.bin files exist in "
            "fresh world to compare against."
        )

    # Copy chunks
    report.add()
    copied = 0
    backed_up = 0

    for src in backup_chunks:
        dest = chunkdata_dir / src.name
        if dry_run:
            if dest.exists():
                report.add(
                    f"  [dry-run] Would backup {dest.name} -> {dest.name}.bak, "
                    f"then copy from {src}"
                )
            else:
                report.add(f"  [dry-run] Would copy {src.name} -> {dest}")
            copied += 1
            continue

        if dest.exists():
            bak_dest = dest.with_suffix(dest.suffix + ".bak")
            shutil.copy2(dest, bak_dest)
            backed_up += 1
            report.add(f"  Backed up existing: {dest.name} -> {bak_dest.name}")

        shutil.copy2(src, dest)
        copied += 1

    if not dry_run:
        report.add()
        report.add(f"  Chunks copied       : {copied}")
        report.add(f"  Existing files saved: {backed_up} (as .bak)")
        report.add("  Chunk copy: OK")
    else:
        report.add(f"  [dry-run] Would copy {copied} chunk files.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate B42.15 player/vehicle/chunk data into a fresh B42.16 save."
    )
    parser.add_argument(
        "--backup-dir",
        required=True,
        type=Path,
        help="Path to the manual-backups directory (contains player-exports/, "
             "firestation-chunk-backup/).",
    )
    parser.add_argument(
        "--save-dir",
        required=True,
        type=Path,
        help="Path to the fresh B42.16 save directory (contains players.db, "
             "vehicles.db, chunkdata/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen; write no files and open no databases for write.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    backup_dir: Path = args.backup_dir
    save_dir: Path = args.save_dir
    dry_run: bool = args.dry_run

    # Validate paths
    if not backup_dir.exists():
        print(f"ERROR: --backup-dir '{backup_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)
    if not save_dir.exists():
        print(f"ERROR: --save-dir '{save_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    script_dir = Path(__file__).parent.resolve()
    report = Report(dry_run=dry_run)

    header = "DRY RUN — " if dry_run else ""
    report.add(f"{header}Zomboid B42 Migration")
    report.add(f"  backup-dir : {backup_dir}")
    report.add(f"  save-dir   : {save_dir}")
    report.add(f"  dry-run    : {dry_run}")

    phase_players(backup_dir, save_dir, report, dry_run)
    phase_vehicles(backup_dir, save_dir, report, dry_run)
    phase_chunks(backup_dir, save_dir, report, dry_run)

    report.section("Summary")
    status = "PASS" if report.overall_pass else "FAIL"
    report.add(f"  Overall: {status}")

    report.write(script_dir)

    if not report.overall_pass:
        sys.exit(1)


if __name__ == "__main__":
    main()
