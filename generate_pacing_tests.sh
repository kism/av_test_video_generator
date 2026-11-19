#!/usr/bin/env bash
# Generates frame-pacing / tearing test clips at common frame rates, 1080p and 2160p.
# Each clip: gray background, a full-height white bar sweeping left->right at a
# constant speed (W/4 px per second, so motion is identical across frame rates),
# plus frame number and timecode overlays. Tearing shows as a split in the bar;
# bad pacing shows as uneven stepping / skipped or doubled frame numbers.
#
# Usage: ./make_pacing_tests.sh [output_dir] [duration_seconds]
set -euo pipefail

OUT="${1:-pacing_tests}"
DUR="${2:-30}"
FONT="/System/Library/Fonts/Menlo.ttc"
mkdir -p "$OUT"

# label:rate
RATES=(
  "23.976:24000/1001"
  "24:24"
  "25:25"
  "29.97:30000/1001"
  "30:30"
  "50:50"
  "59.94:60000/1001"
  "60:60"
  "120:120"
)
# label:width:height:codec-args
make() {
  local rlabel=$1 rate=$2 rlabel2=$3 w=$4 h=$5; shift 5
  local f="$OUT/pacing_${rlabel2}_${rlabel}fps.mp4"
  [[ -f $f ]] && { echo "skip $f"; return; }
  local fs=$((h / 12)) bw=$((w / 40))
  # bar position: loops every 4 seconds, driven by time so speed is rate-independent
  local text="drawtext=fontfile=${FONT}:text='%{frame_num}':start_number=0:x=(w-tw)/2:y=h/2-th:fontsize=${fs}:fontcolor=yellow:box=1:boxcolor=black@0.7,\
drawtext=fontfile=${FONT}:text='${rlabel} fps ${rlabel2}  %{pts\\:hms}':x=(w-tw)/2:y=h/2+th/2:fontsize=$((fs/2)):fontcolor=white:box=1:boxcolor=black@0.7,\
format=yuv420p"
  # bar position is driven by time, so speed is identical at every frame rate
  local fc="[0][1]overlay=x='mod(t*${w}/4,${w})':y=0,${text}"
  echo "make $f"
  ffmpeg -hide_banner -loglevel error -y \
    -f lavfi -i "color=c=0x404040:s=${w}x${h}:r=${rate}" \
    -f lavfi -i "color=c=white:s=${bw}x${h}:r=${rate}" \
    -filter_complex "$fc" -t "$DUR" \
    -an "$@" -movflags +faststart "$f"
}

for entry in "${RATES[@]}"; do
  label=${entry%%:*}; rate=${entry#*:}
  # AV1 8-bit via libaom (the only AV1 encoder in this ffmpeg build); fast settings
  for res in "1080p 1920 1080" "2160p 3840 2160"; do
    set -- $res
    make "$label" "$rate" "$1" "$2" "$3" \
      -c:v libaom-av1 -crf 30 -b:v 0 -cpu-used 8 -row-mt 1 -tiles 2x2 -g 120
  done
done
echo "done -> $OUT"

