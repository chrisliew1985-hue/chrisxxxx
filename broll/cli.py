"""Command line entry point: photos in, finished film out."""

import argparse
import os
import re
import shutil
import tempfile

from . import captions as captions_mod
from . import animate as animate_mod
from . import graph, images, media, motion, presets, text

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}

MIN_HOLD, MAX_HOLD = 1.8, 9.0


def _natural_key(path: str) -> list:
    """Sort so photo2 comes before photo10."""
    name = os.path.basename(path).lower()
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def collect_images(entries: list[str]) -> list[str]:
    found: list[str] = []
    for entry in entries:
        if os.path.isdir(entry):
            inside = [
                os.path.join(entry, name)
                for name in os.listdir(entry)
                if os.path.splitext(name)[1].lower() in IMAGE_SUFFIXES
            ]
            if not inside:
                raise SystemExit(f"no images found in {entry}")
            found += sorted(inside, key=_natural_key)
        elif os.path.isfile(entry):
            found.append(entry)
        else:
            raise SystemExit(f"no such file or directory: {entry}")
    if not found:
        raise SystemExit("no images given")
    return found


def _unescape(value: str | None) -> str | None:
    """Let \\n on the command line mean a real line break."""
    return value.replace("\\n", "\n") if value else value


def _hold_for_music(
    music: str, photo_count: int, transition: float, end_card_seconds: float
) -> float:
    """Pick a per-photo hold that lands the film on the end of the track."""
    length = media.probe_duration(music)
    clip_count = photo_count + (1 if end_card_seconds else 0)
    hold = (length - end_card_seconds + (clip_count - 1) * transition) / photo_count
    clamped = min(max(hold, MIN_HOLD), MAX_HOLD)
    if abs(clamped - hold) > 0.01:
        print(f"note: music wants a {hold:.1f}s hold per photo; clamped to {clamped:.1f}s")
    return clamped


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="broll",
        description="Turn a folder of photos into a cinematic B-roll clip.",
    )
    parser.add_argument("images", nargs="+", help="image files, or folders of them")
    parser.add_argument("-o", "--out", default="broll.mp4", help="output file (default: broll.mp4)")

    frame = parser.add_argument_group("frame and pacing")
    frame.add_argument("--preset", default=presets.DEFAULT_PRESET, choices=sorted(presets.PRESETS))
    frame.add_argument("--seconds", type=float, help="hold per photo")
    frame.add_argument("--transition", type=float, help="cross-fade length")
    frame.add_argument("--transition-type", default="fade", help="ffmpeg xfade transition")
    frame.add_argument("--zoom", type=float, help="Ken Burns amplitude, e.g. 0.10")
    frame.add_argument("--fps", type=int)
    frame.add_argument("--seed", type=int, default=0, help="shuffles which move each photo gets")

    look = parser.add_argument_group("look")
    look.add_argument("--fill", default="auto", choices=images.FILL_MODES,
                      help="how photos meet the frame (default: auto)")
    look.add_argument("--max-crop", type=float, default=0.30,
                      help="most of a photo 'auto' fill will crop away (default: 0.30)")
    look.add_argument("--crop-anchor", default="center", choices=sorted(images.ANCHORS))
    look.add_argument("--pad-color", default="#0d0f12", help="backdrop colour for --fill pad")
    look.add_argument("--grade", default="cinematic", choices=sorted(graph.GRADES))
    look.add_argument("--supersample", type=int, default=images.SUPERSAMPLE,
                      help="render photos at this multiple of the output size")

    words = parser.add_argument_group("text")
    words.add_argument("--captions", help=".txt (one line per photo) or .json")
    words.add_argument("--title", help="opening title, over the first photo")
    words.add_argument("--subtitle", help="smaller line under the title")
    words.add_argument("--end-card", help="closing headline, e.g. a price")
    words.add_argument("--end-card-sub", help="smaller closing lines")
    words.add_argument("--end-card-color", default="#0d0f12")
    words.add_argument("--end-card-seconds", type=float, default=3.2)
    words.add_argument("--caption-style", default="shadow", choices=("shadow", "box"))
    words.add_argument("--no-scrim", action="store_true",
                       help="skip the gradient that darkens the bottom of frame")
    words.add_argument("--font", help="font file for all text")

    ai = parser.add_argument_group("AI motion (Higgsfield)")
    ai.add_argument("--animate", action="store_true",
                    help="generate a motion clip per photo with Higgsfield, "
                         "instead of moving the still with a Ken Burns crop")
    ai.add_argument("--animate-model", default=animate_mod.DEFAULT_MODEL,
                    help=f"Higgsfield model (default: {animate_mod.DEFAULT_MODEL})")
    ai.add_argument("--animate-prompt", default=animate_mod.DEFAULT_PROMPT,
                    help="motion prompt applied to every photo")
    ai.add_argument("--animate-aspect", help="aspect ratio to ask for, e.g. 9:16 "
                                             "(default: the preset's own shape)")
    ai.add_argument("--animate-dir", help="where generated clips are kept and reused "
                                          "(default: an 'animated' folder beside the output)")
    ai.add_argument("--animate-timeout", default="20m",
                    help="how long to wait for one generation (default: 20m)")

    sound = parser.add_argument_group("sound")
    sound.add_argument("--music", help="audio track; looped if shorter than the film")
    sound.add_argument("--music-volume", type=float, default=0.8)
    sound.add_argument("--fit-music", action="store_true",
                       help="set the per-photo hold so the film ends with the track")

    output = parser.add_argument_group("output")
    output.add_argument("--preview", action="store_true", help="render fast and rough")
    output.add_argument("--dry-run", action="store_true", help="print the ffmpeg command only")
    output.add_argument("--keep-temp", action="store_true")
    output.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def _center_stack(specs: list[text.TextSpec], gaps: list[int], height: int) -> None:
    """Treat several text blocks as one unit and centre it in the frame."""
    heights = [text.measure(spec)[1] for spec in specs]
    top = (height - (sum(heights) + sum(gaps))) // 2
    for index, spec in enumerate(specs):
        spec.y = top
        top += heights[index] + (gaps[index] if index < len(gaps) else 0)


