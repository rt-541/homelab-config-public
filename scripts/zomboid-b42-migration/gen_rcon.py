#!/usr/bin/env python3
"""
gen_rcon.py — Generate RCON command files for manual B42 player/vehicle restoration.

This is the fallback path when the DB transplant (migrate.py) cannot be used.
It reads .txt player exports and a vehicles SQL backup, then writes:
  - One .rcon file per player with /grantxp and /additem commands
  - vehicles_lost.txt listing vehicle IDs and tile coordinates (reference only)

Usage:
    sudo python3 gen_rcon.py \\
        --export-dir /docker/game/zomboid/manual-backups/player-exports \\
        --vehicles-sql /docker/game/zomboid/manual-backups/firestation-chunk-backup/vehicles_base.sql \\
        --output-dir ./rcon-output
"""

import argparse
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNOWN_SKILLS = {
    "Strength", "Fitness", "Sprinting", "Lightfoot", "Nimble", "Sneak",
    "Axe", "Blunt", "SmallBlunt", "LongBlade", "SmallBlade", "Spear",
    "Maintenance", "Aiming", "Reloading", "Carpentry", "Cooking", "Farming",
    "FirstAid", "Electrical", "Mechanics", "MetalWelding", "Tailoring",
    "Doctor", "Woodwork", "Electricity", "Metalwork", "PlantScavenging",
    "Husbandry", "Carving", "Trapping", "Fishing",
}

# Matches lines like:
#   "  Woodwork              Level  6  (21283.9 xp)"
#   "  Strength              Level  0  (10.0 xp)"
SKILL_LINE_RE = re.compile(
    r"^\s{2}(\S+)\s+Level\s+\d+\s+\(([0-9]+(?:\.[0-9]+)?)\s+xp\)\s*$"
)

# Matches lines like:
#   "  Base.AmmoStrap_Shells"
#   "  Farming.Soil"
ITEM_LINE_RE = re.compile(r"^\s{2}(\S+)\s*$")

# Module.ItemName validation — at least one alphanumeric char in each part
ITEM_ID_RE = re.compile(r"^[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")

