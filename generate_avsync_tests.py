#!/usr/bin/env python3.13
"""Generate A/V sync test clips (1080p, AV1 + AAC stereo).

Every second a white square (1/5 of the screen height) flashes in the centre of
a black frame for 50 ms while a 1 kHz beep plays for the same 50 ms, both
starting at exactly the same timestamp. If the player is in sync, flash and
beep feel simultaneous.

  sync_<rate>fps.mp4          zero-offset clip at every frame rate
  sync_<rate>fps_<+/-ms>.mp4  deliberately offset clips (audio late = +,
                              audio early = -) so you can calibrate your
                              eye/ear and see what offset the player or
                              TV/AVR is adding. Made at OFFSET_RATES only.

Measuring with a phone: record the TV + speakers in slo-mo (240 fps) and count
frames between flash and the first audio waveform bump. Or compare against the
offset clips: the one that "feels" in sync tells you the chain's real latency.
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
OFFSET_RATES = {"23.976", "59.94"}       # which rates also get offset variants
OFFSETS_MS = [-200, -100, -50, 50, 100, 200]  # + = audio late, - = audio early

W, H = 1920, 1080
FLASH = 0.05  # seconds, shared by flash and beep
FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]
FONT = next((p for p in FONT_CANDIDATES if Path(p).is_file()), None)
CODEC = ["-c:v", "libaom-av1", "-crf", "30", "-b:v", "0", "-cpu-used", "8",
         "-row-mt", "1", "-tiles", "2x2", "-g", "120",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def drawtext(text: str, size: int, y: float, color: str = "white") -> str:
    """Horizontally centred text box whose vertical centre sits at y * frame height."""
    font = f"fontfile={FONT}" if FONT else "font=monospace"
    opts = [font, f"text='{text}'", f"fontsize={size}", f"fontcolor={color}",
            "x=(w-tw)/2", f"y=h*{y}-th/2", "box=1", "boxcolor=0x202020",
            f"boxborderw={max(size // 6, 2)}"]
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


def make(out: Path, label: str, rate: str, off_ms: int, dur: int) -> None:
    suffix = f"_{off_ms:+d}ms" if off_ms else ""
    f = out / f"sync_{label}fps{suffix}.mp4"
    if f.exists():
        print(f"skip {f}")
        return
    off = f"{off_ms / 1000:.4f}"
    # +100 keeps mod() arguments positive for negative offsets
    tone = f"0.6*sin(2*PI*1000*t)*lt(mod(t-({off})+100,1),{FLASH})"
    offset_txt = f"audio {off_ms:+d} ms" if off_ms else "in sync"
    # Text stays on screen (so Jellyfin thumbnails aren't blank), centred and
    # inside the middle 9:16 strip / centre square, clear of the flash square
    # (which spans 0.4-0.6 of the height).
    vf = ",".join([
        f"drawbox=x='(iw-ih/5)/2':y='(ih-ih/5)/2':w='ih/5':h='ih/5'"
        f":color=white:t=fill:enable='lt(mod(t,1),{FLASH})'",
        drawtext("A/V SYNC", H // 14, 0.25),
        drawtext(f"{label} fps", H // 20, 0.34),
        drawtext(offset_txt, H // 18, 0.66, "yellow" if off_ms else "lime"),
        drawtext("flash + beep every 1 s", H // 30, 0.73),
        "format=yuv420p",
    ])
    print(f"make {f}", flush=True)
    tmp = f.with_name(f.stem + ".part.mp4")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={rate}",
         "-f", "lavfi", "-i", f"aevalsrc=exprs='{tone}|{tone}':s=48000",
         "-vf", vf, "-t", str(dur),
         *CODEC, "-movflags", "+faststart", str(tmp)],
        check=True,
    )
    tmp.rename(f)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", type=Path, default=HERE / "avsync_tests",
                    help="output directory (default: avsync_tests next to this script)")
    ap.add_argument("duration", nargs="?", type=int, default=20,
                    help="clip length in seconds (default: 20)")
    ap.add_argument("-r", "--regen", action="store_true",
                    help="delete everything in the output directory and regenerate all clips")
    a = ap.parse_args()

    if a.regen:
        clear_dir(a.out)
    a.out.mkdir(parents=True, exist_ok=True)
    try:
        for label, rate in RATES:
            make(a.out, label, rate, 0, a.duration)
            if label in OFFSET_RATES:
                for ms in OFFSETS_MS:
                    make(a.out, label, rate, ms, a.duration)
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg failed ({e.returncode})", file=sys.stderr)
        return 1
    print(f"done -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
