#!/usr/bin/env python3
"""
walkthrough.py — turn a folder of photos into a cinematic walkthrough video.

Built for property listings: feed it the listing photos, get back a graded,
music-backed walkthrough with eased camera moves and clean titles, in
landscape (YouTube / portal) or vertical (Reels / TikTok / WhatsApp status).

    python3 walkthrough.py photos/ -o walkthrough.mp4 \
        --aspect 9:16 --title "Sky Eden @ Bedok" --subtitle "3BR · 1,076 sqft" \
        --music track.mp3 --grade warm

Everything is deterministic: the same photos and --seed always render the
same video, so re-runs after a tweak are comparable.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}

# --------------------------------------------------------------------------
# ffmpeg discovery
# --------------------------------------------------------------------------


def find_ffmpeg() -> str:
    """System ffmpeg if present, else the static binary from imageio-ffmpeg."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover - depends on environment
        sys.exit(
            "ffmpeg not found. Install it (apt install ffmpeg / brew install ffmpeg) "
            "or run: pip install imageio-ffmpeg"
        )


def run(cmd: list[str], quiet: bool = True) -> None:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write((proc.stderr or "")[-4000:] + "\n")
        raise SystemExit(f"ffmpeg failed ({proc.returncode}): {' '.join(cmd[:6])} ...")


# --------------------------------------------------------------------------
# Look: aspect ratios, colour grades, camera moves
# --------------------------------------------------------------------------

ASPECTS = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "1:1": (1, 1),
    "4:5": (4, 5),
    "2.39:1": (239, 100),
}

# Each grade is an ffmpeg filter chain applied after the camera move.
GRADES = {
    "none": "",
    "neutral": (
        "eq=contrast=1.05:saturation=1.03:gamma=0.99,"
        "vignette=PI/6,unsharp=5:5:0.35"
    ),
    # Golden, estate-agent friendly. Warms highlights, cools shadows slightly.
    "warm": (
        "eq=contrast=1.08:saturation=1.07:gamma=0.97,"
        "colorbalance=rs=0.02:bs=-0.04:rm=0.03:bm=-0.02:rh=0.05:bh=-0.03,"
        "vignette=PI/5,unsharp=5:5:0.5"
    ),
    # Cooler, architectural / new-launch look.
    "cool": (
        "eq=contrast=1.10:saturation=0.97:gamma=0.98,"
        "colorbalance=rs=-0.04:bs=0.06:rm=-0.01:bm=0.02:rh=0.04:bh=-0.02,"
        "vignette=PI/5,unsharp=5:5:0.45"
    ),
    # Low-contrast filmic with a lifted black point.
    "film": (
        "curves=all='0/0.045 0.5/0.5 1/0.96',"
        "eq=contrast=1.04:saturation=0.94,"
        "colorbalance=rs=0.03:bs=0.04:rh=0.03:bh=-0.04,"
        "vignette=PI/4.5,unsharp=5:5:0.4"
    ),
}

MOVES = [
    "push_in",
    "pull_out",
    "pan_right",
    "pan_left",
    "tilt_down",
    "tilt_up",
    "push_in_right",
    "push_in_left",
]

TRANSITIONS = {
    "dissolve": ["fade"],
    "cinematic": ["fade", "fade", "fadeblack", "smoothleft"],
    "energetic": ["slideleft", "smoothleft", "fade", "slideup"],
    "cut": [],
}


@dataclass
class Shot:
    path: Path
    duration: float
    move: str
    caption: str = ""
    zoom: float = 1.16
    fit: str = ""  # overrides the plan-wide fit; floorplans want "blur"


@dataclass
class Plan:
    shots: list[Shot]
    width: int
    height: int
    fps: int
    transition: float
    transition_kinds: list[str]
    grade: str
    grain: float
    letterbox: bool
    title: str = ""
    subtitle: str = ""
    end_card: str = ""
    accent: str = "#E8C37A"
    fit: str = "cover"
    max_crop: float = 0.38
    spec_at: int = 0
    spec_rows: list[tuple[str, str]] = field(default_factory=list)
    spec_note: str = ""
    agent_photo: Path | None = None
    agent_name: str = ""
    agent_tag: str = ""
    agent_phone: str = ""
    music: Path | None = None
    music_gain: float = 0.0
    fonts: dict = field(default_factory=dict)

    @property
    def total(self) -> float:
        n = len(self.shots)
        overlap = self.transition * max(0, n - 1)
        return sum(s.duration for s in self.shots) - overlap


# --------------------------------------------------------------------------
# Camera moves as zoompan expressions
# --------------------------------------------------------------------------


