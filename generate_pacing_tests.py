#!/usr/bin/env python3.13
"""Generate 2160p frame-pacing / tearing test clips at common frame rates.

Each clip: gray background, a full-height white bar sweeping left->right at a
constant speed (W/4 px per second, so motion is identical across frame rates),
plus frame number and timecode overlays. Tearing shows as a split in the bar;
bad pacing shows as uneven stepping / skipped or doubled frame numbers.

Output: <out>/pacing_<rate>fps.mp4  (AV1 + no audio)
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# label, ffmpeg rate
RATES = [
    ("23.976", "24000/1001"),
    ("24", "24"),
    ("25", "25"),
    ("29.97", "30000/1001"),
    ("30", "30"),
    ("50", "50"),
    ("59.94", "60000/1001"),
    ("60", "60"),
    ("120", "120"),
]
W, H = 3840, 2160
FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]
FONT = next((p for p in FONT_CANDIDATES if Path(p).is_file()), None)
# AV1 8-bit via libaom; fast settings
CODEC = ["-c:v", "libaom-av1", "-crf", "30", "-b:v", "0", "-cpu-used", "8",
         "-row-mt", "1", "-tiles", "2x2", "-g", "120"]


def drawtext(text: str, size: int, y: float, color: str, extra: str = "") -> str:
    """Horizontally centred text box whose vertical centre sits at y * frame height."""
    font = f"fontfile={FONT}" if FONT else "font=monospace"
    opts = [font, f"text='{text}'", f"fontsize={size}", f"fontcolor={color}",
            "x=(w-tw)/2", f"y=h*{y}-th/2", "box=1", "boxcolor=black@0.7",
            f"boxborderw={max(size // 6, 2)}"]
    if extra:
        opts.append(extra)
    return "drawtext=" + ":".join(opts)


def clear_dir(d: Path) -> None:
    if not d.is_dir():
        return
    for p in d.iterdir():
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()
    print(f"cleared {d}")


def make(out: Path, label: str, rate: str, dur: int) -> None:
    f = out / f"pacing_{label}fps.mp4"
    if f.exists():
        print(f"skip {f}")
        return
    bw = W // 40
    # All text is centred and kept inside the middle 9:16 strip (which also sits
    # inside the centre square), so it survives Jellyfin's 16:9 and 9:16 crops.
    text = ",".join([
        drawtext("FRAME PACING", H // 22, 0.31, "white"),
        drawtext("%{frame_num}", H // 9, 0.45, "yellow", "start_number=0"),
        drawtext(f"{label} fps", H // 16, 0.58, "white"),
        drawtext(r"%{pts\:hms}", H // 22, 0.67, "white"),
        "format=yuv420p",
    ])
    # bar position is driven by time, so speed is identical at every frame rate
    fc = f"[0][1]overlay=x='mod(t*{W}/4,{W})':y=0,{text}"
    print(f"make {f}", flush=True)
    tmp = f.with_name(f.stem + ".part.mp4")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=0x404040:s={W}x{H}:r={rate}",
         "-f", "lavfi", "-i", f"color=c=white:s={bw}x{H}:r={rate}",
         "-filter_complex", fc, "-t", str(dur),
         "-an", *CODEC, "-movflags", "+faststart", str(tmp)],
        check=True,
    )
    tmp.rename(f)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", type=Path, default=HERE / "pacing_tests",
                    help="output directory (default: pacing_tests next to this script)")
    ap.add_argument("duration", nargs="?", type=int, default=30,
                    help="clip length in seconds (default: 30)")
    ap.add_argument("-r", "--regen", action="store_true",
                    help="delete everything in the output directory and regenerate all clips")
    a = ap.parse_args()

    if a.regen:
        clear_dir(a.out)
    a.out.mkdir(parents=True, exist_ok=True)
    try:
        for label, rate in RATES:
            make(a.out, label, rate, a.duration)
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg failed ({e.returncode})", file=sys.stderr)
        return 1
    print(f"done -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
