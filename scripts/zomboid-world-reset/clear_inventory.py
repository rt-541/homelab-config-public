#!/usr/bin/env python3
"""
clear_inventory.py -- strip the inventory section from PZ player blobs.

Usage:
    sudo python3 clear_inventory.py --save-dir <path-to-server-save-dir> [--dry-run] [--players USER ...]

Reads players.db, strips the inventory section from each player's data blob,
and writes back. Snapshots the original blobs to ./blob-backups/ before mutating.

Heuristic: scan the blob for the first module-prefixed item ID (e.g. Base.HuntingKnife)
after known false-positive recipe sentinel strings. Truncate at that position, leaving
the character identity section (name, gender, profession, skills) intact.

Position metadata is NOT touched. Post-login RCON teleport handles spawn location.
"""

# Blob format analysis (from hexdump of B42.15 player exports, 2026-05-08)
# =========================================================================
#
# Offset 0x00: header bytes (stats, skills, fitness/strength timers, passive skill
#              XP log, per-skill XP floats, kills log, "Fav:" weapon bindings)
#
# Within the header the following fields embed module-prefixed item IDs that look
# like inventory references but are NOT inventory items:
#
#   "handcraftLastRecipe" <Base.RecipeName>   -- last recipe the player crafted
#   "buildLastRecipe"     <Base.RecipeName>   -- last build recipe used
#
# These are FALSE POSITIVES for the item-ID scan. They appear at varying offsets
# depending on how many skills the character has:
#   Curtis:      handcraftLastRecipe at 0x00D3, Base.DisinfectRag at 0x00E8 (248)
#   Bulbs:       handcraftLastRecipe at 0x0239, Base.RipSheets at 0x0252 (594)
#   Vinny:       handcraftLastRecipe at 0x0283, Base.OpenCannedFood at 0x029D (669)
#   Artie:       handcraftLastRecipe at 0x0383, Base.RipClothing at 0x0399 (921)
#                buildLastRecipe at 0x0400, Base.BarricadePlanks at 0x0411 (1041)
#   Emma_M7:     handcraftLastRecipe at 0x0322, Base.PlaceInBox at 0x0338 (824)
#                buildLastRecipe at 0x0380, Base.FeedingTroughSimple at 0x0395 (917)
#
# After the header, a short identity block encodes: first name, last name, gender
# string ("Male"/"Female"), and profession string (e.g. "base:parkranger").
#
# The first REAL inventory item (clothing, weapons, bags) appears AFTER the
# identity block. Confirmed first-item offsets across 8 blobs:
#   Curtis:      0x0234 (564)    -- Base.Socks_Long
#   Bulbs:       0x03A2 (930)    -- Base.Shirt_FormalTINT
#   Vinny:       0x0447 (1095)   -- Base.Belt2
#   Artie:       0x055B (1371)   -- Base.Necklace_Gold
#   Emma_M7:     0x058E (1422)   -- Base.Key1
#   bleedfuel:   0x04BB (1211)   -- Base.Tshirt_WhiteLongSleeveTINT
#   KnobleOutlaw: 0x02A6 (678)   -- Base.Belt2
#   Artie1:      0x024D (589)    -- Base.Belt2
#
# HEURISTIC (sentinel-skip approach):
# ------------------------------------
# 1. Locate every occurrence of the sentinel strings "handcraftLastRecipe" and
#    "buildLastRecipe" in the blob.
# 2. For each sentinel, find the Base.X item-ID string that immediately follows it
#    and mark that range as a skip zone (the whole sentinel..end-of-item-id span).
# 3. Scan the blob for the first module-prefixed item-ID string that does NOT fall
#    inside any skip zone. Truncate at that position.
#
# As a safety floor, scanning never starts before MIN_SCAN_OFFSET bytes. This
# protects against degenerate blobs (e.g., a brand-new character with no craft
# history whose first item might appear very early).
#
# MIN_SCAN_OFFSET = 200 is conservative: the absolute earliest any real inventory
# item appeared across all 8 analyzed blobs was 564 bytes. 200 leaves a wide
# margin below that, ensuring we do not accidentally truncate into the stats header
# while still being a meaningful lower bound.

import argparse
import re
import sqlite3
import sys
from pathlib import Path

# Minimum byte offset before scanning for an item ID. Provides a safety floor for
# blobs with no craft-history sentinels (e.g., a new character who never crafted).
# The earliest first-item offset observed across 8 real blobs was 564 bytes;
# 200 is comfortably below that, guarding only against scanning the very beginning.
MIN_SCAN_OFFSET = 200

