#!/usr/bin/env bash
# media-transcoder worker: compress 4K remuxes to HEVC on the Arc B70 (VA-API),
# driven by a queue on the nemesis NFS share. Runs ONLY inside the configured
# nightly / work-day windows; idles (zero GPU use) otherwise.
#
# One instance only. State lives under /data/media/.reclaim/ (NFS-shared with
# the nemesis-side scripts in scripts/media-reclaim/).
set -uo pipefail

POLICY=/policy.conf
# shellcheck source=transcode-policy.conf
source "$POLICY"

DATA=/data                        # NFS root: /data/media, /data/media2
STATE="$DATA/media/.reclaim"
QUEUE="$STATE/queue/queue.tsv"
LEDGER="$STATE/ledger.tsv"
DONE="$STATE/done.list"
FAILED="$STATE/failed.list"
PAUSE="$STATE/PAUSE"
PILOT_ACK="$STATE/PILOT_ACK"
PILOT_NOTIFIED="$STATE/.pilot-notified"
STATUS="$STATE/status.md"
QCLOG="$STATE/qc-vmaf.tsv"             # rel, offset, score for every verify clip
SCRATCH="${SCRATCH:-/scratch}"    # policy may move it onto the NFS share
mkdir -p "$SCRATCH"

FFMPEG_PID=""
CUR_TMP=""

log() { echo "[$(date '+%F %T')] $*"; }

notify() {
  [[ -n "${WEBHOOK_URL:-}" ]] || return 0
  command -v curl >/dev/null || return 0
  curl -sf -X POST -H 'Content-Type: application/json' \
    -d "{\"content\": \"[media-transcoder] $1\"}" "$WEBHOOK_URL" >/dev/null 2>&1 || true
}

on_term() {
  log "SIGTERM: aborting current encode (job will be retried)"
  [[ -n "$FFMPEG_PID" ]] && kill "$FFMPEG_PID" 2>/dev/null
  [[ -n "$CUR_TMP" ]] && rm -f "$CUR_TMP"
  exit 143
}
trap on_term TERM INT

# --------------------------------------------------------------------------
# Scheduling: WINDOWS is a semicolon-separated list of "<days> HH:MM-HH:MM".
# days: daily | Mon-Fri | Sat-Sun | a single day name. Overnight spans wrap.

day_matches() {  # $1=days-spec  $2=weekday(1=Mon..7=Sun)
  case "$1" in
    daily) return 0 ;;
    Mon-Fri) [[ $2 -le 5 ]] ;;
    Sat-Sun) [[ $2 -ge 6 ]] ;;
    Mon) [[ $2 -eq 1 ]] ;; Tue) [[ $2 -eq 2 ]] ;; Wed) [[ $2 -eq 3 ]] ;;
    Thu) [[ $2 -eq 4 ]] ;; Fri) [[ $2 -eq 5 ]] ;; Sat) [[ $2 -eq 6 ]] ;;
    Sun) [[ $2 -eq 7 ]] ;;
    *) return 1 ;;
  esac
}

