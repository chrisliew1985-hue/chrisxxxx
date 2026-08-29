"""Text layers: rendered with Pillow, overlaid by ffmpeg.

Drawing type in Pillow rather than ffmpeg's drawtext buys exact measurement,
letter spacing and a genuinely soft drop shadow - and works on ffmpeg builds
that ship without drawtext.
"""

import os
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont


@dataclass
class TextSpec:
    text: str
    font: str
    size: int
    # Pixel offset, read according to `anchor`, or "center" to centre vertically.
    y: int | str
    fade_in_at: float
    fade_out_at: float
    fade: float = 0.45
    # Which edge of the text block `y` refers to: "top" or "bottom".
    anchor: str = "top"
    color: tuple[int, int, int] = (255, 255, 255)
    # Letter spacing as a fraction of the font size, so it survives resizing.
    tracking: float = 0.0
    line_spacing: int = 0
    shadow: float = 0.55
    # Darkens the whole frame behind this block, fading in and out with it.
    wash: float = 0.0


def _load(spec: TextSpec) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(spec.font, spec.size)
    except OSError as exc:
        raise SystemExit(f"could not open font {spec.font}: {exc}") from None


def _line_width(font: ImageFont.FreeTypeFont, line: str, tracking: float) -> float:
    if not tracking or not line:
        return font.getlength(line)
    return sum(font.getlength(ch) for ch in line) + tracking * (len(line) - 1)


def _units(line: str) -> tuple[list[str], str]:
    """Where a line may be broken, best separator first."""
    if "·" in line:
        return [part.strip() for part in line.split("·") if part.strip()], "  ·  "
    if " " in line:
        return line.split(" "), " "
    return list(line), ""


def _wrap_line(font, line: str, tracking: float, available: float) -> list[str]:
    """Break one line to fit, on spaces where there are any and on characters
    otherwise, which is what Chinese and Japanese text needs."""
    if _line_width(font, line, tracking) <= available:
        return [line]

    units, joiner = _units(line)
    rows, current = [], ""
    for unit in units:
        candidate = f"{current}{joiner}{unit}" if current else unit
        if current and _line_width(font, candidate, tracking) > available:
            rows.append(current)
            current = unit
        else:
            current = candidate
    if current:
        rows.append(current)
    return rows


def layout(spec: TextSpec, available: float, min_size: int = 10) -> None:
    """Wrap and, if still too wide, shrink until the block fits the frame."""
    while spec.size > min_size:
        font = _load(spec)
        tracking = spec.tracking * spec.size
        rows: list[str] = []
        for line in spec.text.split("\n"):
            rows += _wrap_line(font, line, tracking, available)
        if all(_line_width(font, row, tracking) <= available for row in rows):
            spec.text = "\n".join(rows)
            return
        spec.size = max(int(spec.size * 0.94), min_size)
    spec.text = "\n".join(spec.text.split("\n"))


def measure(spec: TextSpec) -> tuple[int, int]:
    """Width of the widest line, and the height of the whole block."""
    font = _load(spec)
    lines = spec.text.split("\n")
    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    tracking = spec.tracking * spec.size
    width = max((_line_width(font, line, tracking) for line in lines), default=0)
    height = len(lines) * line_height + (len(lines) - 1) * spec.line_spacing
    return round(width), round(height)


def _write(draw: ImageDraw.ImageDraw, spec: TextSpec, font, top: int, size, fill) -> None:
    lines = spec.text.split("\n")
    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    tracking = spec.tracking * spec.size
    for index, line in enumerate(lines):
        y = top + index * (line_height + spec.line_spacing)
        x = (size[0] - _line_width(font, line, tracking)) / 2
        if not tracking:
            draw.text((x, y), line, font=font, fill=fill)
            continue
        for char in line:
            draw.text((x, y), char, font=font, fill=fill)
            x += font.getlength(char) + tracking


def render(spec: TextSpec, size: tuple[int, int], out_path: str) -> str:
    """Draw one text block onto a transparent layer the size of the frame."""
    font = _load(spec)
    _, block_height = measure(spec)
    if spec.y == "center":
        top = (size[1] - block_height) // 2
    elif spec.anchor == "bottom":
        # Anchoring the block's bottom keeps the margin steady however many
        # lines a caption wrapped onto.
        top = int(spec.y) - block_height
    else:
        top = int(spec.y)

    layer = Image.new("RGBA", size, (0, 0, 0, round(255 * spec.wash)))
    if spec.shadow > 0:
        # A blurred copy behind the type keeps captions legible over bright walls.
        shade = Image.new("RGBA", size, (0, 0, 0, 0))
        offset = max(round(spec.size * 0.045), 2)
        _write(ImageDraw.Draw(shade), spec, font, top + offset, size,
               (0, 0, 0, round(255 * spec.shadow)))
        layer.alpha_composite(shade.filter(ImageFilter.GaussianBlur(max(spec.size * 0.10, 3))))

    _write(ImageDraw.Draw(layer), spec, font, top, size, (*spec.color, 255))
    layer.save(out_path)
    return out_path


def scrim(out_path: str, size: tuple[int, int], height: float = 0.38, strength: float = 0.62) -> str:
    """A soft bottom-up darkening overlay, so captions read over bright rooms."""
    width, full_height = size
    band = max(int(full_height * height), 1)
    column = Image.new("RGBA", (1, full_height), (0, 0, 0, 0))
    pixels = column.load()
    for offset in range(band):
        # offset 0 is the bottom row: darkest there, easing to nothing at the
        # top of the band. The exponent keeps that top edge from showing.
        ratio = (1 - offset / band) ** 2.2
        pixels[0, full_height - 1 - offset] = (0, 0, 0, round(255 * strength * ratio))
    column.resize((width, full_height), Image.BILINEAR).save(out_path)
    return out_path


def card(out_path: str, size: tuple[int, int], color: str) -> str:
    """A flat background frame, used behind the closing card."""
    Image.new("RGB", size, color).save(out_path, "JPEG", quality=95, subsampling=0)
    return out_path


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path
