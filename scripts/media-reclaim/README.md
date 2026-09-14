# media-reclaim toolkit (nemesis)

Campaign tooling to take `/docker/plex/media` from 97% full to ~67% by
compressing the 4K remux movie library on devastator's B70 and clearing
no-quality-loss junk first. Full plan:
`docs/superpowers/plans/2026-09-01-plex-media-reclaim.md`.

Every destructive step is split into `--report` (writes a reviewable TSV,
changes nothing) and `--execute` (acts on the reviewed TSV). Reports land in
`/docker/plex/logs/media-reclaim/`; shared machine state (queue, ledger,
holding) lives in `/docker/plex/media/.reclaim/` so the devastator
transcoder can reach it over NFS. Needs passwordless sudo (media mounts are
plexadm 0770). Copy `.env.example` to `.env` for the qbittorrent safety
cross-checks.

## Scripts

| Script | Purpose |
|---|---|
| `phase0_instant_reclaim.sh` | `preflight` checks/backups; `trash` (737G stale `.Trash-1001`); `junk` (iso/exe in downloads) |
| `phase0_arr.py` | `dune-dupe` (phantom Dune TV series, 57.6G AI upscale); `fake4k` (Cowboys & Aliens regrab) |
| `prune_multiversion.py` | media2 dirs with 2+ versions (~93 dirs): keep best, delete extras via Radarr/rm |
| `scan_candidates.py` | ranked candidate report; `--emit-queue` builds the transcoder queue from the reviewed TSV |
| `arr_protect.py` | `keep-remux` tag, `Reclaim-NoUpgrade` profile, move transcoded movies onto it |
| `cleanup_seeds.py` | per-torrent review sheet for old seed data; APPROVE=yes rows deleted with data |
| `qbit_check.py` | helper: which torrent owns a path (used by the shell scripts) |
| `keep-list.conf` | titles never touched (Dune / Alien franchise / LOTR extended) |
| `policy.conf` | thresholds and size-estimate knobs |

## Campaign order (summary)

```bash
cd /docker/homelab-config/scripts/media-reclaim

# Phase 0 - instant reclaim (about 1.4-1.7 TiB, no quality loss)
./phase0_instant_reclaim.sh preflight
./phase0_instant_reclaim.sh trash --report     # review, then:
./phase0_instant_reclaim.sh trash --execute
./phase0_instant_reclaim.sh junk --report && ./phase0_instant_reclaim.sh junk --execute
./phase0_arr.py dune-dupe --report && ./phase0_arr.py dune-dupe --execute
./phase0_arr.py fake4k --report && ./phase0_arr.py fake4k --execute
./prune_multiversion.py --report               # review/edit SKIP, then:
./prune_multiversion.py --execute

# Phase 1 - candidates + protection
./scan_candidates.py                           # review report + TSV, edit SKIP col
./arr_protect.py --tag-keeps && ./arr_protect.py --make-profile
./scan_candidates.py --emit-queue /docker/plex/logs/media-reclaim/<stamp>/candidates_movies.tsv

# Phase 2 - deploy the transcoder on devastator (see its README); pilot gate
# after 3 encodes: verify playback, then sudo touch /docker/plex/media/.reclaim/PILOT_ACK
# Periodically: ./arr_protect.py --assign-from-ledger

# Phase 3 - seed cleanup waves (frees hardlinked bytes)
./cleanup_seeds.py --report                    # set APPROVE=yes per row, then:
./cleanup_seeds.py --execute
```

After each phase: Plex section scan + empty trash (on devastator), and check
`/docker/plex/logs/media-reclaim/df-checkpoints.log`.

While the campaign runs, `move_smallest_50.bash` is paused (see its header).
