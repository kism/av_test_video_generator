#!/usr/bin/env python3.13
"""Generate surround speaker-identification clips for each major audio codec.

Pink-noise bursts step clockwise around the speakers (FL, C, FR, right
surround(s), rear(s), left surround(s), LFE), one speaker at a time. On screen
a speaker map lights up the speaker that should be playing, and its name is
shown in the middle. If the wrong speaker plays, or two play at once, the
player / AVR is mis-mapping or up/down-mixing channels.

Output: <out>/surr_<codec>_<layout>.mkv  (1080p AV1 video, Matroska)

Formats ffmpeg cannot encode, so not generated: Dolby Atmos, DTS:X,
DTS-HD MA, 7.1 E-AC-3, 7.1 TrueHD.

DTS is left out on purpose: ffmpeg's experimental DTS encoder leaks a
low-passed copy of the right surround into the LFE channel, which makes it
useless as a speaker test.
"""

import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

W, H = 1920, 1080
FPS = "24"
SLOT = 2.5  # seconds per speaker
ON = 2.0    # seconds of noise within each slot (rest is silence)

FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]
FONT = next((p for p in FONT_CANDIDATES if Path(p).is_file()), None)

# layout label -> (ffmpeg layout, test order [(channel, on-screen name, angle deg)])
# angles: 0 = front centre, positive = clockwise (to the right). LFE is placed
# at 60 deg on screen for drawing only.
LAYOUTS = {
    "5.1": ("5.1(side)", [
        ("FL", "FRONT LEFT", -30), ("FC", "CENTER", 0), ("FR", "FRONT RIGHT", 30),
        ("SR", "SURROUND RIGHT", 110), ("SL", "SURROUND LEFT", -110),
        ("LFE", "SUBWOOFER LFE", 60),
    ]),
    "7.1": ("7.1", [
        ("FL", "FRONT LEFT", -30), ("FC", "CENTER", 0), ("FR", "FRONT RIGHT", 30),
        ("SR", "SIDE RIGHT", 90), ("BR", "REAR RIGHT", 150),
        ("BL", "REAR LEFT", -150), ("SL", "SIDE LEFT", -90),
        ("LFE", "SUBWOOFER LFE", 60),
    ]),
}

# codec key -> (title, subtitle, {layout: encoder args})
CODECS = {
    "ac3": ("AC-3", "Dolby Digital", {
        "5.1": ["-c:a", "ac3", "-b:a", "640k"]}),
    "eac3": ("E-AC-3", "Dolby Digital Plus", {
        "5.1": ["-c:a", "eac3", "-b:a", "1024k"]}),
    "truehd": ("TrueHD", "Dolby TrueHD", {
        "5.1": ["-c:a", "truehd", "-strict", "-2"]}),
    "aac": ("AAC", "AAC-LC", {
        "5.1": ["-c:a", "aac", "-b:a", "384k"],
        "7.1": ["-c:a", "aac", "-b:a", "512k"]}),
    "opus": ("Opus", "Opus", {
        "5.1": ["-c:a", "libopus", "-mapping_family", "1", "-b:a", "384k"],
        "7.1": ["-c:a", "libopus", "-mapping_family", "1", "-b:a", "512k"]}),
    "flac": ("FLAC", "Lossless", {
        "5.1": ["-c:a", "flac", "-sample_fmt", "s32"],
        "7.1": ["-c:a", "flac", "-sample_fmt", "s32"]}),
    "pcm": ("PCM", "LPCM 24-bit", {
        "5.1": ["-c:a", "pcm_s24le"],
        "7.1": ["-c:a", "pcm_s24le"]}),
}
# Encoders that only accept 5.1 labelled with back (BL/BR) surrounds: the
# channels are relabelled in place (no remixing) before encoding.
RELABEL = {("opus", "5.1"): "5.1"}
VIDEO = ["-c:v", "libaom-av1", "-crf", "30", "-b:v", "0", "-cpu-used", "8",
         "-row-mt", "1", "-tiles", "2x2", "-g", "120", "-pix_fmt", "yuv420p"]


def clear_dir(d: Path) -> None:
    if not d.is_dir():
        return
    for p in d.iterdir():
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()
    print(f"cleared {d}")


def drawtext(text: str, size: int, x: str, y: str, color: str = "white",
             extra: str = "") -> str:
    font = f"fontfile={FONT}" if FONT else "font=monospace"
    opts = [font, f"text='{text}'", f"fontsize={size}", f"fontcolor={color}",
            f"x={x}", f"y={y}"]
    if extra:
        opts.append(extra)
    return "drawtext=" + ":".join(opts)


