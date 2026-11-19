#!/usr/bin/env bash
# Generates A/V sync test clips (1080p, AV1 + AAC stereo).
#
# Every second a white square (1/5 of the screen height) flashes in the centre of a black frame for 50 ms while a 1 kHz beep plays
# for the same 50 ms, both starting at exactly the same timestamp. If the player
# is in sync, flash and beep feel simultaneous.
#
#  * avsync_1080p_<rate>fps_sync.mp4       zero-offset clip at every frame rate
#  * avsync_1080p_<rate>fps_a<+/-ms>.mp4   deliberately offset clips (audio late = +,
#                                          audio early = -) so you can calibrate your
#                                          eye/ear and see what offset the player
#                                          or TV/AVR is adding. Made at OFFSET_RATES only.
#
# Measuring with a phone: record the TV + speakers in slo-mo (240 fps) and count frames
# between flash and the first audio waveform bump. Or just compare against the offset
# clips: the one that "feels" in sync tells you the chain's real latency.
#
# Usage: ./make_avsync_tests.sh [output_dir] [duration_seconds]
set -euo pipefail

OUT="${1:-avsync_tests}"
DUR="${2:-20}"
mkdir -p "$OUT"

RATES=("23.976:24000/1001" "24:24" "25:25" "29.97:30000/1001" "30:30"
       "50:50" "59.94:60000/1001" "60:60" "120:120")
OFFSET_RATES=("23.976" "59.94")           # which rates also get offset variants
OFFSETS_MS=(-200 -100 -50 50 100 200)     # + = audio late, - = audio early

W=1920 H=1080
FLASH=0.05                                 # seconds, shared by flash and beep

make() {
  local label=$1 rate=$2 off_ms=$3 name=$4
  local f="$OUT/avsync_1080p_${label}fps_${name}.mp4"
  [[ -f $f ]] && { echo "skip $f"; return; }
  local off; off=$(awk -v ms="$off_ms" 'BEGIN{printf "%.4f", ms/1000}')
  # +100 keeps mod() arguments positive for negative offsets
  local tone="0.6*sin(2*PI*1000*t)*lt(mod(t-(${off})+100,1),${FLASH})"
  echo "make $f"
  ffmpeg -hide_banner -loglevel error -y \
    -f lavfi -i "color=c=black:s=${W}x${H}:r=${rate}" \
    -f lavfi -i "aevalsrc=exprs='${tone}|${tone}':s=48000" \
    -vf "drawbox=x='(iw-ih/5)/2':y='(ih-ih/5)/2':w='ih/5':h='ih/5':color=white:t=fill:enable='lt(mod(t,1),${FLASH})',format=yuv420p" \
    -t "$DUR" \
    -c:v libaom-av1 -crf 30 -b:v 0 -cpu-used 8 -row-mt 1 -tiles 2x2 -g 120 \
    -c:a aac -b:a 192k -ar 48000 -ac 2 \
    -movflags +faststart "$f"
}

for entry in "${RATES[@]}"; do
  label=${entry%%:*}; rate=${entry#*:}
  make "$label" "$rate" 0 sync
  for r in "${OFFSET_RATES[@]}"; do
    if [[ $r == "$label" ]]; then
      for ms in "${OFFSETS_MS[@]}"; do
        make "$label" "$rate" "$ms" "a$(printf '%+d' "$ms")ms"
      done
    fi
  done
done
echo "done -> $OUT"

