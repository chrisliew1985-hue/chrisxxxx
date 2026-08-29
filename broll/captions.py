"""Caption sources and the fonts used to draw them."""

import json
import os
import re

CJK = re.compile(r"[\u3000-\u9fff\uf900-\ufaff\uff00-\uffef]")

# Ordered by preference; the first one present on the machine wins.
LATIN_FONTS = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arial.ttf",
)
CJK_FONTS = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyh.ttc",
)


def _first_present(candidates: tuple[str, ...]) -> str | None:
    return next((path for path in candidates if os.path.exists(path)), None)


def pick_font(text: str, override: str | None = None) -> str:
    """Choose a font that can actually render `text`."""
    if override:
        return override
    families = (CJK_FONTS, LATIN_FONTS) if CJK.search(text) else (LATIN_FONTS, CJK_FONTS)
    for family in families:
        found = _first_present(family)
        if found:
            return found
    raise SystemExit(
        "no usable font found; pass --font /path/to/font.ttf "
        "(a CJK font is required for Chinese captions)"
    )


def load(source: str | None, count: int, names: list[str]) -> list[str | None]:
    """Read captions from a .txt (one line per photo) or .json file.

    JSON may be a list in photo order, or an object keyed by file name.
    A blank line means "no caption for this photo".
    """
    if not source:
        return [None] * count

    with open(source, encoding="utf-8") as handle:
        raw = handle.read()

    if source.lower().endswith(".json"):
        data = json.loads(raw)
        if isinstance(data, dict):
            lookup = {os.path.basename(k): v for k, v in data.items()}
            values = [lookup.get(os.path.basename(name)) for name in names]
        elif isinstance(data, list):
            values = list(data)
        else:
            raise SystemExit(f"{source}: expected a JSON list or object")
    else:
        values = raw.splitlines()

    if len(values) < count:
        values += [None] * (count - len(values))
    elif len(values) > count:
        print(f"note: {source} has {len(values)} captions for {count} photos; extras ignored")
        values = values[:count]

    return [(str(v).strip() or None) if v is not None else None for v in values]