def _animated_clips(args, preset, photo_paths) -> list[graph.Clip]:
    """Generate a motion clip per photo, and let each one's real length set its hold."""
    videos = animate_mod.animate(
        photo_paths,
        args.animate_dir or os.path.join(os.path.dirname(os.path.abspath(args.out)), "animated"),
        model=args.animate_model,
        prompt=args.animate_prompt,
        aspect_ratio=args.animate_aspect or _aspect_ratio(preset),
        wait_timeout=args.animate_timeout,
        verbose=args.verbose,
    )

    clips: list[graph.Clip] = []
    for video in videos:
        # A generated clip is short; hold it for as long as it actually runs,
        # within the pacing the preset asks for.
        length = min(max(media.probe_duration(video), preset.transition + 0.5), MAX_HOLD)
        clips.append(graph.Clip(
            source=video,
            frames=round(length * preset.fps),
            move="still",
            is_video=True,
        ))
    return clips


def _aspect_ratio(preset) -> str:
    """The preset's frame shape, in the form the Higgsfield CLI expects."""
    from math import gcd

    divisor = gcd(preset.width, preset.height)
    return f"{preset.width // divisor}:{preset.height // divisor}"


def build_clips(args, preset, work_dir, photo_paths, caption_lines) -> list[graph.Clip]:
    if args.animate:
        clips = _animated_clips(args, preset, photo_paths)
        _add_text(args, preset, clips, caption_lines)
        if args.end_card:
            clips.append(_end_card_clip(args, preset, work_dir))
        return clips

    prepared = images.prepare(
        photo_paths, os.path.join(work_dir, "frames"), preset.size,
        fill=args.fill, max_crop=args.max_crop, anchor=args.crop_anchor,
        pad_color=args.pad_color, supersample=args.supersample,
    )
    frames = round(preset.seconds * preset.fps)
    moves = motion.plan(len(prepared), args.seed)

    clips = [
        graph.Clip(source=item.path, frames=frames, move=moves[index])
        for index, item in enumerate(prepared)
    ]
    _add_text(args, preset, clips, caption_lines)

    if args.end_card:
        clips.append(_end_card_clip(args, preset, work_dir))
    return clips


def _add_text(args, preset, clips: list[graph.Clip], caption_lines) -> None:
    """Hang captions, and the opening title, on the photo clips."""
    caption_size = round(preset.height * preset.caption_size)
    caption_y = round(preset.height * preset.caption_y)

    for index, clip in enumerate(clips):
        hold = clip.seconds(preset.fps)
        caption = caption_lines[index] if index < len(caption_lines) else None
        if caption:
            spec = text.TextSpec(
                text=caption,
                font=captions_mod.pick_font(caption, args.font),
                size=caption_size,
                y=caption_y,
                anchor="bottom",
                fade_in_at=0.5,
                fade_out_at=max(hold - 0.35, 1.0),
                tracking=0.03,
                line_spacing=round(caption_size * 0.35),
            )
            text.layout(spec, preset.width * 0.84)
            clip.texts.append(spec)

        if index == 0 and args.title:
            clip.texts.extend(_title_specs(args, preset, hold))


