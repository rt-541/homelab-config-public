# Plex Media Space Reclaim - Design

**Date:** 2026-09-01
**Status:** APPROVED (user), implementation committed alongside this doc
**Problem:** `/docker/plex/media` at 97% (1.1T free of 33T), `/docker/plex/media2` at 88% (2.0T free of 17T).

## Survey findings (2026-09-01)

- `media/movies` is a wall-to-wall 4K remux library: 230 movies, avg 59.7 GiB,
  13.41 TiB total; 228/230 are 2160p, 223 tagged REMUX. One file per dir.
- `media/tv` 14.01 TiB (7,821 eps; 1,496 eps in 4K = 7.02 TiB). Untouched this
  campaign (user decision) but the survey data stands for a later pass.
- `media/downloads` 4.45 TiB unique bytes; 3,834/10,076 mkvs on media are
  nlink=2 (qbittorrent seed hardlinks) - deleting a library file does not free
  those bytes until the matching torrent+data goes too.
- Instant reclaim: `.Trash-1001` 737.4 GiB (all mtime 2024-10); a 57.6 GiB
  AI-upscaled Dune Part Two misfiled as a TV series; 93 multi-version dirs on
  media2 (~0.5-0.9 TiB); fake-4K upscales (Alien 3, Cowboys & Aliens);
  6 iso / 7 exe in downloads.
- Priority titles verified genuine 2160p BDRemux (EBML headers, HEVC + lossless
  audio): Dune x3, Alien, Aliens, LOTR extended x3, Hobbit extended x3.

## User decisions

1. Keep-list (never touched): Dune (1984/2021/Part Two), Alien (1979),
   Aliens (1986), LOTR extended trilogy, rest of Alien franchise (Covenant,
   Romulus, Resurrection). **Hobbit trilogy not kept - gets compressed.**
2. Everything else stays 4K but compressed: 2160p HEVC, ~15-25G per film.
   Nothing drops to 1080p.
3. TV untouched this pass.
4. Method: **transcode on devastator's Arc Pro B70** (not redownload), running
   in two windows: nightly (22:30-06:30 daily) + work-day (08:30-16:30
   Mon-Fri). Windows are config, not timers.

## Architecture

- **nemesis** `scripts/media-reclaim/`: report-then-execute scripts for
  Phase 0 deletes, the ranked candidate scanner, Radarr guard rails
  (`keep-remux` tag, `Reclaim-NoUpgrade` profile with upgradeAllowed=false),
  and reviewed seed cleanup. Reports in `/docker/plex/logs/media-reclaim/`.
- **devastator** `composed-apps/media-transcoder/`: lscr.io/linuxserver/ffmpeg
  container, `/dev/dri` passthrough, same NFS volume pattern as the plex app,
  local `/scratch`. `worker.sh` self-schedules from `transcode-policy.conf`
  windows; container runs 24/7 and idles outside windows (zero GPU).
- **Shared state** rides the NFS export at `/docker/plex/media/.reclaim/`
  (queue, ledger, done/failed lists, holding dirs, PAUSE / PILOT_ACK
  sentinels) because `/docker/plex/logs` is NOT exported.
- Encode: hevc_vaapi 10-bit, ICQ quality 22 (pilot-tuned), explicit HDR10
  color-property passthrough; DV enhancement layers are lost by design
  (HDR10 base remains). Audio: first English track, lossless -> EAC3 640k,
  lossy copied; English subs kept. Output replaces the original under the
  same filename; original held in `.reclaim/holding/` (last 10 per mount).

## Alternatives considered

- **Redownload via Radarr/Sonarr at lower profiles** (recommended by the
  initial design agent): better quality-per-GB than local VA-API encodes and
  the arr->qbit pipeline is fully wired, but the user chose no-bandwidth
  local transcoding with the idle GPU. The arr protection pieces survive in
  both designs.
- **Tdarr/Unmanic stack**: rejected - heavyweight new service for a one-off
  campaign; a queue file + worker loop is enough and dies cleanly when done.
- **Systemd timers for the windows**: rejected - windows in the worker config
  avoid host units entirely and honor the "compose owns lifecycle" house rule.

## Safety model

- Nothing deletes without a prior `--report` TSV a human can veto (SKIP /
  APPROVE columns). Trash purge and seed deletion are explicit confirm gates.
- nlink + qbittorrent content-path cross-checks before every rm; torrent-owned
  paths are never rm'd directly - they go to the seed-cleanup ledger where
  tracker/ratio is reviewed per torrent (private-tracker ratio protection).
- Transcoder: verify (duration, streams, size sanity, 3-point decode) before
  replacement; rolling holding dir; pilot gate after 3 encodes until
  PILOT_ACK; Plex active-session guard; keep-list enforced at scan AND queue
  emission.
- Radarr can never re-upgrade compressed files (`Reclaim-NoUpgrade`,
  upgradeAllowed=false, assigned from the ledger).
- `move_smallest_50.bash` paused for the campaign (header note).

## Expected outcome

Phase 0 ~1.4-1.7 TiB; transcode wave ~9 TiB on media + ~2 TiB on media2
(after seed-cleanup waves release hardlinked bytes). End state ~media 67% /
media2 ~72%. Timeline ~3-4 weeks of windowed encoding at ~1 movie/hour.