# PZ stores player blobs in this table, not "players".
PLAYER_TABLE = "networkPlayers"

# Module ID pattern: bytes spelling "<Module>.<ItemName>" where Module starts with
# a capital letter. Matches Base.HuntingKnife, Base.Necklace_Gold, etc.
ITEM_ID_PATTERN = re.compile(rb'[A-Z][A-Za-z0-9_]+\.[A-Za-z][A-Za-z0-9_]+')

# Fields in the identity/stats section that embed a Base.X recipe reference.
# These are FALSE POSITIVES -- not inventory items. We skip the Base.X value that
# immediately follows each sentinel.
RECIPE_SENTINELS = [b'handcraftLastRecipe', b'buildLastRecipe']


def _build_skip_zones(blob: bytes) -> list:
    """Return list of (start, end) byte ranges covering sentinel-embedded Base.X
    recipe references. Matches inside these ranges are not inventory item boundaries."""
    skip_zones = []
    for sentinel in RECIPE_SENTINELS:
        pos = 0
        while True:
            idx = blob.find(sentinel, pos)
            if idx < 0:
                break
            # The Base.X recipe name follows the sentinel (possibly with a few
            # length-prefix bytes between them). Search a generous window ahead.
            m = ITEM_ID_PATTERN.search(blob, idx, idx + len(sentinel) + 64)
            if m:
                skip_zones.append((idx, m.end()))
            pos = idx + 1
    return skip_zones


def strip_inventory(blob: bytes) -> bytes:
    """Truncate blob at the first module-prefixed item ID that is not a
    recipe-sentinel false positive, searching only after MIN_SCAN_OFFSET.

    Returns the original blob unchanged if no inventory boundary is found."""
    if len(blob) <= MIN_SCAN_OFFSET:
        return blob

    skip_zones = _build_skip_zones(blob)

    def in_skip_zone(pos):
        return any(start <= pos < end for start, end in skip_zones)

    pos = MIN_SCAN_OFFSET
    while True:
        m = ITEM_ID_PATTERN.search(blob, pos)
        if m is None:
            # No item ID found -- nothing to strip.
            return blob
        if not in_skip_zone(m.start()):
            # First real inventory item found; truncate here.
            return blob[: m.start()]
        # This match is a false positive; advance past it.
        pos = m.end()


def main():
    parser = argparse.ArgumentParser(
        description='Strip inventory section from PZ player blobs in players.db.'
    )
    parser.add_argument(
        '--save-dir', required=True,
        help='path to save dir containing players.db'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='report changes without writing'
    )
    parser.add_argument(
        '--players', nargs='+',
        help='only process these usernames (default: all)'
    )
    args = parser.parse_args()

    db_path = Path(args.save_dir) / 'players.db'
    if not db_path.exists():
        print('ERROR: players.db not found at {}'.format(db_path), file=sys.stderr)
        sys.exit(1)

    backup_dir = Path(__file__).parent / 'blob-backups'
    if not args.dry_run:
        backup_dir.mkdir(exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute(f'SELECT username, data FROM {PLAYER_TABLE}').fetchall()

    changed = 0
    for username, blob in rows:
        if args.players and username not in args.players:
            continue
        original_size = len(blob)
        backup_path = backup_dir / '{}_prestrip.blob'.format(username)
        if not args.dry_run:
            backup_path.write_bytes(blob)
        new_blob = strip_inventory(blob)
        new_size = len(new_blob)
        delta = original_size - new_size
        if args.dry_run:
            status = 'DRY-RUN'
        elif delta == 0:
            status = 'UNCHANGED'
        else:
            status = 'STRIPPED'
            changed += 1
        suffix = ''
        if not args.dry_run:
            suffix = ' | snapshot: {}'.format(backup_path.name)
        print('  {} {}: {} -> {} bytes (removed {}{})'.format(
            status, username, original_size, new_size, delta, suffix
        ))
        if not args.dry_run and delta > 0:
            cur.execute(
                f'UPDATE {PLAYER_TABLE} SET data=? WHERE username=?',
                (new_blob, username)
            )

    if not args.dry_run:
        conn.commit()
    conn.close()
    if not args.dry_run:
        print('done ({} player(s) modified)'.format(changed))
    else:
        print('dry-run complete (no changes written)')


if __name__ == '__main__':
    main()
