# media-transcoder (devastator)

Batch-compresses the 4K remux movie library on the Arc Pro B70 (VA-API HEVC
10-bit), reading and writing the nemesis libraries over NFS. Part of the
2026-09 media space-reclaim campaign - see
`docs/superpowers/plans/2026-09-01-plex-media-reclaim.md` for the full
runbook and `scripts/media-reclaim/` for the nemesis-side tooling that
produces the queue.

## How it runs

- The worker (`worker.sh`) only starts encodes inside the windows configured
  in `transcode-policy.conf` (default: nightly 22:30-06:30 daily, plus
  08:30-16:30 Mon-Fri). Outside a window it idles with zero GPU use, so the
  container stays up 24/7 and there are no timers to manage. A running encode
  finishes past window close (bounded by one film, ~1h).
- Queue: `/docker/plex/media/.reclaim/queue/queue.tsv` (NFS-shared),
  generated on nemesis by `scan_candidates.py --emit-queue` after the user
  reviews the candidate report. State (`done.list`, `failed.list`,
  `ledger.tsv`, `status.md`) lives in the same `.reclaim/` dir.
- Per job: encode to local `/scratch`, verify (duration, stream layout,
  size sanity, 3-point decode), move the original into
  `.reclaim/holding/` (last 10 kept per mount), drop the new file in under
  the original filename, chown to plexadm (1001).
- HDR10 color properties are passed through explicitly; Dolby Vision
  enhancement layers do not survive a transcode (HDR10 base remains) - this
  is what the pilot review is for.
- Audio: first English track kept; lossless (TrueHD/DTS-HD/FLAC) becomes
  EAC3 640k, lossy tracks are copied. English subtitles kept.

## Safety gates

- **Pilot gate:** after `PILOT_LIMIT` (3) encodes the worker stops and waits.
  Verify playback + HDR on a real client, then release with:
  `sudo touch /docker/plex/media/.reclaim/PILOT_ACK` (on nemesis).
- **Pause:** `sudo touch /docker/plex/media/.reclaim/PAUSE` (remove to resume).
- **Plex guard:** with `PLEX_TOKEN` set, no new encode starts while Plex has
  active video sessions.
- Keep-list titles never reach the queue (enforced twice on nemesis).

## Deploy (on devastator)

```bash
sudo mkdir -p /docker/transcode-scratch          # local scratch, >=250G free
cd /docker/homelab-config/compute-node/composed-apps/media-transcoder
cp .env.example .env && vi .env                  # optional PLEX_TOKEN/WEBHOOK_URL
sudo docker compose up -d
sudo docker compose logs -f                      # watch device pick + first job
```

Do NOT deploy until the nemesis-side Phase 0/1 steps produced and reviewed a
queue. Restart after config edits = `down` then `up -d` (house rule).

## GPU sharing

Encode/decode uses the B70's fixed-function media engine and little VRAM;
the vLLM stack's memory split is untouched. Single stream only. If vLLM or
Plex hardware transcodes misbehave during encode windows, pause with the
PAUSE file and revisit scheduling.