def active(k: int, n: int, during_on: bool) -> str:
    """Timeline expression: true while speaker k (of n) owns the current slot."""
    e = f"eq(mod(floor(t/{SLOT}),{n}),{k})"
    return f"{e}*lt(mod(t,{SLOT}),{ON})" if during_on else e


def video_filter(title: str, subtitle: str, layout: str, order) -> str:
    n = len(order)
    cx, cy, r = W / 2, H / 2, 0.38 * H
    box = round(0.09 * H)
    f = []
    # speaker map (inside the centre square)
    for k, (ch, _, ang) in enumerate(order):
        a = math.radians(ang)
        s = round(box * 0.75) if ch == "LFE" else box
        x = round(cx + r * math.sin(a) - s / 2)
        y = round(cy - r * math.cos(a) - s / 2)
        f.append(f"drawbox=x={x}:y={y}:w={s}:h={s}:color=0x303030:t=fill")
        f.append(f"drawbox=x={x}:y={y}:w={s}:h={s}:color=0xFF8C00:t=fill"
                 f":enable='{active(k, n, True)}'")
        f.append(f"drawbox=x={x}:y={y}:w={s}:h={s}:color=0x909090:t=3")
        f.append(drawtext(ch, s // 3, f"{x}+({s}-tw)/2", f"{y}+({s}-th)/2"))
    # centre text, kept inside the middle 9:16 strip for Jellyfin thumbnails
    cxt = "(w-tw)/2"
    f.append(drawtext(f"{title} {layout}", H // 13, cxt, "h*0.37-th/2"))
    f.append(drawtext(subtitle, H // 26, cxt, "h*0.45-th/2", "0xC0C0C0"))
    for k, (_, name, _) in enumerate(order):
        f.append(drawtext(name, H // 18, cxt, "h*0.57-th/2", "yellow",
                          f"enable='{active(k, n, False)}'"))
    f.append(drawtext("speaker test - pink noise", H // 36, cxt, "h*0.65-th/2",
                      "0x909090"))
    return ",".join(f)


def audio_filter(ff_layout: str, order, relabel: str | None = None) -> str:
    n = len(order)
    parts = [f"anoisesrc=c=pink:r=48000:a=0.35:nb_samples=256,asplit={n}"
             + "".join(f"[n{k}]" for k in range(n))]
    for k, (ch, _, _) in enumerate(order):
        lp = ",lowpass=f=120" if ch == "LFE" else ""
        parts.append(f"[n{k}]volume='{active(k, n, True)}':eval=frame{lp}[c{k}]")
    mapping = "|".join(f"{k}.0-{ch}" for k, (ch, _, _) in enumerate(order))
    parts.append("".join(f"[c{k}]" for k in range(n))
                 + f"join=inputs={n}:channel_layout={ff_layout}:map={mapping}"
                 + (f",channelmap=channel_layout={relabel}" if relabel else "") + "[a]")
    return ";".join(parts)


def make(out: Path, key: str, layout: str, loops: int) -> None:
    title, subtitle, encoders = CODECS[key]
    f = out / f"surr_{key}_{layout}.mkv"
    if f.exists():
        print(f"skip {f}")
        return
    ff_layout, order = LAYOUTS[layout]
    dur = SLOT * len(order) * loops
    print(f"make {f}", flush=True)
    tmp = f.with_name(f.stem + ".part.mkv")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}",
         "-filter_complex",
         f"[0]{video_filter(title, subtitle, layout, order)}[v];"
         f"{audio_filter(ff_layout, order, RELABEL.get((key, layout)))}",
         "-map", "[v]", "-map", "[a]", "-t", f"{dur}",
         *VIDEO, *encoders[layout], "-ar", "48000", str(tmp)],
        check=True,
    )
    tmp.rename(f)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", type=Path, default=HERE / "surround_tests",
                    help="output directory (default: surround_tests next to this script)")
    ap.add_argument("loops", nargs="?", type=int, default=2,
                    help="times to cycle through all speakers (default: 2)")
    ap.add_argument("-r", "--regen", action="store_true",
                    help="delete everything in the output directory and regenerate all clips")
    a = ap.parse_args()

    if a.regen:
        clear_dir(a.out)
    a.out.mkdir(parents=True, exist_ok=True)
    try:
        for key, (_, _, encoders) in CODECS.items():
            for layout in encoders:
                make(a.out, key, layout, a.loops)
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg failed ({e.returncode})", file=sys.stderr)
        return 1
    print(f"done -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
