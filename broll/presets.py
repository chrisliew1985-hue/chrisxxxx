"""Output presets: canvas size, pacing and caption styling."""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Preset:
    name: str
    width: int
    height: int
    fps: int = 30
    # How long each photo is held on screen, including its share of the transitions.
    seconds: float = 3.4
    # Cross-fade length between two photos.
    transition: float = 0.75
    # Ken Burns amplitude: 0.12 means the move travels across 12% of the frame.
    zoom: float = 0.12
    # Caption geometry, as a fraction of the output height.
    caption_size: float = 0.030
    # Where the bottom of the caption block sits, as a fraction of the height.
    caption_y: float = 0.900
    title_size: float = 0.055
    end_card_size: float = 0.042

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height


PRESETS: dict[str, Preset] = {
    "vertical": Preset("vertical", 1080, 1920),
    "horizontal": Preset(
        "horizontal", 1920, 1080,
        seconds=3.8, transition=0.85, zoom=0.11,
        caption_size=0.042, caption_y=0.885, title_size=0.075, end_card_size=0.058,
    ),
    "square": Preset(
        "square", 1080, 1080,
        seconds=3.2, transition=0.7, zoom=0.13,
        caption_size=0.040, caption_y=0.890, title_size=0.070, end_card_size=0.055,
    ),
    # Property walkthroughs breathe more: longer holds, gentler moves, longer dissolves.
    "property": Preset(
        "property", 1080, 1920,
        seconds=4.2, transition=0.95, zoom=0.09,
        caption_size=0.029, caption_y=0.900, title_size=0.052, end_card_size=0.040,
    ),
    "property-wide": Preset(
        "property-wide", 1920, 1080,
        seconds=4.6, transition=1.05, zoom=0.08,
        caption_size=0.041, caption_y=0.885, title_size=0.072, end_card_size=0.056,
    ),
}

DEFAULT_PRESET = "vertical"


def resolve(name: str, **overrides) -> Preset:
    """Look up a preset and apply any explicitly supplied overrides."""
    try:
        preset = PRESETS[name]
    except KeyError:
        known = ", ".join(sorted(PRESETS))
        raise SystemExit(f"unknown preset {name!r} (choose from: {known})") from None
    supplied = {k: v for k, v in overrides.items() if v is not None}
    return replace(preset, **supplied) if supplied else preset
