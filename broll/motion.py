"""Ken Burns moves, expressed as ffmpeg zoompan expressions."""

import random

# Each move is (zoom_start, zoom_end, x_start, x_end, y_start, y_end).
# Zoom values are fractions of the configured amplitude: 0 = no zoom, 1 = full.
# Position values are fractions of the pannable range: 0 = hard left/top,
# 0.5 = centred, 1 = hard right/bottom.
MOVES: dict[str, tuple[float, float, float, float, float, float]] = {
    "push_in":       (0.0, 1.0, 0.50, 0.50, 0.50, 0.50),
    "pull_out":      (1.0, 0.0, 0.50, 0.50, 0.50, 0.50),
    "pan_right":     (1.0, 1.0, 0.12, 0.88, 0.50, 0.50),
    "pan_left":      (1.0, 1.0, 0.88, 0.12, 0.50, 0.50),
    "reveal_down":   (1.0, 1.0, 0.50, 0.50, 0.10, 0.90),
    "reveal_up":     (1.0, 1.0, 0.50, 0.50, 0.90, 0.10),
    "push_in_left":  (0.0, 1.0, 0.72, 0.44, 0.50, 0.50),
    "push_in_right": (0.0, 1.0, 0.28, 0.56, 0.50, 0.50),
    "pull_out_up":   (1.0, 0.0, 0.50, 0.50, 0.64, 0.44),
    "still":         (0.0, 0.0, 0.50, 0.50, 0.50, 0.50),
}

# A rotation that reads well back to back: never the same move twice, and
# pushes alternating with pulls so the film keeps breathing.
_ROTATION = [
    "push_in", "pan_right", "pull_out", "reveal_down", "push_in_left",
    "pan_left", "push_in", "reveal_up", "pull_out_up", "push_in_right",
]


def plan(count: int, seed: int = 0) -> list[str]:
    """Choose a move for each photo, deterministically for a given seed."""
    offset = random.Random(seed).randrange(len(_ROTATION))
    return [_ROTATION[(offset + i) % len(_ROTATION)] for i in range(count)]


def _term(start: float, end: float, smoothstep: str) -> str:
    """Render `start -> end` interpolation as an ffmpeg expression."""
    delta = end - start
    if abs(delta) < 1e-9:
        return f"{start:.6f}"
    return f"({start:.6f}{delta:+.6f}*{smoothstep})"


def expressions(move: str, frames: int, amplitude: float) -> tuple[str, str, str]:
    """Build the (z, x, y) zoompan expressions for one clip.

    Progress is eased with a smoothstep so each move starts and ends softly
    instead of snapping into motion.
    """
    try:
        z0f, z1f, x0, x1, y0, y1 = MOVES[move]
    except KeyError:
        known = ", ".join(sorted(MOVES))
        raise SystemExit(f"unknown move {move!r} (choose from: {known})") from None

    span = max(frames - 1, 1)
    progress = f"(on/{span})"
    smoothstep = f"({progress}*{progress}*(3-2*{progress}))"

    z = _term(1.0 + amplitude * z0f, 1.0 + amplitude * z1f, smoothstep)
    # (iw - iw/zoom) is the horizontal travel available at the current zoom;
    # at zoom 1 it collapses to 0 and the frame simply stays centred.
    x = f"(iw-iw/zoom)*{_term(x0, x1, smoothstep)}"
    y = f"(ih-ih/zoom)*{_term(y0, y1, smoothstep)}"
    return z, x, y
