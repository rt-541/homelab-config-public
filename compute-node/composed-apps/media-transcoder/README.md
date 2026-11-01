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
- Per job:
  1. Encode video + the chosen audio track only (hevc_vaapi, ICQ
     `VIDEO_QUALITY`) into `SCRATCH` (`.reclaim/scratch/` on the NFS share).
  2. Copy-only remux that adds the English subtitles from the source. They
     are kept out of the encode on purpose: in ffmpeg 9 a sparse copied PGS
     track in the same run as a re-encoded audio track starves the audio,
     which then silently ends (exit 0) at the start or mid-film.
  3. Verify the whole film (`verify_encode`): one read counts audio and video
     packets per `VERIFY_STEP` (300 s) block, and a 4 s clip from the middle
     of every block must decode and score >= `VMAF_FAIL` (60) against the
     source (clips under `VMAF_WARN`, 85, are listed in the log; every score
     lands in `.reclaim/qc-vmaf.tsv`). Length is judged by the video stream,
     and clips are aligned by stream start time.
  4. Only on a full pass: the new file replaces the original under the same
     filename (chown plexadm 1001), the original is deleted
     (`PURGE_ON_PASS=true`; `false` keeps the last `HOLD_COUNT` in
     `.reclaim/holding/`), and Plex rescans the folder (`PLEX_SECTION`).
     Any failure keeps the original and records the reason in `failed.list`.
- HDR10 color properties are passed through explicitly; Dolby Vision
  enhancement layers do not survive a transcode (HDR10 base remains) - this
  is what the pilot review is for.
- Audio: first English track kept; lossless (TrueHD/DTS-HD/FLAC) becomes
  EAC3 640k, lossy tracks are copied. English subtitles kept.
- Test a change without touching the library: `CLIP_SECS=N` encodes and
  verifies only the first N seconds and stops before the replace step.

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
