"""Locating and driving the ffmpeg binary."""

import os
import re
import shutil
import subprocess

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def ffmpeg_exe() -> str:
    """Return a usable ffmpeg binary, preferring an explicit override."""
    override = os.environ.get("BROLL_FFMPEG")
    if override:
        return override
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError:
        raise SystemExit(
            "ffmpeg not found. Install it (apt install ffmpeg / brew install ffmpeg),\n"
            "or run: pip install imageio-ffmpeg"
        ) from None
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args: list[str], *, verbose: bool = False) -> None:
    """Run ffmpeg, surfacing its own error output when it fails."""
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    if verbose:
        print(proc.stdout)
    if proc.returncode != 0:
        tail = "\n".join(proc.stdout.strip().splitlines()[-25:])
        raise SystemExit(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")


def probe_duration(path: str) -> float:
    """Read a media file's duration in seconds, without needing ffprobe."""
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    match = _DURATION_RE.search(proc.stdout)
    if not match:
        raise SystemExit(f"could not read a duration from {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
