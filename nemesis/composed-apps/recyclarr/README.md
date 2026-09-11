# Recyclarr - plex-ops prevention layer

Syncs TRaSH-guides custom formats and quality-profile settings into the live
Sonarr and Radarr, so the junk classes the plex-ops agent keeps triaging out of
the queue stop getting grabbed in the first place. Design:
`docs/superpowers/specs/2026-09-10-plex-ops-agents-design.md` (Prevention
section).

Recyclarr is the ONE sanctioned writer to the arr APIs in this suite - and it
only writes what `recyclarr.yml` declares. Everything else (the plex-ops
runner, probes) is read-only.

## Layout

| File | Purpose |
|---|---|
| `docker-compose.yml` | Cron-mode container on the `proxy` network (same network as plex-stack, so `http://sonarr:8989` / `http://radarr:7878` resolve by container name) |
| `recyclarr.yml` | The synced config - in-repo source of truth, mounted read-only into the container |
| `.env.example` | Template for `.env` (API keys; `.env` itself is gitignored) |
| `/docker/recyclarr/` | Container state on the host (recyclarr cache/logs) |

## First run

1. Create the state dir, owned like the rest of the arr stack (PUID 1001):

   ```
   sudo mkdir -p /docker/recyclarr
   sudo chown 1001:1001 /docker/recyclarr
   ```

2. `cp .env.example .env` and fill in the two API keys. They live on-host in
   `/docker/sonarr/config.xml` and `/docker/radarr/config.xml` (the
   `<ApiKey>` element).

3. **Preview before anything touches the live arrs** - this prints every
   custom format and profile change without applying it:

   ```
   cd /docker/homelab-config/nemesis/composed-apps/recyclarr
   sudo docker compose run --rm recyclarr sync --preview
   ```

   Expected on a clean first preview: ~10 new custom formats per app (both
   arrs had zero pre-existing CFs as of 2026-09-10), score assignments of
   -10000 to the profiles below, and the Sonarr cutoff change.

4. When the preview looks right, apply once interactively, then leave the
   container running for the daily cron sync:

   ```
   sudo docker compose run --rm recyclarr sync
   sudo docker compose up -d
   ```

   Cadence is `CRON_SCHEDULE` (default daily 06:00 America/Detroit).

## What each block prevents

Mapped to the junk classes from the 2026-09-10 queue audit (137 Sonarr queue
items, 96 stuck):

| CF group in `recyclarr.yml` | Custom formats | Junk class it blocks |
|---|---|---|
| Malware-prone / no-name release groups | LQ, LQ (Release Title), No-RlsGroup, Obfuscated, Retags | The `malware-ext` class: `.exe`/`.scr`/`.rar`/`.lnk`/`.zipx` payload releases, which ride on low-quality-group, groupless, obfuscated, or retagged uploads |
| Upscaled / junk-encode releases | Upscaled, AV1, BR-DISK, Extras | Fake 4K / AI upscales, AV1 re-encodes the players choke on, raw disk dumps, and extras mislabeled as episodes (hollow-file bait) |
| Wrong-language releases | Language: Not Original | Wrong-language grabs. "Not Original" (not "Not English") on purpose: foreign-original titles tracked deliberately stay grabbable in their native audio |
| `quality_profiles` section | - | The `not-upgrade` re-grab churn: Sonarr's in-use profile upgraded "until HDTV-2160p", endlessly chasing 2160p over good 1080p - now capped at the `WEB 1080p` group. Radarr's profile has upgrades off; the config pins that so it cannot drift |

How the blocking works: each format carries the TRaSH default score of
-10000, and the profiles set `min_format_score: 0`. A release matching any
format therefore scores below the minimum and is rejected at grab/RSS time -
it never enters the queue, so the triage agent never sees it.

Scores are synced to the two in-use profiles per app (Sonarr
`"HD - 720p/1080p + "` with 330 series, Radarr `"HD-1080p + "` with 1053
movies) plus each app's small `Any` profile. **The in-use profile names
contain real trailing spaces** - if you rename profiles in the arr UIs,
update `recyclarr.yml` to match exactly or the sync will fail to find them.

## Tuning scores

Scores are omitted in `recyclarr.yml`, so every format uses the TRaSH default
(-10000, a hard block given `min_format_score: 0`). To soften one from block
to preference - e.g. allow AV1 as a last resort instead of banning it - set an
explicit score on that profile assignment:

```yaml
- trash_ids:
    - 15a05bc7c1a36e2b57fd628f8977e2fc # AV1
  assign_scores_to:
    - name: "HD - 720p/1080p + "
      score: -100   # preference, not a block: no longer below min_format_score
```

Rules of thumb:

- `score <= -10000` (or anything below `min_format_score`): hard block.
- Small negative (-100 .. -25): allowed, but loses to any clean release.
- Removing a trash_id from the list deletes the format from the arr on the
  next sync (`delete_old_custom_formats: true`) - that is intended; this file
  owns the CF namespace since both arrs started with zero custom formats.
- After any edit: `sudo docker compose run --rm recyclarr sync --preview`
  first, then "restart" the cron container the compose way
  (`sudo docker compose down && sudo docker compose up -d`) - the config is
  mounted read-only from the repo, so the running container picks it up on
  its next scheduled sync anyway.

Browse available formats and their canonical IDs:
`sudo docker compose run --rm recyclarr list custom-formats sonarr` (or
`radarr`).