def ease(frames: int) -> str:
    """Cubic ease-in-out over the shot, as an ffmpeg expression in `on`."""
    if frames <= 1:
        return "0"
    p = f"(on/{frames - 1})"
    return f"if(lt({p},0.5),4*pow({p},3),1-pow(-2*{p}+2,3)/2)"


def zoompan_expr(move: str, frames: int, zmax: float) -> tuple[str, str, str]:
    """Return (z, x, y) expressions for one camera move.

    x/y are the top-left of the crop window in input pixels; the window is
    iw/zoom x ih/zoom, so the pannable range is iw-iw/zoom. Moves keep an 8%
    margin at each end so the frame never slams into the edge of the photo.
    """
    e = ease(frames)
    lo, hi = 0.08, 0.92  # keep the pan off the extreme edges
    span = f"({lo}+({hi}-{lo})*{e})"
    rspan = f"({hi}-({hi}-{lo})*{e})"
    cx, cy = "(iw/2-(iw/zoom/2))", "(ih/2-(ih/zoom/2))"

    if move == "push_in":
        return f"1+{zmax - 1:.4f}*{e}", cx, cy
    if move == "pull_out":
        return f"{zmax:.4f}-{zmax - 1:.4f}*{e}", cx, cy
    if move == "pan_right":
        return f"{zmax:.4f}", f"{span}*(iw-iw/zoom)", cy
    if move == "pan_left":
        return f"{zmax:.4f}", f"{rspan}*(iw-iw/zoom)", cy
    if move == "tilt_down":
        return f"{zmax:.4f}", cx, f"{span}*(ih-ih/zoom)"
    if move == "tilt_up":
        return f"{zmax:.4f}", cx, f"{rspan}*(ih-ih/zoom)"
    if move == "push_in_right":
        return f"1+{zmax - 1:.4f}*{e}", f"(0.35+0.30*{e})*(iw-iw/zoom)", cy
    if move == "push_in_left":
        return f"1+{zmax - 1:.4f}*{e}", f"(0.65-0.30*{e})*(iw-iw/zoom)", cy
    raise ValueError(f"unknown move: {move}")


def pick_moves(count: int, seed: int) -> list[str]:
    """Vary the moves so consecutive shots never repeat or mirror each other."""
    rng = random.Random(seed)
    order = ["push_in", "pan_right", "pull_out", "tilt_down", "push_in_left",
             "pan_left", "push_in", "tilt_up", "push_in_right", "pull_out"]
    rng.shuffle(order)
    out: list[str] = []
    for i in range(count):
        cand = order[i % len(order)]
        if out and cand == out[-1]:
            cand = order[(i + 3) % len(order)]
        out.append(cand)
    return out


# --------------------------------------------------------------------------
# Image prep
# --------------------------------------------------------------------------