# Matches INSERT OR REPLACE INTO vehicles (...) VALUES (...)
# We only need the VALUES clause; columns are: id, wx, wy, x, y, worldversion, data
VEHICLE_INSERT_RE = re.compile(
    r"INSERT\s+OR\s+REPLACE\s+INTO\s+vehicles\s*\([^)]+\)\s*VALUES\s*\(([^)]+)\)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def warn(msg: str) -> None:
    """Print a warning to stderr with a WARNING: prefix."""
    print(f"WARNING: {msg}", file=sys.stderr)


def info(msg: str) -> None:
    """Print an informational message to stdout."""
    print(msg)


# ---------------------------------------------------------------------------
# Player export parsing
# ---------------------------------------------------------------------------

def parse_export_file(txt_path: Path) -> tuple[list[str], list[str]]:
    """
    Parse a player .txt export file.

    Returns (skill_commands, item_commands) where each element is a list of
    RCON command strings (without the leading username — caller supplies that).

    Each element is a bare string like:
        "SkillName=XP"     (for skills)
        "Module.ItemName"  (for items)

    The caller formats these into /grantxp and /additem commands.

    Raises ValueError if the file is empty.
    """
    raw = txt_path.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError("empty file")

    lines = raw.splitlines()

    # State machine: track which section we are in
    section = None  # None | "skills" | "inventory"

    skills: list[tuple[str, str]] = []   # (skill_name, xp_str)
    items: list[str] = []

    for lineno, line in enumerate(lines, start=1):
        stripped = line.rstrip()

        if stripped.strip() == "SKILLS":
            section = "skills"
            continue
        if stripped.strip().startswith("INVENTORY"):
            section = "inventory"
            continue
        if stripped.strip().startswith("---"):
            # Separator line — skip
            continue
        if stripped.strip().startswith("=="):
            # Header separator — skip
            continue
        if stripped.strip().startswith("Player:"):
            # Header line — skip
            continue
        if not stripped.strip():
            # Blank line — ignore
            continue

        if section == "skills":
            m = SKILL_LINE_RE.match(stripped)
            if m:
                skill_name = m.group(1)
                xp_str = m.group(2)
                xp_val = float(xp_str)

                if skill_name not in KNOWN_SKILLS:
                    warn(
                        f"{txt_path.name}:{lineno}: unknown skill name '{skill_name}', skipping"
                    )
                    continue

                if xp_val > 0:
                    skills.append((skill_name, xp_str))
            else:
                warn(
                    f"{txt_path.name}:{lineno}: malformed skill line, skipping: {stripped!r}"
                )

        elif section == "inventory":
            m = ITEM_LINE_RE.match(stripped)
            if m:
                item_id = m.group(1)
                if not ITEM_ID_RE.match(item_id):
                    warn(
                        f"{txt_path.name}:{lineno}: item ID '{item_id}' does not match"
                        f" Module.ItemName format, skipping"
                    )
                    continue
                items.append(item_id)
            else:
                warn(
                    f"{txt_path.name}:{lineno}: malformed inventory line, skipping: {stripped!r}"
                )

        # Lines outside both sections are silently ignored (e.g., blank header lines)

    return skills, items


def write_player_rcon(
    username: str,
    skills: list[tuple[str, str]],
    items: list[str],
    out_path: Path,
) -> None:
    """Write a .rcon file for one player."""
    lines: list[str] = [
        f"# RCON commands for {username} — generated by gen_rcon.py",
        "# Paste into server console or pipe through RCON client",
        "",
    ]

    if skills:
        lines.append("# --- Skills ---")
        for skill_name, xp_str in skills:
            lines.append(f"/grantxp {username} {skill_name}={xp_str}")
        lines.append("")

    if items:
        lines.append("# --- Inventory ---")
        for item_id in items:
            lines.append(f"/additem {username} {item_id}")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def process_players(export_dir: Path, output_dir: Path) -> None:
    """
    Iterate over all .txt files in export_dir and generate .rcon files.
    """
    txt_files = sorted(export_dir.glob("*.txt"))

    if not txt_files:
        warn(f"No .txt files found in {export_dir}")
        return

    for txt_path in txt_files:
        username = txt_path.stem
        out_path = output_dir / f"{username}.rcon"

        info(f"Processing player: {username} ({txt_path.name})")

        if not txt_path.exists():
            warn(f"{txt_path.name}: file not found, skipping")
            continue

        try:
            skills, items = parse_export_file(txt_path)
        except ValueError as exc:
            warn(f"{txt_path.name}: {exc} — writing empty .rcon with note")
            out_path.write_text(
                f"# RCON commands for {username} — generated by gen_rcon.py\n"
                "# Paste into server console or pipe through RCON client\n"
                f"\n# NOTE: source file was empty or unreadable ({exc})\n",
                encoding="utf-8",
            )
            continue

        skill_count = len(skills)
        item_count = len(items)
        info(f"  Skills with XP > 0: {skill_count}, inventory items: {item_count}")

        write_player_rcon(username, skills, items, out_path)
        info(f"  Written: {out_path}")


# ---------------------------------------------------------------------------
# Vehicle SQL parsing
# ---------------------------------------------------------------------------

def parse_vehicles_sql(sql_path: Path) -> list[tuple[str, str, str]]:
    """
    Parse a vehicles SQL file and extract (id, x, y) tuples.

    The INSERT format is:
        INSERT OR REPLACE INTO vehicles (id, wx, wy, x, y, worldversion, data)
        VALUES (<id>, <wx>, <wy>, <x>, <y>, <worldversion>, <data>)

    Column positions (0-indexed): id=0, wx=1, wy=2, x=3, y=4
    """
    sql_text = sql_path.read_text(encoding="utf-8", errors="replace")
    vehicles: list[tuple[str, str, str]] = []

    for m in VEHICLE_INSERT_RE.finditer(sql_text):
        values_str = m.group(1)
        # Split on commas but only at the top level (the data blob may contain
        # hex literals with no commas, but the VALUES clause ends at the first
        # unmatched ')' which the regex already handles via [^)]+).
        # The first 5 fields are plain integers/floats; split carefully.
        parts = [p.strip() for p in values_str.split(",")]
        if len(parts) < 5:
            warn(f"vehicles SQL: could not parse VALUES clause: {values_str[:80]!r}")
            continue
        vid = parts[0]
        x = parts[3]
        y = parts[4]
        vehicles.append((vid, x, y))

    return vehicles


def write_vehicles_lost(
    vehicles: list[tuple[str, str, str]], output_dir: Path
) -> None:
    """Write vehicles_lost.txt listing each vehicle and its tile coordinates."""
    out_path = output_dir / "vehicles_lost.txt"
    lines: list[str] = [
        "# Vehicles lost in migration — reference only",
        "# Vehicles are NOT recoverable via RCON; use sqlite3 to restore from backup",
        "",
    ]
    for vid, x, y in vehicles:
        lines.append(f"Vehicle ID: {vid}  Tile: ({x}, {y})")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    info(f"Written: {out_path} ({len(vehicles)} vehicles)")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate RCON command files for manual B42 player/vehicle restoration. "
            "Reads .txt player exports and a vehicles SQL backup; writes .rcon files "
            "and vehicles_lost.txt to --output-dir."
        )
    )
    parser.add_argument(
        "--export-dir",
        required=True,
        type=Path,
        metavar="DIR",
        help="Directory containing player .txt export files",
    )
    parser.add_argument(
        "--vehicles-sql",
        required=True,
        type=Path,
        metavar="FILE",
        help="Path to vehicles_base.sql backup file",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        metavar="DIR",
        help="Output directory for .rcon files and vehicles_lost.txt (created if missing)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Validate inputs
    if not args.export_dir.is_dir():
        print(f"ERROR: export-dir does not exist or is not a directory: {args.export_dir}", file=sys.stderr)
        sys.exit(1)

    if not args.vehicles_sql.is_file():
        print(f"ERROR: vehicles-sql does not exist or is not a file: {args.vehicles_sql}", file=sys.stderr)
        sys.exit(1)

    # Create output directory if needed
    args.output_dir.mkdir(parents=True, exist_ok=True)
    info(f"Output directory: {args.output_dir}")

    # Process players
    info("")
    info("=== Processing player exports ===")
    process_players(args.export_dir, args.output_dir)

    # Process vehicles
    info("")
    info("=== Processing vehicles SQL ===")
    info(f"Parsing: {args.vehicles_sql}")
    vehicles = parse_vehicles_sql(args.vehicles_sql)
    info(f"Found {len(vehicles)} vehicle records")
    write_vehicles_lost(vehicles, args.output_dir)

    info("")
    info("Done.")


if __name__ == "__main__":
    main()
