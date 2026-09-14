#!/usr/bin/env bash
#
# fix-compose-env.sh — Convert docker-compose environment sections
# from shell-wrapped list form to YAML map form.
#
# Converts:
#   environment:
#     - "KEY=value"        →  environment:
#     - KEY=${VAR}              KEY: value
#                               KEY: ${VAR}
#
# Usage:
#   ./scripts/fix-compose-env.sh              # dry run (show changes)
#   ./scripts/fix-compose-env.sh --apply      # apply changes
#
# Skips files that already use YAML map form.

set -euo pipefail

COMPOSE_DIR="/docker/homelab-config/data-host/composed-apps"
DRY_RUN=true

if [[ "${1:-}" == "--apply" ]]; then
  DRY_RUN=false
fi

echo "Mode: $(if $DRY_RUN; then echo 'DRY RUN (use --apply to write changes)'; else echo 'APPLYING CHANGES'; fi)"
echo ""

for file in "$COMPOSE_DIR"/*/docker-compose.{yml,yaml}; do
  [[ -f "$file" ]] || continue

  # Skip if no list-style env vars
  if ! grep -qP '^\s+-\s+"?[A-Za-z_][A-Za-z0-9_]*=' "$file" 2>/dev/null; then
    continue
  fi

  relpath="${file#$COMPOSE_DIR/}"
  echo "=== $relpath ==="

  python3 - "$file" "$DRY_RUN" << 'PYEOF'
import sys
import re

infile = sys.argv[1]
dry_run = sys.argv[2] == "True"

with open(infile, 'r') as f:
    lines = f.readlines()

output = []
i = 0
changes = 0

while i < len(lines):
    line = lines[i]

    if re.match(r'^(\s*)environment:\s*$', line):
        output.append(line)
        i += 1

        while i < len(lines):
            entry = lines[i]

            # Match: - "KEY=val", - 'KEY=val', or - KEY=val
            m = re.match(r'^(\s*)-\s+["\']?([A-Za-z_][A-Za-z0-9_]*)=(.*?)["\']?\s*$', entry)
            if m:
                entry_indent = m.group(1)
                key = m.group(2)
                val = m.group(3).rstrip('"').rstrip("'")

                if val == '':
                    new_line = f"{entry_indent}  {key}:\n"
                elif val.startswith('\\') or re.search(r'[:{}\[\],&*#?|<>=!%@`]', val):
                    new_line = f'{entry_indent}  {key}: "{val}"\n'
                else:
                    new_line = f"{entry_indent}  {key}: {val}\n"

                if entry.rstrip() != new_line.rstrip():
                    if dry_run:
                        print(f"  - {entry.rstrip()}")
                        print(f"  + {new_line.rstrip()}")
                    changes += 1

                output.append(new_line)
                i += 1
            elif re.match(r'^\s*#', entry):
                output.append(entry)
                i += 1
            else:
                break
    else:
        output.append(line)
        i += 1

if dry_run:
    if changes == 0:
        print("  (no changes needed)")
    else:
        print(f"  {changes} line(s) to convert")
else:
    with open(infile, 'w') as f:
        f.writelines(output)
    print(f"  {changes} line(s) converted")

PYEOF

done

echo ""
echo "Done."