in_window() {
  local today yesterday now
  today=$(date +%u)
  yesterday=$(( today == 1 ? 7 : today - 1 ))
  now=$(( 10#$(date +%H) * 60 + 10#$(date +%M) ))
  local IFS=';'
  for w in $WINDOWS; do
    w="${w#"${w%%[![:space:]]*}"}"
    local days times start end
    days="${w%% *}"; times="${w#* }"
    start=$(( 10#${times%%:*} * 60 + 10#$(cut -d- -f1 <<<"$times" | cut -d: -f2) ))
    end=$(( 10#$(cut -d- -f2 <<<"$times" | cut -d: -f1) * 60 + 10#${times##*:} ))
    if (( start <= end )); then
      day_matches "$days" "$today" && (( now >= start && now < end )) && return 0
    else  # overnight wrap: evening belongs to the listed day
      day_matches "$days" "$today" && (( now >= start )) && return 0
      day_matches "$days" "$yesterday" && (( now < end )) && return 0
    fi
  done
  return 1
}

plex_busy() {
  [[ "${PLEX_GUARD:-true}" == "true" && -n "${PLEX_TOKEN:-}" ]] || return 1
  command -v curl >/dev/null || return 1
  local n
  n=$(curl -sf --max-time 10 "${PLEX_URL}/status/sessions?X-Plex-Token=${PLEX_TOKEN}" \
      | grep -c '<Video' || true)
  [[ "${n:-0}" -gt 0 ]]
}

# --------------------------------------------------------------------------
pick_vaapi_device() {
  local dev
  for dev in ${VAAPI_DEVICE:-} /dev/dri/renderD128 /dev/dri/renderD129 /dev/dri/renderD130; do
    [[ -e "$dev" ]] || continue
    if ffmpeg -v error -init_hw_device "vaapi=va:$dev" -f lavfi -i color=black:s=1280x720 \
        -frames:v 3 -vf format=nv12,hwupload -c:v hevc_vaapi -f null - >/dev/null 2>&1; then
      echo "$dev"; return 0
    fi
  done
  return 1
}

probe1() {  # $1=file $2=entries -> first line of csv output
  ffprobe -v error -show_entries "$2" -of csv=p=0 "$1" 2>/dev/null | head -1
}

pick_audio() {  # $1=file -> "absidx codec channels" of first eng (else first) audio
  local lines
  lines=$(ffprobe -v error -select_streams a -show_entries \
    stream=index,codec_name,channels:stream_tags=language -of compact=p=0 "$1" 2>/dev/null)
  local first="" eng=""
  while IFS= read -r ln; do
    [[ -z "$ln" ]] && continue
    local idx codec ch lang
    idx=$(grep -oP 'index=\K[0-9]+' <<<"$ln")
    codec=$(grep -oP 'codec_name=\K[^|]+' <<<"$ln")
    ch=$(grep -oP 'channels=\K[0-9]+' <<<"$ln")
    lang=$(grep -oP 'tag:language=\K[^|]+' <<<"$ln" || true)
    [[ -z "$first" ]] && first="$idx ${codec:-?} ${ch:-6}"
    if [[ -z "$eng" && "${lang:-}" == eng* ]]; then eng="$idx ${codec:-?} ${ch:-6}"; fi
  done <<<"$lines"
  echo "${eng:-$first}"
}

pick_subs() {  # $1=file -> "-map 0:N" pairs for eng-tagged (else untagged) text/PGS subs, may be empty
  # ffmpeg's "-map 0:s:m:language:eng?" is NOT optional: the "?" is read as
  # part of the metadata value, so a file with no eng-tagged subtitle stream
  # aborts with "Stream map '' matches no streams" (rc=234). Pick by index.
  local lines
  lines=$(ffprobe -v error -select_streams s -show_entries \
    stream=index:stream_tags=language -of compact=p=0 "$1" 2>/dev/null)
  local eng=() untagged=()
  while IFS= read -r ln; do
    [[ -z "$ln" ]] && continue
    local idx lang
    idx=$(grep -oP 'index=\K[0-9]+' <<<"$ln")
    lang=$(grep -oP 'tag:language=\K[^|]+' <<<"$ln" || true)
    if [[ "${lang:-}" == eng* ]]; then eng+=(-map "0:$idx")
    elif [[ -z "${lang:-}" || "$lang" == und ]]; then untagged+=(-map "0:$idx"); fi
  done <<<"$lines"
  if (( ${#eng[@]} )); then printf '%s\n' "${eng[@]}"
  elif (( ${#untagged[@]} )); then printf '%s\n' "${untagged[@]}"; fi
}

count_lines() { local n; n=$(grep -c . "$1" 2>/dev/null); echo "${n:-0}"; }

update_status() {
  local done_n saved queued
  done_n=$(count_lines "$DONE")
  queued=$(( $(count_lines "$QUEUE") - 1 )); (( queued < 0 )) && queued=0
  saved=$(awk -F'\t' '$2=="transcode-replace" && $9 ~ /^saved:/ {sub("saved:","",$9); s+=$9} END{printf "%.0f", s/1024/1024/1024}' "$LEDGER" 2>/dev/null)
  {
    echo "# media-transcoder status"
    echo "- updated: $(date -Is)"
    echo "- state: $1"
    echo "- done: ${done_n} / queued: ${queued}"
    echo "- saved so far: ${saved:-0} GiB"
  } > "$STATUS" 2>/dev/null || true
}

ledger_add() {  # action title old_path old_size nlink inode status
  if [[ ! -f "$LEDGER" ]]; then
    printf 'ts\taction\ttitle\told_path\told_size_bytes\tnlink\tsamefile_paths\tqbit_hash\tstatus\n' > "$LEDGER"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\tinum:%s\t-\t%s\n' \
    "$(date -Is)" "$1" "$2" "$3" "$4" "$5" "$6" "$7" >> "$LEDGER"
}

# --------------------------------------------------------------------------
next_job() {  # -> "rel_path<TAB>size" or empty
  [[ -f "$QUEUE" ]] || return 0
  tail -n +2 "$QUEUE" | while IFS=$'\t' read -r rel size target title; do
    [[ -z "$rel" ]] && continue
    grep -qxF "$rel" "$DONE" 2>/dev/null && continue
    awk -F'\t' -v r="$rel" '$1==r{f=1} END{exit !f}' "$FAILED" 2>/dev/null && continue
    printf '%s\t%s\n' "$rel" "$size"
    break
  done
}

fail_job() {  # rel reason
  printf '%s\t%s\n' "$1" "$2" >> "$FAILED"
  log "FAILED $1: $2"
  notify "FAILED: $1 ($2)"
}

# Whole seconds of the first video stream. The container duration follows the
# longest stream, and some remuxes carry audio tracks that outlast the picture
# (Wrath of Man: DTS +9 s), which the encode rightly does not keep.
video_duration() {  # file -> seconds
  local d
  d=$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of default=nw=1:nk=1 "$1" 2>/dev/null | head -1)
  if [[ ! $d =~ ^[0-9.]+$ ]]; then
    d=$(ffprobe -v error -select_streams v:0 -show_entries stream_tags=DURATION -of default=nw=1:nk=1 "$1" 2>/dev/null \
      | awk -F: 'NF == 3 { printf "%.3f", $1 * 3600 + $2 * 60 + $3; exit }')
  fi
  [[ $d =~ ^[0-9.]+$ ]] || d=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$1" 2>/dev/null)
  echo "${d%%.*}"
}

# Check the encode across its whole length before the original is purged.
#  1. census: one read of the encode, audio and video packets counted per
#     VERIFY_STEP block; a block short of either fails (catches audio that
#     silently stops, or a truncated video track).
#  2. a 4 s clip in the middle of every block: must decode (video + audio) and,
#     with VERIFY_VMAF, score >= VMAF_FAIL against the source.
# Prints "ok <summary>" or "fail <reason>"; per-clip scores go to $QCLOG.
verify_encode() {  # tmp src duration rel
  local tmp=$1 src=$2 dur=$3 rel=$4 step=${VERIFY_STEP:-300}
  local fps census short
  fps=$(probe1 "$tmp" "stream=avg_frame_rate" | awk -F/ '{ printf "%d", ($2 ? $1/$2 : $1) }')
  census=$(ffprobe -v error -show_entries packet=stream_index,pts_time -of csv=p=0 "$tmp" 2>/dev/null |
    awk -F, -v step="$step" -v dur="$dur" -v fps="${fps:-24}" -v apps="${AUDIO_MIN_PPS:-25}" '
      $2 == "N/A" { next }
      { b = int($2 / step) }
      $1 == 0 { v[b]++ }
      $1 == 1 { a[b]++ }
      END {
        nb = int(dur / step)              # full blocks only; the tail block is partial
        for (i = 0; i < nb; i++) {
          if (a[i] < step * apps * 0.9) { printf "audio-short@%ds(%dpkts)", i * step, a[i]; exit }
          if (v[i] < step * fps * 0.9)  { printf "video-short@%ds(%dpkts)", i * step, v[i]; exit }
        }
        printf "OK %d", nb
      }')
  [[ $census == OK* ]] || { echo "fail $census"; return; }

  # Seek the source by the same picture, not the same timestamp: when the two
  # video streams start at different times (Bad Boys II: source 0.017 s, encode
  # 0), equal -ss values can land a frame apart and VMAF scores a fast scene ~45.
  local vstart_src vstart_tmp shift
  vstart_src=$(ffprobe -v error -select_streams v:0 -show_entries stream=start_time -of default=nw=1:nk=1 "$src" 2>/dev/null | head -1)
  vstart_tmp=$(ffprobe -v error -select_streams v:0 -show_entries stream=start_time -of default=nw=1:nk=1 "$tmp" 2>/dev/null | head -1)
  [[ $vstart_src =~ ^-?[0-9.]+$ ]] || vstart_src=0
  [[ $vstart_tmp =~ ^-?[0-9.]+$ ]] || vstart_tmp=0
  shift=$(awk -v a="$vstart_src" -v b="$vstart_tmp" 'BEGIN { printf "%.3f", a - b }')

  local t ts clips=0 low="" score min=100 sum=0
  for (( t = step / 2; t + 4 < dur; t += step )); do
    ts=$(awk -v t="$t" -v s="$shift" 'BEGIN { printf "%.3f", t + s }')
    if ! ffmpeg -v error -ss "$t" -i "$tmp" -t 4 -map 0:v:0 -map 0:a:0 -f null - >/dev/null 2>&1; then
      echo "fail decode-check@${t}s"; return
    fi
    clips=$(( clips + 1 ))
    [[ "${VERIFY_VMAF:-true}" == "true" ]] || continue
    score=$(ffmpeg -hide_banner -nostdin -ss "$t" -t 4 -i "$tmp" -ss "$ts" -t 4 -i "$src" \
      -lavfi "[0:v]setpts=PTS-STARTPTS[d];[1:v]setpts=PTS-STARTPTS[r];[d][r]libvmaf=model=version=vmaf_4k_v0.6.1:n_threads=${VMAF_THREADS:-6}" \
      -f null - 2>&1 | sed -n 's/.*VMAF score: \([0-9.]*\).*/\1/p' | head -1)
    [[ -n $score ]] || { echo "fail vmaf-error@${t}s"; return; }
    printf '%s\t%s\t%s\n' "$rel" "$t" "$score" >> "$QCLOG"
    if awk -v s="$score" -v f="${VMAF_FAIL:-60}" 'BEGIN { exit !(s < f) }'; then
      echo "fail vmaf@${t}s=${score}"; return
    fi
    awk -v s="$score" -v w="${VMAF_WARN:-85}" 'BEGIN { exit !(s < w) }' && low+="${t}s=${score%.*} "
    min=$(awk -v a="$min" -v b="$score" 'BEGIN { print (b < a) ? b : a }')
    sum=$(awk -v a="$sum" -v b="$score" 'BEGIN { print a + b }')
  done
  local mean="-"; (( clips )) && [[ "${VERIFY_VMAF:-true}" == "true" ]] && mean=$(awk -v s="$sum" -v n="$clips" 'BEGIN { printf "%.1f", s / n }')
  echo "ok ${census#OK } blocks, ${clips} clips, vmaf mean ${mean} min ${min%.*}${low:+, low: $low}"
}

plex_rescan() {  # dir: ask Plex to rescan the folder so it re-reads the swapped file
  [[ -n "${PLEX_TOKEN:-}" ]] || return 0
  curl -sf --max-time 15 -G "${PLEX_URL}/library/sections/${PLEX_SECTION:-1}/refresh" \
    --data-urlencode "path=$1" --data-urlencode "X-Plex-Token=${PLEX_TOKEN}" >/dev/null \
    && log "plex rescan queued: $1" || log "plex rescan failed: $1"
}

transcode_one() {  # $1=rel_path
  local rel="$1" src="$DATA/$1"
  local name dir mount_root holding
  name=$(basename "$src"); dir=$(dirname "$src")
  case "$rel" in
    media/*)  mount_root="$DATA/media" ;;
    media2/*) mount_root="$DATA/media2" ;;
    *) fail_job "$rel" "bad-rel-path"; return ;;
  esac
  holding="$mount_root/.reclaim/holding"
  mkdir -p "$holding"

  [[ -f "$src" ]] || { fail_job "$rel" "source-missing"; return; }
  local src_size src_nlink src_inode
  read -r src_nlink src_size src_inode <<<"$(stat -c '%h %s %i' "$src")"

  # scratch space gate: full source + output must fit
  local avail_gb
  avail_gb=$(( $(df -B1 --output=avail "$SCRATCH" | tail -1) / 1024 / 1024 / 1024 ))
  if (( avail_gb < ${MIN_SCRATCH_GB:-250} )); then
    log "scratch low (${avail_gb}G) - sleeping"; sleep 600; return
  fi

  local duration
  duration=$(video_duration "$src")
  [[ -n "${CLIP_SECS:-}" ]] && duration=$CLIP_SECS   # test mode: encode only the first CLIP_SECS
  read -r aidx acodec ach <<<"$(pick_audio "$src")"
  [[ -z "${aidx:-}" ]] && { fail_job "$rel" "no-audio-stream"; return; }
  # Subtitles are NOT part of the encode. In ffmpeg 9 a sparse copied subtitle
  # (long gaps, e.g. forced PGS) in the same run as a re-encoded audio track
  # starves the audio: at the start of the film with one demuxer, mid-film even
  # from a second demuxer (Forrest Gump lost ~85 s at 7500 s). They are added
  # afterwards in a copy-only remux, which that bug does not touch.
  local sub_args=()
  mapfile -t sub_args < <(pick_subs "$src")
  (( ${#sub_args[@]} )) && sub_args=("${sub_args[@]/#0:/1:}")
  local audio_args
  case "$acodec" in
    ac3|eac3|aac|opus) audio_args=(-c:a copy) ;;
    *) audio_args=(-c:a eac3 -b:a "${AUDIO_BITRATE:-640k}")
       (( ${ach:-6} > 6 )) && audio_args+=(-ac 6) ;;
  esac
  # color passthrough (explicit, in case side-data doesn't survive the hw path)
  # ffprobe prints fields in its own order (space,transfer,primaries), so read them by key
  local prim="" trc="" space="" k v color_args=()
  while IFS='=' read -r k v; do
    case "$k" in
      color_primaries) prim=$v ;; color_transfer) trc=$v ;; color_space) space=$v ;;
    esac
  done < <(ffprobe -v error -select_streams v:0 \
             -show_entries stream=color_primaries,color_transfer,color_space \
             -of default=nw=1 "$src" 2>/dev/null)
  [[ -n "$prim"  && "$prim"  != "unknown" ]] && color_args+=(-color_primaries "$prim")
  [[ -n "$trc"   && "$trc"   != "unknown" ]] && color_args+=(-color_trc "$trc")
  [[ -n "$space" && "$space" != "unknown" ]] && color_args+=(-colorspace "$space")

  local tmp="$SCRATCH/${name%.mkv}.reclaim.mkv"
  local av=$tmp
  (( ${#sub_args[@]} )) && av="$SCRATCH/${name%.mkv}.reclaim-av.mkv"
  CUR_TMP="$av"
  log "encoding [$(( src_size / 1024 / 1024 / 1024 ))G] $rel"
  local t0=$SECONDS
  ffmpeg -hide_banner -nostdin -y -v warning \
    -init_hw_device "vaapi=va:$VADEV" -hwaccel vaapi -hwaccel_output_format vaapi \
    -hwaccel_device va -i "$src" \
    -map 0:v:0 -map "0:$aidx" \
    -c:v "${ENCODER:-hevc_vaapi}" -rc_mode "${RC_MODE:-ICQ}" -global_quality "${VIDEO_QUALITY:-22}" \
    -profile:v main10 "${color_args[@]}" \
    "${audio_args[@]}" -map_metadata 0 -map_chapters 0 \
    ${CLIP_SECS:+-t "$CLIP_SECS"} "$av" &
  FFMPEG_PID=$!
  wait "$FFMPEG_PID"; local rc=$?
  FFMPEG_PID=""
  if (( rc != 0 )); then rm -f "$av"; CUR_TMP=""; fail_job "$rel" "ffmpeg-rc=$rc"; return; fi
  log "encode took $(( (SECONDS - t0) / 60 )) min"

  # ---- subtitles: copy-only remux of the encoded A/V plus the source's subs ----
  if [[ $av != "$tmp" ]]; then
    CUR_TMP="$tmp"
    ffmpeg -hide_banner -nostdin -y -v warning -i "$av" -i "$src" \
      -map 0:v:0 -map 0:a:0 "${sub_args[@]}" -c copy -map_metadata 0 -map_chapters 0 \
      ${CLIP_SECS:+-t "$CLIP_SECS"} "$tmp" &
    FFMPEG_PID=$!
    wait "$FFMPEG_PID"; rc=$?
    FFMPEG_PID=""
    rm -f "$av"
    if (( rc != 0 )); then rm -f "$tmp"; CUR_TMP=""; fail_job "$rel" "subs-remux-rc=$rc"; return; fi
    log "subtitles muxed ($(( ${#sub_args[@]} / 2 )) tracks)"
  fi

  # ---- verify ----
  local out_size out_dur
  out_size=$(stat -c %s "$tmp")
  out_dur=$(video_duration "$tmp")
  if [[ -z "${CLIP_SECS:-}" ]]; then
    if (( out_size < 2 * 1024 * 1024 * 1024 )); then rm -f "$tmp"; CUR_TMP=""; fail_job "$rel" "output-too-small"; return; fi
    if (( out_size * 10 > src_size * 9 )); then rm -f "$tmp"; CUR_TMP=""; fail_job "$rel" "no-size-gain"; return; fi
  fi
  if [[ -n "$duration" && -n "$out_dur" ]] && (( out_dur < duration - 2 || out_dur > duration + 2 )); then
    rm -f "$tmp"; CUR_TMP=""; fail_job "$rel" "duration-mismatch($duration vs $out_dur)"; return
  fi
  local verdict
  verdict=$(verify_encode "$tmp" "$src" "$duration" "$rel")
  if [[ $verdict != ok* ]]; then
    rm -f "$tmp"; CUR_TMP=""; fail_job "$rel" "${verdict#fail }"; return
  fi
  log "verified: ${verdict#ok }"
  if [[ -n "${CLIP_SECS:-}" ]]; then log "clip verified, left at $tmp"; CUR_TMP=""; return; fi

  # ---- replace (original -> holding; new file -> original name) ----
  mv "$src" "$holding/$name" || { rm -f "$tmp"; CUR_TMP=""; fail_job "$rel" "hold-move"; return; }
  local incoming="$dir/.incoming.$name"
  if ! cp "$tmp" "$incoming" || ! mv "$incoming" "$dir/$name"; then
    rm -f "$incoming" "$tmp"; CUR_TMP=""
    mv "$holding/$name" "$src"   # roll the original straight back
    fail_job "$rel" "writeback"; return
  fi
  chown "${MEDIA_UID:-1001}:${MEDIA_GID:-1001}" "$dir/$name" 2>/dev/null || true
  chmod 664 "$dir/$name" 2>/dev/null || true
  rm -f "$tmp"; CUR_TMP=""

  local title; title=$(basename "$dir")
  ledger_add "transcode-replace" "$title" "/docker/plex/$rel" "$src_size" "$src_nlink" \
    "$src_inode" "saved:$(( src_size - out_size ))"
  echo "$rel" >> "$DONE"
  log "done $title: $(( src_size / 1024 / 1024 / 1024 ))G -> $(( out_size / 1024 / 1024 / 1024 ))G"
  plex_rescan "$dir"

  # ---- purge: the encode passed every 5-minute check, so the original goes now ----
  if [[ "${PURGE_ON_PASS:-true}" == "true" ]]; then
    rm -f "$holding/$name" && log "purged original: $name"
  else
    ls -1t "$holding" 2>/dev/null | tail -n +$(( ${HOLD_COUNT:-10} + 1 )) | while IFS= read -r old; do
      rm -f "$holding/$old"
      log "holding purge: $old"
    done
  fi
}

# --------------------------------------------------------------------------
log "media-transcoder starting; windows: ${WINDOWS}"
mkdir -p "$STATE/queue" "$DATA/media/.reclaim/holding" "$DATA/media2/.reclaim/holding"
touch "$DONE" "$FAILED"

VADEV=$(pick_vaapi_device) || { log "no working VA-API device found"; notify "no VA-API device; worker idle"; sleep infinity; }
log "using VA-API device $VADEV"

while true; do
  if [[ -f "$PAUSE" ]]; then update_status "paused (PAUSE file)"; sleep 300; continue; fi
  if ! in_window; then update_status "outside window"; sleep 60; continue; fi

  done_n=$(count_lines "$DONE")
  if (( done_n >= ${PILOT_LIMIT:-3} )) && [[ ! -f "$PILOT_ACK" ]]; then
    if [[ ! -f "$PILOT_NOTIFIED" ]]; then
      notify "pilot batch of ${PILOT_LIMIT:-3} complete - verify playback/HDR, then: touch /docker/plex/media/.reclaim/PILOT_ACK"
      touch "$PILOT_NOTIFIED"
      log "pilot gate reached - waiting for PILOT_ACK"
    fi
    update_status "pilot gate - awaiting PILOT_ACK"; sleep 600; continue
  fi

  if plex_busy; then update_status "deferred (Plex sessions active)"; sleep 900; continue; fi

  job=$(next_job)
  if [[ -z "$job" ]]; then
    update_status "queue empty"
    if [[ -f "$QUEUE" && ! -f "$STATE/.complete-notified" && $done_n -gt 0 ]]; then
      notify "queue drained: ${done_n} titles transcoded"
      touch "$STATE/.complete-notified"
    fi
    sleep 1800; continue
  fi
  rel=$(cut -f1 <<<"$job")
  update_status "encoding: $rel"
  transcode_one "$rel"
done
