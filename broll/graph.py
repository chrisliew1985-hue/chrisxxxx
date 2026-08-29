"""Assembling the ffmpeg filtergraph and command line."""

import os
from dataclasses import dataclass, field

from . import motion, text
from .presets import Preset

# Colour grades, applied once to the assembled film.
GRADES: dict[str, str] = {
    "none": "",
    "clean": "eq=contrast=1.04:saturation=1.02",
    # Gentle S-curve, cool shadows against warm highlights, a soft vignette and
    # a whisper of grain: the usual ingredients of a filmic look.
    "cinematic": (
        "eq=contrast=1.07:saturation=0.93:gamma=0.98,"
        "colorbalance=rs=-0.025:bs=0.035:rh=0.030:bh=-0.020,"
        "vignette=angle=PI/5.2,"
        "unsharp=5:5:0.35:5:5:0.0,"
        "noise=alls=3:allf=t+u"
    ),
    "warm": (
        "eq=contrast=1.05:saturation=1.06,"
        "colorbalance=rh=0.045:bh=-0.030,"
        "vignette=angle=PI/6"
    ),
}


@dataclass
class Clip:
    image: str
    frames: int
    move: str
    texts: list[text.TextSpec] = field(default_factory=list)

    def seconds(self, fps: int) -> float:
        return self.frames / fps


class _Inputs:
    """Collects ffmpeg -i arguments and hands back each one's stream index."""

    def __init__(self) -> None:
        self.args: list[str] = []
        self._count = 0

    def add(self, path: str, *, before: list[str] | None = None) -> int:
        self.args += (before or []) + ["-i", path]
        self._count += 1
        return self._count - 1


def _offsets(clips: list[Clip], fps: int, transition: float) -> list[float]:
    """Where each cross-fade starts, walking the timeline clip by clip."""
    offsets: list[float] = []
    elapsed = clips[0].seconds(fps)
    for clip in clips[1:]:
        offsets.append(elapsed - transition)
        elapsed += clip.seconds(fps) - transition
    return offsets


def total_seconds(clips: list[Clip], fps: int, transition: float) -> float:
    return sum(c.seconds(fps) for c in clips) - transition * (len(clips) - 1)


def build(
    clips: list[Clip],
    out_path: str,
    preset: Preset,
    *,
    work_dir: str,
    scrim_path: str | None = None,
    music: str | None = None,
    music_volume: float = 0.8,
    grade: str = "cinematic",
    transition_type: str = "fade",
    fade_in: float = 1.0,
    fade_out: float = 1.4,
    crf: int = 18,
    x264_preset: str = "slow",
) -> list[str]:
    """Return the full ffmpeg argv for one render."""
    if grade not in GRADES:
        raise SystemExit(f"unknown grade {grade!r} (choose from: {', '.join(GRADES)})")

    from .media import ffmpeg_exe

    width, height = preset.size
    fps, transition = preset.fps, preset.transition

    inputs = _Inputs()
    # The still-image demuxer reports no frame rate, which xfade refuses;
    # declaring one on the input and again after zoompan keeps the links constant.
    clip_indexes = [
        inputs.add(clip.image, before=["-framerate", str(fps)]) for clip in clips
    ]
    scrim_index = inputs.add(scrim_path) if scrim_path else None

    # Every text block becomes its own looped still, so ffmpeg can fade its
    # alpha independently of the photo underneath it.
    text_indexes: list[list[int]] = []
    for clip_number, clip in enumerate(clips):
        per_clip = []
        for spec_number, spec in enumerate(clip.texts):
            png = text.render(
                spec, preset.size,
                os.path.join(work_dir, f"text_{clip_number:03d}_{spec_number}.png"),
            )
            per_clip.append(inputs.add(
                png,
                before=["-loop", "1", "-framerate", str(fps), "-t", f"{clip.seconds(fps):.3f}"],
            ))
        text_indexes.append(per_clip)

    music_index = inputs.add(music, before=["-stream_loop", "-1"]) if music else None

    chains: list[str] = []
    if scrim_index is not None:
        outs = "".join(f"[scrim{i}]" for i in range(len(clips)))
        chains.append(f"[{scrim_index}:v]split={len(clips)}{outs}")

    for number, clip in enumerate(clips):
        z, x, y = motion.expressions(clip.move, clip.frames, preset.zoom)
        node = (
            f"[{clip_indexes[number]}:v]zoompan=z='{z}':x='{x}':y='{y}'"
            f":d={clip.frames}:s={width}x{height}:fps={fps}"
            f",fps={fps},setsar=1,format=yuv420p,setpts=PTS-STARTPTS"
        )

        # Everything that sits on top of this photo, back to front.
        layers: list[str] = []
        if scrim_index is not None:
            layers.append(f"[scrim{number}]")
        for spec, stream in zip(clip.texts, text_indexes[number]):
            fade = max(spec.fade, 0.01)
            label = f"[o{number}_{stream}]"
            chains.append(
                f"[{stream}:v]format=rgba,setpts=PTS-STARTPTS"
                f",fade=t=in:st={spec.fade_in_at:.3f}:d={fade:.3f}:alpha=1"
                f",fade=t=out:st={max(spec.fade_out_at - fade, spec.fade_in_at):.3f}"
                f":d={fade:.3f}:alpha=1{label}"
            )
            layers.append(label)

        for stage, layer in enumerate(layers):
            base = f"[s{number}_{stage}]"
            chains.append(f"{node}{base}")
            node = f"{base}{layer}overlay=0:0:format=auto"

        # Overlaying stills can drop the frame rate off the link again; pin it
        # once more so xfade always sees a constant rate.
        chains.append(f"{node},fps={fps},setsar=1[c{number}]")

    current = "[c0]"
    for step, offset in enumerate(_offsets(clips, fps, transition), start=1):
        label = f"[x{step}]"
        chains.append(
            f"{current}[c{step}]xfade=transition={transition_type}"
            f":duration={transition:.3f}:offset={offset:.3f}{label}"
        )
        current = label

    total = total_seconds(clips, fps, transition)
    tail = GRADES[grade].split(",") if GRADES[grade] else []
    if fade_in > 0:
        tail.append(f"fade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0:
        tail.append(f"fade=t=out:st={max(total - fade_out, 0):.3f}:d={fade_out:.3f}")
    tail.append("format=yuv420p")
    chains.append(f"{current}{','.join(tail)}[v]")

    if music_index is not None:
        chains.append(
            f"[{music_index}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS"
            f",volume={music_volume:.3f},afade=t=in:st=0:d=1.5"
            f",afade=t=out:st={max(total - 2.5, 0):.3f}:d=2.5[a]"
        )

    args = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-stats"]
    args += inputs.args
    args += ["-filter_complex", ";".join(chains), "-map", "[v]"]
    if music_index is not None:
        args += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    args += [
        "-c:v", "libx264",
        "-preset", x264_preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        "-r", str(fps),
        "-t", f"{total:.3f}",
        "-movflags", "+faststart",
        out_path,
    ]
    return args
