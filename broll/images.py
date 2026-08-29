"""Preparing source photos: orientation, framing and the blurred backdrop."""

import os
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

# Photos are rendered at a multiple of the output size so that zoompan, which
# crops on the integer pixel grid of its input, does not visibly judder.
SUPERSAMPLE = 3

FILL_MODES = ("auto", "crop", "blur", "pad")
ANCHORS = {"center": 0.5, "top": 0.0, "bottom": 1.0}


@dataclass(frozen=True)
class Prepared:
    path: str
    # True when the photo could not fill the frame on its own and sits on a
    # backdrop. Letterboxed frames want gentler, zoom-led moves.
    letterboxed: bool


def _cover_scale(size: tuple[int, int], target: tuple[int, int]) -> float:
    return max(target[0] / size[0], target[1] / size[1])


def _crop_loss(size: tuple[int, int], target: tuple[int, int]) -> float:
    """Fraction of the photo's longer axis that a full-frame crop would discard."""
    src_ar = size[0] / size[1]
    tgt_ar = target[0] / target[1]
    kept = tgt_ar / src_ar if src_ar > tgt_ar else src_ar / tgt_ar
    return 1.0 - kept


def _crop_to_cover(img: Image.Image, target: tuple[int, int], anchor: float) -> Image.Image:
    scale = _cover_scale(img.size, target)
    scaled = img.resize(
        (max(round(img.width * scale), target[0]), max(round(img.height * scale), target[1])),
        Image.LANCZOS,
    )
    left = round((scaled.width - target[0]) * 0.5)
    top = round((scaled.height - target[1]) * anchor)
    return scaled.crop((left, top, left + target[0], top + target[1]))


def _trim(img: Image.Image, target: tuple[int, int], limit: float, anchor: float) -> Image.Image:
    """Shave up to `limit` off the axis the target does not want, no further."""
    src_ar = img.width / img.height
    tgt_ar = target[0] / target[1]
    if src_ar > tgt_ar:
        width = max(round(img.width * (1.0 - limit)), 1)
        left = round((img.width - width) * 0.5)
        return img.crop((left, 0, left + width, img.height))
    height = max(round(img.height * (1.0 - limit)), 1)
    top = round((img.height - height) * anchor)
    return img.crop((0, top, img.width, top + height))


def _backdrop(img: Image.Image, target: tuple[int, int], solid: str | None) -> Image.Image:
    """Build the layer behind a letterboxed photo.

    Blur is a low-frequency effect, so it is composed at a quarter size and
    scaled up - visually identical, and far cheaper on supersampled frames.
    """
    small = (max(target[0] // 4, 1), max(target[1] // 4, 1))
    if solid:
        return Image.new("RGB", small, solid)
    blurred = _crop_to_cover(img, small, 0.5).filter(
        ImageFilter.GaussianBlur(radius=max(small[0] // 22, 4))
    )
    return ImageEnhance.Brightness(blurred).enhance(0.62)


def _drop_shadow(frame: Image.Image, box: tuple[int, int, int, int]) -> None:
    """Lift the photo off its backdrop so the composite reads as deliberate."""
    size = frame.size
    spread = max(round(size[0] * 0.012), 4)
    shadow = Image.new("L", size, 0)
    ImageDraw.Draw(shadow).rectangle(
        [box[0] - spread, box[1] - spread, box[2] + spread, box[3] + spread], fill=170
    )
    frame.paste(
        Image.new("RGB", size, (0, 0, 0)),
        (0, 0),
        shadow.filter(ImageFilter.GaussianBlur(spread * 1.6)),
    )


def compose(
    img: Image.Image,
    target: tuple[int, int],
    *,
    fill: str = "auto",
    max_crop: float = 0.30,
    anchor: float = 0.5,
    pad_color: str | None = None,
) -> tuple[Image.Image, bool]:
    """Fit one photo to the output frame. Returns the frame and whether it is letterboxed."""
    if fill == "crop" or (fill == "auto" and _crop_loss(img.size, target) <= max_crop):
        return _crop_to_cover(img, target, anchor), False

    # Too much would be lost to a straight crop: trim only as far as allowed,
    # then float what is left on a backdrop so the whole photo survives.
    trimmed = _trim(img, target, max_crop, anchor) if fill == "auto" else img
    fitted = ImageOps.contain(trimmed, target, Image.LANCZOS)
    left = (target[0] - fitted.width) // 2
    top = (target[1] - fitted.height) // 2

    small = _backdrop(img, target, pad_color if fill == "pad" else None)
    scale = small.width / target[0]
    _drop_shadow(small, (
        round(left * scale), round(top * scale),
        round((left + fitted.width) * scale), round((top + fitted.height) * scale),
    ))

    frame = small.resize(target, Image.BICUBIC)
    frame.paste(fitted, (left, top))
    return frame, True


def prepare(
    paths: list[str],
    out_dir: str,
    size: tuple[int, int],
    *,
    fill: str = "auto",
    max_crop: float = 0.25,
    anchor: str = "center",
    pad_color: str | None = None,
    supersample: int = SUPERSAMPLE,
) -> list[Prepared]:
    """Normalise every photo to one identical, ffmpeg-friendly frame."""
    if fill not in FILL_MODES:
        raise SystemExit(f"unknown fill {fill!r} (choose from: {', '.join(FILL_MODES)})")
    if anchor not in ANCHORS:
        raise SystemExit(f"unknown crop anchor {anchor!r} (choose from: {', '.join(ANCHORS)})")

    target = (size[0] * supersample, size[1] * supersample)
    os.makedirs(out_dir, exist_ok=True)
    prepared: list[Prepared] = []

    for index, path in enumerate(paths):
        with Image.open(path) as src:
            # Phone photos carry their rotation in EXIF; ffmpeg ignores it.
            img = ImageOps.exif_transpose(src).convert("RGB")
        frame, letterboxed = compose(
            img, target, fill=fill, max_crop=max_crop,
            anchor=ANCHORS[anchor], pad_color=pad_color,
        )
        dest = os.path.join(out_dir, f"frame_{index:03d}.jpg")
        frame.save(dest, "JPEG", quality=95, subsampling=0)
        prepared.append(Prepared(dest, letterboxed))

    return prepared


def solid_frame(out_path: str, size: tuple[int, int], color: str, supersample: int = SUPERSAMPLE) -> str:
    """Render a flat colour frame, used as the end card's background."""
    Image.new("RGB", (size[0] * supersample, size[1] * supersample), color).save(
        out_path, "JPEG", quality=95, subsampling=0
    )
    return out_path
