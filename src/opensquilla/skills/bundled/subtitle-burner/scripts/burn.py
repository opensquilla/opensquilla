#!/usr/bin/env python3
"""Burn an SRT subtitle file into an MP4 video using ffmpeg.

Single-pass re-encode that overlays the SRT cues onto the video stream
via ffmpeg's ``subtitles=`` filter (libass under the hood). The audio
stream is copied without re-encoding. CJK-friendly font fallback is
baked into the force_style chain.

Used by meta-short-drama after video-merger has produced the merged
``final.mp4``: this script writes ``final_subtitled.mp4`` next to it,
matching the user's voiceover language.

Usage:
    python burn.py --input final.mp4 --subtitles drama.srt \\
        --output final_subtitled.mp4 \\
        [--font "Microsoft YaHei,SimHei,Arial Unicode MS,Arial"] \\
        [--font-size 28] [--margin-v 80] [--ffmpeg-path ffmpeg]

Exit codes:
    0 — success, output written.
    1 — failure; stderr carries the ffmpeg tail.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from glob import glob
from pathlib import Path

_WINGET_FFMPEG_GLOB = (
    "Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_*/"
    "ffmpeg-*-full_build/bin"
)


def _probe_resolution(ffmpeg_bin: str, video_path: Path) -> tuple[int, int] | None:
    """Use ffprobe (next to ffmpeg) to read the source video's W x H."""
    ffprobe = ffmpeg_bin.replace("ffmpeg.exe", "ffprobe.exe").replace(
        "/ffmpeg", "/ffprobe",
    )
    if ffprobe == ffmpeg_bin:
        # Fallback for non-Windows / non-suffixed names.
        ffprobe = str(Path(ffmpeg_bin).with_name(
            "ffprobe.exe" if os.name == "nt" else "ffprobe",
        ))
    if not Path(ffprobe).is_file() and shutil.which(ffprobe) is None:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                str(video_path),
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.decode("utf-8", "replace").strip()
    if "x" not in raw:
        return None
    try:
        w_s, h_s = raw.split("x", 1)
        return int(w_s), int(h_s)
    except ValueError:
        return None


def _resolve_ffmpeg(explicit: str) -> str:
    """Return ffmpeg path; probe common Windows install locations as fallback."""
    found = shutil.which(explicit)
    if found:
        return found
    if os.path.isabs(explicit) and os.path.isfile(explicit):
        return explicit
    if os.name != "nt":
        return explicit
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        for bin_dir in glob(os.path.join(local_app, _WINGET_FFMPEG_GLOB)):
            candidate = os.path.join(bin_dir, "ffmpeg.exe")
            if os.path.isfile(candidate):
                return candidate
    user_profile = os.environ.get("USERPROFILE", "")
    candidates = [
        os.path.join(user_profile, "scoop", "apps", "ffmpeg", "current", "bin", "ffmpeg.exe"),
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return explicit


def _escape_subtitle_path(path: str) -> str:
    """Escape a path for ffmpeg's ``subtitles=`` filter argument.

    libass on Windows is picky: drive-letter colons must be backslash-
    escaped, and the path uses forward slashes regardless of OS. Inside
    the filter graph, single quotes wrap the path so commas / brackets
    in the file name don't confuse the parser.
    """
    # Always use forward slashes inside the filter graph.
    normalised = path.replace("\\", "/")
    # Escape drive-letter colon ("C:" -> "C\:") to keep libass happy.
    if len(normalised) >= 2 and normalised[1] == ":" and normalised[0].isalpha():
        normalised = normalised[0] + r"\:" + normalised[2:]
    # Escape any remaining colon (e.g. an unusual file name).
    rest = normalised[3:] if len(normalised) >= 3 else ""
    if ":" in rest:
        normalised = normalised[:3] + rest.replace(":", r"\:")
    # Escape single quotes inside the path (rare on Windows but possible).
    normalised = normalised.replace("'", r"\'")
    return normalised


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", required=True, help="Input MP4 path")
    parser.add_argument("--subtitles", "-s", required=True, help="SRT file path")
    parser.add_argument("--output", "-o", required=True, help="Output MP4 path")
    parser.add_argument(
        "--font",
        default="Microsoft YaHei,SimHei,Arial Unicode MS,Arial",
        help="Comma-separated font fallback chain. First wins. Defaults cover CJK.",
    )
    parser.add_argument("--font-size", type=int, default=42)
    parser.add_argument(
        "--primary-colour", default="&Hffffff",
        help="ASS colour code for fill (&HBBGGRR). Default white &Hffffff.",
    )
    parser.add_argument(
        "--outline-colour", default="&H000000",
        help="ASS colour code for outline. Default black &H000000.",
    )
    parser.add_argument(
        "--outline", type=int, default=2, help="Outline thickness in px.",
    )
    parser.add_argument(
        "--margin-v", type=int, default=80,
        help="Bottom margin in PX of the source video (we set PlayResX/Y to "
             "the source resolution so MarginV maps 1:1 to pixels).",
    )
    parser.add_argument(
        "--play-res", default="auto",
        help="libass PlayRes as 'WxH', or 'auto' to probe the input MP4. "
             "Setting this makes FontSize and MarginV act in source pixels.",
    )
    parser.add_argument(
        "--alignment", type=int, default=2,
        help="libass alignment: 1=bottom-left, 2=bottom-center, 3=bottom-right, "
             "7=top-left, 8=top-center, 9=top-right. Default 2.",
    )
    parser.add_argument("--crf", type=int, default=20)
    parser.add_argument(
        "--preset", default="medium",
        choices=["ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow"],
    )
    parser.add_argument("--ffmpeg-path", default="ffmpeg")
    args = parser.parse_args()

    in_path = Path(args.input)
    srt_path = Path(args.subtitles)
    out_path = Path(args.output)
    if not in_path.is_file():
        print(f"Error: --input not found: {in_path}", file=sys.stderr)
        return 1
    if not srt_path.is_file():
        print(f"Error: --subtitles not found: {srt_path}", file=sys.stderr)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = _resolve_ffmpeg(args.ffmpeg_path)

    # Resolve PlayRes so MarginV / FontSize map to source-video pixels.
    play_w, play_h = 0, 0
    if args.play_res == "auto":
        probed = _probe_resolution(ffmpeg_bin, in_path)
        if probed:
            play_w, play_h = probed
    elif "x" in args.play_res:
        try:
            play_w, play_h = (int(x) for x in args.play_res.split("x", 1))
        except ValueError:
            print(f"Warning: invalid --play-res {args.play_res!r}; ignoring.", file=sys.stderr)

    srt_arg = _escape_subtitle_path(str(srt_path.resolve()))
    force_style_parts = [
        f"FontName={args.font}",
        f"FontSize={args.font_size}",
        f"PrimaryColour={args.primary_colour}",
        f"OutlineColour={args.outline_colour}",
        "BorderStyle=3",
        f"Outline={args.outline}",
        "Shadow=0",
        f"Alignment={args.alignment}",
        f"MarginV={args.margin_v}",
    ]
    if play_w and play_h:
        force_style_parts.extend([f"PlayResX={play_w}", f"PlayResY={play_h}"])
    force_style = ",".join(force_style_parts)
    vf = f"subtitles='{srt_arg}':force_style='{force_style}'"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(in_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", str(args.crf),
        "-preset", args.preset,
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    print("==> burning subtitles", file=sys.stderr)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        print(f"Error: ffmpeg not found ({exc})", file=sys.stderr)
        return 1
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace")[-2500:])
        print(f"\nError: ffmpeg exited {proc.returncode}", file=sys.stderr)
        return 1
    print(str(out_path.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