def _title_specs(args, preset, hold: float) -> list[text.TextSpec]:
    title = _unescape(args.title)
    subtitle = _unescape(args.subtitle)
    title_size = round(preset.height * preset.title_size)
    sub_size = round(title_size * 0.40)

    specs = [text.TextSpec(
        text=title,
        font=captions_mod.pick_font(title, args.font),
        size=title_size,
        y="center",
        fade_in_at=0.6,
        fade_out_at=max(hold - 0.3, 1.6),
        fade=0.8,
        tracking=0.10,
        wash=0.30,
        line_spacing=round(title_size * 0.25),
    )]
    if subtitle:
        specs.append(text.TextSpec(
            text=subtitle,
            font=captions_mod.pick_font(subtitle, args.font),
            size=sub_size,
            y="center",
            fade_in_at=1.0,
            fade_out_at=max(hold - 0.3, 1.8),
            fade=0.8,
            tracking=0.16,
            line_spacing=round(sub_size * 0.45),
        ))
    for spec in specs:
        text.layout(spec, preset.width * 0.86)
    if subtitle:
        _center_stack(specs, [round(specs[0].size * 0.55)], preset.height)
    return specs


def _end_card_clip(args, preset, work_dir) -> graph.Clip:
    background = text.card(
        os.path.join(work_dir, "endcard.jpg"),
        (preset.width * args.supersample, preset.height * args.supersample),
        args.end_card_color,
    )
    headline = _unescape(args.end_card)
    lines = _unescape(args.end_card_sub)
    head_size = round(preset.height * preset.end_card_size)
    sub_size = round(head_size * 0.50)
    hold = args.end_card_seconds

    specs = [text.TextSpec(
        text=headline,
        font=captions_mod.pick_font(headline, args.font),
        size=head_size,
        y="center",
        fade_in_at=0.4,
        fade_out_at=hold,
        fade=0.7,
        tracking=0.06,
        line_spacing=round(head_size * 0.3),
    )]
    if lines:
        specs.append(text.TextSpec(
            text=lines,
            font=captions_mod.pick_font(lines, args.font),
            size=sub_size,
            y="center",
            fade_in_at=0.8,
            fade_out_at=hold,
            fade=0.7,
            tracking=0.10,
            line_spacing=round(sub_size * 0.55),
        ))
    for spec in specs:
        text.layout(spec, preset.width * 0.80)
    if lines:
        _center_stack(specs, [round(specs[0].size * 0.9)], preset.height)

    return graph.Clip(
        source=background,
        frames=round(hold * preset.fps),
        move="still",
        texts=specs,
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    photo_paths = collect_images(args.images)
    caption_lines = captions_mod.load(args.captions, len(photo_paths), photo_paths)

    preset = presets.resolve(
        args.preset, seconds=args.seconds, transition=args.transition,
        zoom=args.zoom, fps=args.fps,
    )
    if args.fit_music:
        if not args.music:
            raise SystemExit("--fit-music needs --music")
        if args.seconds is not None:
            print("note: --fit-music overrides --seconds")
        end_seconds = args.end_card_seconds if args.end_card else 0.0
        preset = presets.resolve(
            args.preset,
            seconds=_hold_for_music(args.music, len(photo_paths), preset.transition, end_seconds),
            transition=args.transition, zoom=args.zoom, fps=args.fps,
        )

    work_dir = tempfile.mkdtemp(prefix="broll_")
    try:
        clips = build_clips(args, preset, work_dir, photo_paths, caption_lines)
        has_text = any(clip.texts for clip in clips[: len(photo_paths)])
        scrim_path = None
        if has_text and not args.no_scrim:
            scrim_path = text.scrim(os.path.join(work_dir, "scrim.png"), preset.size)

        command = graph.build(
            clips, args.out, preset,
            work_dir=work_dir,
            scrim_path=scrim_path,
            music=args.music,
            music_volume=args.music_volume,
            grade=args.grade,
            transition_type=args.transition_type,
            crf=28 if args.preview else 18,
            x264_preset="veryfast" if args.preview else "slow",
        )
        if args.dry_run:
            print(" ".join(command))
            return

        length = graph.total_seconds(clips, preset.fps, preset.transition)
        print(
            f"{len(photo_paths)} photos"
            f"{' + end card' if args.end_card else ''}"
            f" -> {preset.width}x{preset.height} @ {preset.fps}fps, {length:.1f}s"
        )
        media.run(command, verbose=args.verbose)
        print(f"wrote {args.out}")
    finally:
        if args.keep_temp:
            print(f"temp files kept in {work_dir}")
        else:
            shutil.rmtree(work_dir, ignore_errors=True)