def collect_photos(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            paths.extend(
                sorted(
                    q for q in p.iterdir()
                    if q.suffix.lower() in IMAGE_SUFFIXES and not q.name.startswith(".")
                )
            )
        elif p.is_file():
            paths.append(p)
        else:
            sys.exit(f"not found: {item}")
    if not paths:
        sys.exit("no photos found")
    return paths


def prepare_photo(
    src: Path, dst: Path, width: int, height: int, oversample: float,
    fit: str = "cover", max_crop: float = 0.38,
) -> None:
    """Compose one photo to the output aspect and upsample.

    zoompan truncates its crop offsets to whole input pixels, so feeding it an
    oversampled frame is what keeps the move smooth instead of stepping.

    fit="cover" crops to fill. That is right for a 16:9 cut, but taking a 9:16
    slice out of a 4:3 room photo throws away most of the room. fit="blur"
    keeps the whole photo and fills the gap with a blurred, darkened copy of
    itself; fit="smart" is the middle ground and usually the one you want for
    vertical — it crops up to max_crop of the long edge, so the photo fills
    most of the frame without the room being cut in half.
    """
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        tw = min(int(width * oversample), 6000)
        th = max(2, round(tw * height / width))

        if fit == "smart":
            # Crop part of the way towards the frame aspect, not all of it.
            frame_a = width / height
            src_a = im.width / im.height
            if src_a > frame_a:
                target_a = max(frame_a, src_a * (1 - max_crop))
            else:
                target_a = min(frame_a, src_a / (1 - max_crop))
            if target_a >= src_a:
                cw, ch = im.width, max(2, round(im.width / target_a))
            else:
                cw, ch = max(2, round(im.height * target_a)), im.height
            im = ImageOps.fit(im, (cw, ch), Image.LANCZOS, centering=(0.5, 0.45))

        if fit in ("blur", "smart"):
            # Blur a small copy and scale it up: same look, far less work.
            small = ImageOps.fit(im, (max(1, tw // 6), max(1, th // 6)), Image.LANCZOS)
            bg = small.filter(ImageFilter.GaussianBlur(small.width / 22)).resize(
                (tw, th), Image.LANCZOS
            )
            bg = Image.blend(bg, Image.new("RGB", (tw, th), (16, 16, 18)), 0.32)

            scale = min(tw * 0.98 / im.width, th * 0.92 / im.height)
            fg = im.resize(
                (max(2, int(im.width * scale)), max(2, int(im.height * scale))), Image.LANCZOS
            )
            # Sit the photo slightly high; captions live along the bottom.
            out = bg
            out.paste(fg, ((tw - fg.width) // 2, int((th - fg.height) * 0.42)))
        else:
            out = ImageOps.fit(im, (tw, th), method=Image.LANCZOS, centering=(0.5, 0.45))

        if out.width % 2 or out.height % 2:
            out = out.crop((0, 0, out.width - out.width % 2, out.height - out.height % 2))
        out.save(dst, "PNG", compress_level=1)


# --------------------------------------------------------------------------
# Text cards (this ffmpeg build has no drawtext, and Pillow handles CJK better)
# --------------------------------------------------------------------------

FONT_CANDIDATES = {
    "bold": [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    "regular": [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ],
    "cjk": [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ],
}


def has_cjk(text: str) -> bool:
    return any(ord(c) > 0x2E80 for c in text)


def load_font(kind: str, size: int, text: str) -> ImageFont.FreeTypeFont:
    names = FONT_CANDIDATES["cjk"] if has_cjk(text) else FONT_CANDIDATES[kind]
    for name in names + FONT_CANDIDATES["regular"] + FONT_CANDIDATES["cjk"]:
        if os.path.exists(name):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
    return ImageFont.load_default()


def hex_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return tuple(int(v[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def scrim(card: Image.Image, height_frac: float, strength: int, top: bool = False) -> None:
    """Paint a soft dark gradient so text stays readable over any photo."""
    w, h = card.size
    band = max(1, int(h * height_frac))
    grad = Image.new("L", (1, band))
    for y in range(band):
        t = y / max(1, band - 1)
        a = t if not top else 1 - t
        grad.putpixel((0, y), int(strength * (a**1.6)))
    grad = grad.resize((w, band))
    layer = Image.new("RGBA", (w, band), (0, 0, 0, 0))
    layer.putalpha(grad)
    card.alpha_composite(layer, (0, h - band if not top else 0))


def tracked_text(draw, xy, text, font, fill, tracking: int = 0, anchor_center=False, width=0):
    """Draw text with optional letter-spacing (Pillow has no tracking option)."""
    if not tracking:
        if anchor_center:
            tw = draw.textlength(text, font=font)
            xy = (xy[0] - tw / 2, xy[1])
        draw.text(xy, text, font=font, fill=fill)
        return
    total = sum(draw.textlength(c, font=font) + tracking for c in text) - tracking
    x = xy[0] - total / 2 if anchor_center else xy[0]
    for c in text:
        draw.text((x, xy[1]), c, font=font, fill=fill)
        x += draw.textlength(c, font=font) + tracking


def text_width(draw, text: str, font, tracking: int = 0) -> float:
    if not tracking:
        return draw.textlength(text, font=font)
    return sum(draw.textlength(c, font=font) + tracking for c in text) - tracking


def fit_font(draw, kind: str, text: str, size: float, max_w: float, tracking_frac: float = 0.0):
    """Shrink a line until it fits the frame width.

    Sizes derived from the frame height alone overflow a 9:16 crop, so every
    headline is measured and stepped down until it actually fits.
    """
    size = max(10, int(size))
    while size > 10:
        font = load_font(kind, size, text)
        tracking = int(size * tracking_frac)
        if text_width(draw, text, font, tracking) <= max_w:
            return font, tracking
        size = int(size * 0.92)
    font = load_font(kind, size, text)
    return font, int(size * tracking_frac)


def make_title_card(plan: Plan) -> Image.Image:
    w, h = plan.width, plan.height
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    scrim(card, 0.55 if h >= w else 0.5, 190)
    d = ImageDraw.Draw(card)
    unit = min(w, h) / 1000  # short edge, so portrait text does not overflow
    max_w = w * 0.86

    title = plan.title if has_cjk(plan.title) else plan.title.upper()
    sub = plan.subtitle
    f_title, tr_title = fit_font(
        d, "bold", title, 62 * unit, max_w, 0.0 if has_cjk(title) else 0.045
    )
    t_size = f_title.size

    base_y = h - int(150 * unit) - (t_size if sub else 0)
    tracked_text(d, (w / 2, base_y), title, f_title, (255, 255, 255, 255),
                 tr_title, anchor_center=True)

    rule_y = base_y + t_size + int(22 * unit)
    rule_w = int(min(w * 0.10, max_w))
    d.rectangle(
        [w / 2 - rule_w / 2, rule_y, w / 2 + rule_w / 2, rule_y + max(2, int(3 * unit))],
        fill=hex_rgb(plan.accent) + (235,),
    )
    if sub:
        f_sub, tr_sub = fit_font(d, "regular", sub, 27 * unit, max_w, 0.05)
        tracked_text(d, (w / 2, rule_y + int(26 * unit)), sub, f_sub,
                     (240, 238, 234, 235), tr_sub, anchor_center=True)
    return card


def make_caption_card(plan: Plan, text: str) -> Image.Image:
    w, h = plan.width, plan.height
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    scrim(card, 0.28, 150)
    d = ImageDraw.Draw(card)
    unit = min(w, h) / 1000
    x = int(w * 0.075)
    bar_w = max(3, int(4 * unit))
    gap = int(18 * unit)
    f, _ = fit_font(d, "regular", text, 32 * unit, w - x * 2 - bar_w - gap)
    y = h - int(105 * unit)
    d.rectangle([x, y + int(4 * unit), x + bar_w, y + f.size],
                fill=hex_rgb(plan.accent) + (255,))
    d.text((x + bar_w + gap, y), text, font=f, fill=(255, 255, 255, 240))
    return card


def make_end_card(plan: Plan) -> Image.Image:
    w, h = plan.width, plan.height
    card = Image.new("RGBA", (w, h), (0, 0, 0, 150))
    d = ImageDraw.Draw(card)
    unit = min(w, h) / 1000
    max_w = w * 0.86
    lines = plan.end_card.split("|")

    fitted = []
    for i, line in enumerate(lines):
        size = 50 * unit if i == 0 else 29 * unit
        kind = "bold" if i == 0 else "regular"
        tr_frac = 0.0 if has_cjk(line) else 0.05
        fitted.append((line, kind, *fit_font(d, kind, line, size, max_w, tr_frac)))

    heights = [f.size * 1.55 for _, _, f, _ in fitted]
    y = h / 2 - sum(heights) / 2
    for i, (line, _, f, tr) in enumerate(fitted):
        colour = (255, 255, 255, 250) if i == 0 else (235, 233, 228, 225)
        tracked_text(d, (w / 2, y), line, f, colour, tr, anchor_center=True)
        y += heights[i]
    return card


def make_spec_card(plan: Plan) -> Image.Image:
    """A panel of hard numbers — the part a buyer screenshots."""
    w, h = plan.width, plan.height
    card = Image.new("RGBA", (w, h), (0, 0, 0, 96))
    d = ImageDraw.Draw(card)
    unit = min(w, h) / 1000
    accent = hex_rgb(plan.accent)

    pad = int(46 * unit)
    row_h = int(62 * unit)
    panel_w = int(w * 0.84)
    head_h = int(78 * unit)
    note_h = int(58 * unit) if plan.spec_note else 0
    panel_h = head_h + row_h * len(plan.spec_rows) + pad + note_h
    x0 = (w - panel_w) // 2
    y0 = (h - panel_h) // 2

    d.rounded_rectangle([x0, y0, x0 + panel_w, y0 + panel_h],
                        radius=int(18 * unit), fill=(14, 14, 16, 208))
    d.rectangle([x0, y0, x0 + panel_w, y0 + max(3, int(4 * unit))], fill=accent + (255,))

    f_lab, _ = fit_font(d, "regular", "M", 25 * unit, panel_w * 0.45)
    y = y0 + head_h - int(24 * unit)
    for label, value in plan.spec_rows:
        fl, _ = fit_font(d, "regular", label, 25 * unit, panel_w * 0.44)
        fv, _ = fit_font(d, "bold", value, 29 * unit, panel_w * 0.50)
        d.text((x0 + pad, y + int(3 * unit)), label, font=fl, fill=(186, 184, 178, 235))
        vw = text_width(d, value, fv)
        d.text((x0 + panel_w - pad - vw, y), value, font=fv, fill=(255, 255, 255, 245))
        y += row_h
        if (label, value) != plan.spec_rows[-1]:
            d.rectangle([x0 + pad, y - int(14 * unit), x0 + panel_w - pad,
                         y - int(14 * unit) + 1], fill=(255, 255, 255, 30))

    if plan.spec_note:
        fn, tr = fit_font(d, "bold", plan.spec_note, 34 * unit, panel_w - pad * 2, 0.0)
        tracked_text(d, (w / 2, y + int(8 * unit)), plan.spec_note, fn,
                     accent + (255,), tr, anchor_center=True)
    return card


def circular(im: Image.Image, size: int, ring: tuple, ring_w: int) -> Image.Image:
    """Square-crop a portrait into a ringed circle."""
    src = ImageOps.fit(im.convert("RGB"), (size, size), Image.LANCZOS, centering=(0.5, 0.42))
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    out.paste(src, (0, 0), mask.resize((size, size), Image.LANCZOS))
    d = ImageDraw.Draw(out)
    half = ring_w / 2
    d.ellipse([half, half, size - 1 - half, size - 1 - half], outline=ring + (255,), width=ring_w)
    return out


def make_agent_card(plan: Plan) -> Image.Image:
    """Closing call to action: hook, face, name, number — in that reading order.

    The face carries it. A buyer saves a person, not a phone number.
    """
    w, h = plan.width, plan.height
    card = Image.new("RGBA", (w, h), (10, 10, 12, 214))
    d = ImageDraw.Draw(card)
    unit = min(w, h) / 1000
    accent = hex_rgb(plan.accent)
    max_w = w * 0.86

    lines = [ln for ln in plan.end_card.split("|") if ln.strip()] if plan.end_card else []
    avatar = int(min(w * 0.46, h * 0.28))

    # Lay the card out as a measured stack, then draw it centred as a block.
    stack: list[tuple] = []
    if lines:
        f, tr = fit_font(d, "bold", lines[0], 46 * unit, max_w,
                         0.0 if has_cjk(lines[0]) else 0.04)
        stack.append(("text", lines[0], f, tr, (255, 255, 255, 250), f.size * 1.7))
    stack.append(("avatar", None, None, 0, None, avatar + 30 * unit))
    if plan.agent_name:
        f, tr = fit_font(d, "bold", plan.agent_name, 34 * unit, max_w,
                         0.0 if has_cjk(plan.agent_name) else 0.05)
        stack.append(("text", plan.agent_name, f, tr, (255, 255, 255, 250), f.size * 1.35))
    if plan.agent_tag:
        f, tr = fit_font(d, "regular", plan.agent_tag, 23 * unit, max_w, 0.04)
        stack.append(("text", plan.agent_tag, f, tr, (188, 186, 180, 225), f.size * 1.9))
    for line in lines[1:]:
        f, tr = fit_font(d, "regular", line, 26 * unit, max_w, 0.03)
        stack.append(("text", line, f, tr, (226, 224, 218, 230), f.size * 1.6))
    if plan.agent_phone:
        f, tr = fit_font(d, "bold", plan.agent_phone, 32 * unit, max_w * 0.8, 0.03)
        stack.append(("pill", plan.agent_phone, f, tr, None, f.size + 52 * unit))

    y = (h - sum(item[5] for item in stack)) / 2
    for kind, text, font, tracking, colour, advance in stack:
        if kind == "avatar":
            if plan.agent_photo and plan.agent_photo.exists():
                with Image.open(plan.agent_photo) as portrait:
                    card.alpha_composite(
                        circular(portrait, avatar, accent, max(3, int(5 * unit))),
                        ((w - avatar) // 2, int(y)),
                    )
        elif kind == "pill":
            pw = text_width(d, text, font, tracking)
            px, py = int(22 * unit), int(16 * unit)
            d.rounded_rectangle(
                [w / 2 - pw / 2 - px, y, w / 2 + pw / 2 + px, y + font.size + py * 2],
                radius=int((font.size + py * 2) / 2), fill=accent + (255,),
            )
            tracked_text(d, (w / 2, y + py), text, font, (18, 16, 14, 255), tracking,
                         anchor_center=True)
        else:
            tracked_text(d, (w / 2, y), text, font, colour, tracking, anchor_center=True)
        y += advance
    return card


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render_shot(ff: str, shot: Shot, plan: Plan, work: Path, idx: int, verbose: bool) -> Path:
    prepped = work / f"src_{idx:03d}.png"
    prepare_photo(shot.path, prepped, plan.width, plan.height,
                  oversample=2.5 if (shot.fit or plan.fit) != "cover" else 3.0,
                  fit=shot.fit or plan.fit, max_crop=plan.max_crop)

    frames = max(2, int(round(shot.duration * plan.fps)))
    z, x, y = zoompan_expr(shot.move, frames, shot.zoom)

    chain = [
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={plan.width}x{plan.height}:fps={plan.fps}"
    ]
    if GRADES[plan.grade]:
        chain.append(GRADES[plan.grade])
    if plan.grain > 0:
        chain.append(f"noise=alls={int(plan.grain)}:allf=t+u")
    chain.append("format=yuv420p")

    script = work / f"vf_{idx:03d}.txt"
    script.write_text(",".join(chain))

    out = work / f"shot_{idx:03d}.mp4"
    run(
        [
            ff, "-y", "-loglevel", "error", "-i", str(prepped),
            "-filter_script:v", str(script),
            "-c:v", "libx264", "-crf", "16", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-r", str(plan.fps), str(out),
        ],
        quiet=not verbose,
    )
    prepped.unlink(missing_ok=True)
    return out


def free_slot(window: tuple[float, float], reserved: list[tuple[float, float]],
              gap: float = 0.35) -> tuple[float, float] | None:
    """Largest sub-window of `window` not colliding with anything reserved."""
    start, end = window
    best: tuple[float, float] | None = None
    edges = [start] + [b + gap for _, b in reserved] 
    for s0 in edges:
        if s0 >= end:
            continue
        e0 = end
        for a, b in reserved:
            if a - gap > s0:
                e0 = min(e0, a - gap)
        if e0 > s0 and (best is None or e0 - s0 > best[1] - best[0]):
            best = (s0, e0)
    return best


def build_overlays(plan: Plan, work: Path) -> list[tuple[Path, float, float]]:
    """Text overlays as (png, start, end) on the final timeline.

    Cards are scheduled so they never stack: the title owns the head of the
    film, the spec panel and closing card claim their own windows, and captions
    take whatever is left of their own shot. Two scrims on screen at once reads
    as a smudge, not a title.
    """
    items: list[tuple[Path, float, float]] = []
    reserved: list[tuple[float, float]] = []
    total = plan.total
    tail = plan.transition  # a caption should clear its own outgoing transition

    # Where each shot starts on the assembled timeline.
    starts, clock = [], 0.0
    for i, shot in enumerate(plan.shots):
        starts.append(clock)
        clock += shot.duration - (tail if i < len(plan.shots) - 1 else 0)

    if plan.title:
        end = min(0.6 + 4.0, max(2.2, plan.shots[0].duration - tail * 0.5))
        path = work / "card_title.png"
        make_title_card(plan).save(path)
        items.append((path, 0.6, end))
        reserved.append((0.6, end))

    if plan.spec_rows and len(plan.shots) > 1:
        i = (plan.spec_at - 1) if plan.spec_at else (1 if len(plan.shots) < 4 else 2)
        i = max(0, min(i, len(plan.shots) - 1))
        start = starts[i] + 0.35
        end = min(start + 4.2, starts[i] + plan.shots[i].duration - tail - 0.25)
        if end - start >= 1.5:
            path = work / "card_spec.png"
            make_spec_card(plan).save(path)
            items.append((path, start, end))
            reserved.append((start, end))

    closing = bool(plan.agent_photo or plan.agent_name or plan.agent_phone or plan.end_card)
    if closing:
        last = plan.shots[-1]
        span = min(4.0 if plan.agent_photo else 3.2, last.duration - tail - 0.2)
        start = max((reserved[-1][1] + 0.4) if reserved else 0.0, total - span)
        path = work / "card_close.png"
        card = make_agent_card(plan) if (plan.agent_photo or plan.agent_phone) else make_end_card(plan)
        card.save(path)
        items.append((path, start, total))
        reserved.append((start, total))

    reserved.sort()
    for i, shot in enumerate(plan.shots):
        if not shot.caption:
            continue
        window = (starts[i] + 0.45, starts[i] + shot.duration - tail - 0.25)
        slot = free_slot(window, reserved)
        if slot is None or slot[1] - slot[0] < 1.0:
            continue
        path = work / f"card_cap_{i:03d}.png"
        make_caption_card(plan, shot.caption).save(path)
        items.append((path, slot[0], slot[1]))

    items.sort(key=lambda it: it[1])
    return items


def assemble(ff: str, clips: list[Path], plan: Plan, work: Path, out: Path, verbose: bool) -> None:
    overlays = build_overlays(plan, work)
    total = plan.total

    cmd = [ff, "-y", "-loglevel", "error"]
    for c in clips:
        cmd += ["-i", str(c)]
    for png, _, _ in overlays:
        cmd += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(png)]
    if plan.music:
        cmd += ["-stream_loop", "-1", "-i", str(plan.music)]

    g: list[str] = []
    n = len(clips)

    # 1. Chain the shots together with transitions.
    if n == 1:
        g.append("[0:v]null[vx]")
    elif not plan.transition_kinds or plan.transition <= 0:
        g.append("".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vx]")
    else:
        prev, offset = "[0:v]", 0.0
        for i in range(1, n):
            kind = plan.transition_kinds[(i - 1) % len(plan.transition_kinds)]
            offset += plan.shots[i - 1].duration - plan.transition
            label = "[vx]" if i == n - 1 else f"[x{i}]"
            g.append(
                f"{prev}[{i}:v]xfade=transition={kind}:"
                f"duration={plan.transition:.3f}:offset={offset:.3f}{label}"
            )
            prev = label

    # 2. Fade up from black and out to black.
    g.append(f"[vx]fade=in:st=0:d=0.8,fade=out:st={max(0.0, total - 1.0):.3f}:d=1.0[vg]")

    # 3. Text overlays, each with its own alpha fade.
    cur = "[vg]"
    for k, (_, start, end) in enumerate(overlays):
        src = n + k
        fade = min(0.6, max(0.15, (end - start) / 4))
        g.append(
            f"[{src}:v]format=rgba,fade=in:st={start:.3f}:d={fade:.3f}:alpha=1,"
            f"fade=out:st={max(start, end - fade):.3f}:d={fade:.3f}:alpha=1[c{k}]"
        )
        label = "[vo]" if k == len(overlays) - 1 else f"[o{k}]"
        g.append(f"{cur}[c{k}]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'{label}")
        cur = label
    if not overlays:
        g.append("[vg]null[vo]")

    # 4. Optional 2.39:1 letterbox bars.
    if plan.letterbox:
        bar = int(plan.height * (1 - (plan.width / plan.height) / 2.39) / 2)
        bar = max(0, bar - bar % 2)
        if bar > 0:
            inner = plan.height - 2 * bar
            g.append(
                f"[vo]scale={plan.width}:{inner}:flags=lanczos,"
                f"pad={plan.width}:{plan.height}:0:{bar}:black[vf]"
            )
        else:
            g.append("[vo]null[vf]")
    else:
        g.append("[vo]null[vf]")

    if plan.music:
        aidx = n + len(overlays)
        g.append(
            f"[{aidx}:a]atrim=0:{total:.3f},asetpts=N/SR/TB,"
            f"afade=in:st=0:d=1.5,afade=out:st={max(0.0, total - 2.5):.3f}:d=2.5,"
            f"volume={plan.music_gain:.2f}dB[af]"
        )

    script = work / "graph.txt"
    script.write_text(";\n".join(g))

    cmd += ["-filter_complex_script", str(script), "-map", "[vf]"]
    if plan.music:
        cmd += ["-map", "[af]", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-r", str(plan.fps),
        "-movflags", "+faststart", "-t", f"{total:.3f}", str(out),
    ]
    run(cmd, quiet=not verbose)


# --------------------------------------------------------------------------
# Plan building
# --------------------------------------------------------------------------


def build_plan(args) -> Plan:
    if args.aspect not in ASPECTS:
        sys.exit(f"--aspect must be one of {', '.join(ASPECTS)}")
    aw, ah = ASPECTS[args.aspect]
    height = args.height
    width = round(height * aw / ah)
    width -= width % 2
    height -= height % 2

    shotlist = None
    if args.shotlist:
        shotlist = json.loads(Path(args.shotlist).read_text())

    if shotlist:
        base = Path(args.shotlist).parent
        entries = shotlist["shots"] if isinstance(shotlist, dict) else shotlist
        paths = [(base / e["photo"]) if not Path(e["photo"]).is_absolute() else Path(e["photo"])
                 for e in entries]
        captions = [e.get("caption", "") for e in entries]
        durations = [float(e.get("duration", args.duration)) for e in entries]
        moves = [e.get("move") for e in entries]
        fits = [e.get("fit", "") for e in entries]
    else:
        paths = collect_photos(args.photos)
        captions = [""] * len(paths)
        durations = [args.duration] * len(paths)
        moves = [None] * len(paths)
        fits = [""] * len(paths)
        if args.captions:
            lines = Path(args.captions).read_text().splitlines()
            for i, line in enumerate(lines[: len(paths)]):
                captions[i] = line.strip()

    auto = pick_moves(len(paths), args.seed)
    shots = [
        Shot(path=p, duration=d, move=(m or auto[i]), caption=c, zoom=args.zoom, fit=f)
        for i, (p, d, m, c, f) in enumerate(zip(paths, durations, moves, captions, fits))
    ]

    spec_rows: list[tuple[str, str]] = []
    if args.spec:
        for chunk in args.spec.split("|"):
            if "=" in chunk:
                label, value = chunk.split("=", 1)
                spec_rows.append((label.strip(), value.strip()))

    kinds = TRANSITIONS[args.transition]
    return Plan(
        shots=shots,
        width=width,
        height=height,
        fps=args.fps,
        transition=0.0 if not kinds else args.transition_duration,
        transition_kinds=kinds,
        grade=args.grade,
        grain=args.grain,
        letterbox=args.letterbox,
        title=args.title or "",
        subtitle=args.subtitle or "",
        end_card=args.end_card or "",
        accent=args.accent,
        fit=args.fit,
        max_crop=args.max_crop,
        spec_at=args.spec_at,
        spec_rows=spec_rows,
        spec_note=args.spec_note or "",
        agent_photo=Path(args.agent_photo) if args.agent_photo else None,
        agent_name=args.agent_name or "",
        agent_tag=args.agent_tag or "",
        agent_phone=args.agent_phone or "",
        music=Path(args.music) if args.music else None,
        music_gain=args.music_gain,
    )


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Turn photos into a cinematic walkthrough video.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("photos", nargs="*", help="photo files, or a folder of them (sorted by name)")
    p.add_argument("-o", "--output", default="walkthrough.mp4")
    p.add_argument("--shotlist", help="JSON shotlist: per-shot photo/caption/duration/move")
    p.add_argument("--captions", help="text file, one caption per line, matching photo order")

    p.add_argument("--aspect", default="16:9", choices=list(ASPECTS))
    p.add_argument("--height", type=int, default=1080, help="output height in pixels")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--duration", type=float, default=4.0, help="seconds per photo")

    p.add_argument("--grade", default="warm", choices=list(GRADES))
    p.add_argument("--grain", type=float, default=0, help="film grain strength, 0-20")
    p.add_argument("--zoom", type=float, default=1.16, help="camera move strength (1.0 = static)")
    p.add_argument("--letterbox", action="store_true", help="add 2.39:1 cinema bars")
    p.add_argument("--transition", default="cinematic", choices=list(TRANSITIONS))
    p.add_argument("--transition-duration", type=float, default=0.9)

    p.add_argument("--title")
    p.add_argument("--subtitle")
    p.add_argument("--end-card", help="closing text; use | to split lines")
    p.add_argument("--accent", default="#E8C37A", help="accent colour for rules and bars")
    p.add_argument("--fit", default="cover", choices=["cover", "smart", "blur"],
                   help="cover crops to fill; blur keeps the whole photo on a blurred "
                        "backdrop; smart crops part way, best for vertical")
    p.add_argument("--max-crop", type=float, default=0.38,
                   help="with --fit smart, most of the long edge it may crop away")

    p.add_argument("--spec", help="spec panel rows: \"Land=35' x 80'|Built-up=3,144 sqft\"")
    p.add_argument("--spec-note", help="headline under the spec rows, e.g. the price")
    p.add_argument("--spec-at", type=int, default=0,
                   help="which shot number the spec panel sits on (default: shot 3)")

    p.add_argument("--agent-photo", help="agent portrait for the closing card")
    p.add_argument("--agent-name")
    p.add_argument("--agent-tag", help="agency / licence line")
    p.add_argument("--agent-phone", help="shown in an accent pill")

    p.add_argument("--music", help="audio file; looped and faded to fit")
    p.add_argument("--music-gain", type=float, default=-3.0, help="dB applied to the music")

    p.add_argument("--seed", type=int, default=7, help="controls the camera-move shuffle")
    p.add_argument("--dry-run", action="store_true", help="print the shot plan and exit")
    p.add_argument("-v", "--verbose", action="store_true", help="show ffmpeg output")
    args = p.parse_args(argv)
    if not args.photos and not args.shotlist:
        p.error("give photos (or a folder), or --shotlist")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    plan = build_plan(args)

    print(f"{len(plan.shots)} shots · {plan.width}x{plan.height} @ {plan.fps}fps "
          f"· {plan.total:.1f}s · grade={plan.grade}")
    for i, s in enumerate(plan.shots, 1):
        cap = f"  “{s.caption}”" if s.caption else ""
        print(f"  {i:>2}. {s.path.name:<32} {s.move:<14} {s.duration:.1f}s{cap}")
    if args.dry_run:
        return 0

    ff = find_ffmpeg()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="walkthrough_") as tmp:
        work = Path(tmp)
        clips = []
        for i, shot in enumerate(plan.shots):
            print(f"  rendering shot {i + 1}/{len(plan.shots)} …", flush=True)
            clips.append(render_shot(ff, shot, plan, work, i, args.verbose))
        print("  assembling …", flush=True)
        assemble(ff, clips, plan, work, out, args.verbose)

    size = out.stat().st_size / 1e6
    print(f"✓ {out} ({size:.1f} MB, {plan.total:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
