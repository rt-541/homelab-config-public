# Plex Media Space Reclaim - Campaign Plan

Design: `docs/superpowers/specs/2026-09-01-plex-media-reclaim-design.md`
Tooling: `scripts/media-reclaim/` (nemesis), `compute-node/composed-apps/media-transcoder/`
Reports/checkpoints: `/docker/plex/logs/media-reclaim/`

Targets: media <=80% (stretch ~67%), media2 <=80% (stretch ~72%).
Rule for the whole campaign: `move_smallest_50.bash` is PAUSED.

## Task 1 - Phase 0 instant reclaim (~1.4-1.7 TiB)

- [ ] **Step 1** `phase0_instant_reclaim.sh preflight` - arr configs + quality
      profiles backed up, versions logged, recycleBin EMPTY/unset confirmed
      (if set: resolve before ANY delete), qbit reachability known.
- [x] **Step 2** DONE 2026-09-01. `trash --report` -> user chose "save what
      isn't in Plex, delete the rest". Restored Counterpart S01E01-09 + S02E01
      (52 GiB real) into `media/tv/Counterpart/`; all Poirot and Cabinet of
      Curiosities trash copies were HOLLOW (sparse shells, data destroyed
      pre-trash) - nothing to save, gone for good. Purged the rest. The 737G
      figure was APPARENT size; real allocation was ~387G. Actually freed
      ~335 GiB (media 1041 -> 1375 GiB free, 96%).
- [ ] **Step 3** `junk --report` / `--execute` (iso/exe in downloads).
- [ ] **Step 4** `phase0_arr.py dune-dupe --report` / `--execute`; then Plex
      TV-section scan + empty trash (devastator) - phantom "Dune" series gone.
- [ ] **Step 5** `phase0_arr.py fake4k --report` / `--execute` (Cowboys &
      Aliens 1080p regrab; Alien 3 decision recorded, keep-list otherwise).
- [ ] **Step 6** `prune_multiversion.py --report`, user reviews/edits SKIP,
      `--execute`. Post-condition: media2 free >=2.5T.

Rollback notes: trash/junk/prune rm of nlink=1 files is irreversible (user
gate before each). nlink=2 deletes are recoverable from the seed copy until
Task 4 removes it.

## Task 2 - Phase 1 candidates + guard rails

- [ ] **Step 1** `scan_candidates.py`; review `report.md` (keep-list
      verification MUST show a match for every pattern) + edit SKIP column.
- [ ] **Step 2** `arr_protect.py --tag-keeps` then `--make-profile`.
- [ ] **Step 3** `scan_candidates.py --emit-queue <reviewed candidates tsv>` -
      queue lands in `/docker/plex/media/.reclaim/queue/queue.tsv`.

## Task 3 - Phase 2 B70 transcode campaign (~9 TiB media, ~2 TiB media2)

- [ ] **Step 1** On devastator: `mkdir /docker/transcode-scratch`, optional
      `.env` (PLEX_TOKEN, WEBHOOK_URL), `sudo docker compose up -d` in
      `compute-node/composed-apps/media-transcoder/`. Verify log shows a working
      VA-API device and window state.
- [ ] **Step 2** PILOT GATE: after 3 encodes the worker halts. Verify on a
      real client: playback, HDR10 present (ffprobe color_transfer=smpte2084),
      audio/subs correct, size in the 15-25G band. Tune VIDEO_QUALITY if
      needed (restart = down/up). Release: `sudo touch
      /docker/plex/media/.reclaim/PILOT_ACK`.
- [ ] **Step 3** Bulk run inside windows (nightly 22:30-06:30 daily; work-day
      08:30-16:30 Mon-Fri). Monitor `/docker/plex/media/.reclaim/status.md`,
      `failed.list`, df checkpoints. Weekly: `arr_protect.py
      --assign-from-ledger` so Radarr never re-upgrades compressed titles.
- [ ] **Step 4** Failed/no-gain titles reviewed at end; leave as-is or handle
      manually (they are simply not replaced - originals intact).

## Task 4 - Phase 3 seed-cleanup waves (frees hardlinked bytes)

- [ ] **Step 1** Every ~25 transcodes: `cleanup_seeds.py --report`, review
      tracker/ratio per torrent, set APPROVE=yes, `--execute`.
- [ ] **Step 2** Plex movie-section scan + empty trash after each wave.

## Task 5 - Campaign close-out

- [ ] **Step 1** Final df checkpoint vs targets; append summary here.
- [ ] **Step 2** Keep-list untouched check: size+mtime of every keep-list file
      unchanged vs the Phase 1 scan.
- [ ] **Step 3** Decide transcoder future: `docker compose down` + leave
      committed, or keep for a TV pass (separate decision).
- [ ] **Step 4** Un-pause `move_smallest_50.bash` (remove header note) if
      rebalancing is still wanted at the new fill levels.
- [ ] **Step 5** Review `orphans_downloads.tsv` (~3.7 TiB candidate, needs
      qbit cross-check) - separate mini-campaign if pursued.

## Findings / decisions log

- 2026-09-01: user confirmed keep-list (core + Alien franchise, NO Hobbit),
  compressed-4K target for all others, TV untouched, B70 transcode method,
  nightly + work-day windows.
- 2026-09-01: trash purge revealed HOLLOW FILES - much of `.Trash-1001` was
  sparse shells (apparent size >> allocated; middles read as zeros; likely
  failed/partial grabs trashed in 2024-10). Tooling now measures allocation:
  scanner flags `SPARSE`, `sparse-review` action, queue emission refuses
  hollow files, orphan report shows apparent vs allocated. Library movie scan
  after the fix: 0 sparse - the 10.5 TiB transcode estimate is real data.
  Remaining downloads orphans: 3822 GiB apparent / 3786 GiB allocated.
- 2026-09-01: Counterpart restored to `media/tv/` is NOT in Sonarr (add the
  series later to fetch S01E10 + rest of S02 if wanted); Plex sees it on next
  TV-section scan. Poirot / Cabinet of Curiosities need full redownloads if
  ever wanted again.

## Post-conditions

- media <=80% used, media2 <=80% used, all non-keep movies 2160p HEVC in the
  15-25G band, keep-list byte-identical, Radarr profiles prevent re-upgrades,
  no orphaned seeds for replaced files (approved rows only).
