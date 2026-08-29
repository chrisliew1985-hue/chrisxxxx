"""Turning stills into motion clips with the Higgsfield CLI.

The CLI does the generating; this module drives it one photo at a time,
caches what it produces, and hands the clips back for the ordinary broll
pipeline to cut together.
"""

import json
import os
import re
import shutil
import subprocess
import urllib.request

DEFAULT_MODEL = "seedance_2_0"
# Interiors want the camera to move, not the room. Saying so keeps the model
# from inventing furniture, people or doorways that are not in the listing.
DEFAULT_PROMPT = (
    "slow cinematic camera move through the space, photorealistic, "
    "architecture and furnishings stay exactly as they are, "
    "no people, no new objects, no text"
)

_URL = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
_VIDEO_SUFFIX = (".mp4", ".mov", ".webm", ".m4v")


def cli_exe() -> str:
    """Locate the Higgsfield CLI, or explain how to install it."""
    override = os.environ.get("BROLL_HIGGSFIELD")
    if override:
        return override
    for name in ("higgsfield", "hf"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit(
        "the Higgsfield CLI was not found. Install it with:\n"
        "  npm i -g @higgsfield/cli\n"
        "then sign in with:  higgsfield auth login"
    )


def _video_urls(payload) -> list[str]:
    """Pull result URLs out of a CLI response.

    The CLI's JSON shape is not pinned down anywhere, so rather than hard-code
    a path this walks the whole structure and keeps anything that looks like a
    video URL, preferring keys that name a result.
    """
    found: list[str] = []

    def walk(node, key: str = "") -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                walk(value, name)
        elif isinstance(node, list):
            for value in node:
                walk(value, key)
        elif isinstance(node, str):
            for url in _URL.findall(node):
                bare = url.split("?", 1)[0].lower()
                if bare.endswith(_VIDEO_SUFFIX) or "video" in key.lower():
                    found.append(url)

    walk(payload)
    # Preserve order while dropping repeats.
    return list(dict.fromkeys(found))


def _parse(output: str) -> list[str]:
    """Read result URLs from CLI output, whether or not it is valid JSON."""
    try:
        return _video_urls(json.loads(output))
    except json.JSONDecodeError:
        pass
    # --json can still be preceded by progress lines; try each line, then fall
    # back to scanning the raw text.
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(("{", "[")):
            try:
                urls = _video_urls(json.loads(line))
            except json.JSONDecodeError:
                continue
            if urls:
                return urls
    return [
        url for url in _URL.findall(output)
        if url.split("?", 1)[0].lower().endswith(_VIDEO_SUFFIX)
    ]


def _download(url: str, dest: str) -> str:
    with urllib.request.urlopen(url, timeout=300) as response, open(dest, "wb") as handle:
        shutil.copyfileobj(response, handle)
    return dest


def animate(
    paths: list[str],
    out_dir: str,
    *,
    model: str = DEFAULT_MODEL,
    prompt: str = DEFAULT_PROMPT,
    aspect_ratio: str | None = None,
    extra_args: list[str] | None = None,
    wait_timeout: str = "20m",
    verbose: bool = False,
) -> list[str]:
    """Generate one motion clip per photo, reusing any already in `out_dir`.

    Generations cost credits, so a clip that is already on disk is never
    regenerated - delete it to force a new take.
    """
    exe = cli_exe()
    os.makedirs(out_dir, exist_ok=True)
    clips: list[str] = []

    for index, path in enumerate(paths):
        dest = os.path.join(out_dir, f"clip_{index:03d}.mp4")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f"[{index + 1}/{len(paths)}] reusing {os.path.basename(dest)}")
            clips.append(dest)
            continue

        command = [
            exe, "generate", "create", model,
            "--image-references", os.path.abspath(path),
            "--prompt", prompt,
            "--wait", "--wait-timeout", wait_timeout,
            "--json",
        ]
        if aspect_ratio:
            command += ["--aspect-ratio", aspect_ratio]
        command += extra_args or []

        print(f"[{index + 1}/{len(paths)}] generating from {os.path.basename(path)}...")
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace",
        )
        if verbose:
            print(result.stdout)
        if result.returncode != 0:
            tail = "\n".join(result.stdout.strip().splitlines()[-15:])
            raise SystemExit(f"higgsfield failed on {path} (exit {result.returncode}):\n{tail}")

        urls = _parse(result.stdout)
        if not urls:
            tail = "\n".join(result.stdout.strip().splitlines()[-15:])
            raise SystemExit(
                f"no video URL found in the Higgsfield response for {path}.\n"
                f"Run the same command with --verbose to see it in full:\n{tail}"
            )
        clips.append(_download(urls[0], dest))

    return clips
