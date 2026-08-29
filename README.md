# chrisxxxx — photo → cinematic walkthrough

Turn a folder of listing photos into a graded, music-backed walkthrough video
with eased camera moves and clean titles. Landscape for portals and YouTube,
vertical for Reels / TikTok / WhatsApp status.

## Install

```bash
pip install -r requirements.txt
```

`imageio-ffmpeg` ships a static ffmpeg, so there is nothing else to install.
If you already have ffmpeg on your PATH it is used instead.

## Use it

```bash
python3 walkthrough.py photos/ -o walkthrough.mp4 \
    --title "Sky Eden @ Bedok" \
    --subtitle "3 BR · 1,076 sqft · 99-yr" \
    --captions captions.txt \
    --end-card "Viewing this weekend|Chris · 9XXX XXXX" \
    --music track.mp3
```

Photos are used in filename order, so name them in walking order —
`01_living.jpg`, `02_kitchen.jpg`, and so on.

A vertical cut for Reels, from the same photos:

```bash
python3 walkthrough.py photos/ -o reel.mp4 --aspect 9:16 --height 1920 \
    --duration 3 --grade cool --music track.mp3
```

`--dry-run` prints the shot plan (order, camera move, duration) without
rendering, which is the fast way to check the edit before committing to it.

## Options that matter

| Flag | What it does |
| --- | --- |
| `--aspect` | `16:9`, `9:16`, `1:1`, `4:5`, `2.39:1` |
| `--height` | Output height; width follows the aspect. 1080 default |
| `--duration` | Seconds per photo (default 4). 2.5–3 suits vertical |
| `--grade` | `warm` (default), `cool`, `film`, `neutral`, `none` |
| `--zoom` | Camera move strength. 1.0 is static, 1.16 default, 1.3 is aggressive |
| `--transition` | `cinematic` (default), `dissolve`, `energetic`, `cut` |
| `--letterbox` | 2.39:1 cinema bars |
| `--grain` | Film grain, 0–20. Try 4 |
| `--music` | Any audio file; looped and faded to fit the video |
| `--seed` | Reshuffles which camera move lands on which photo |

Text is rendered with Pillow, so Chinese, mixed 中英, and long titles all work —
headlines are measured and stepped down until they fit the frame.

### Captions

One line per photo, in the same order. Blank lines mean no caption.

```
Living · north-facing
Open kitchen
Master bedroom
```

### Shotlist (per-shot control)

For full control over order, timing, and which move lands on which photo, use a
shotlist instead of a folder — see `examples/shotlist.example.json`:

```bash
python3 walkthrough.py --shotlist shotlist.json -o walkthrough.mp4
```

Moves: `push_in`, `pull_out`, `pan_left`, `pan_right`, `tilt_up`, `tilt_down`,
`push_in_left`, `push_in_right`.

## How it works

Each photo is cover-fitted to the output aspect and upsampled 3x before the
camera move. That oversampling is the whole trick: ffmpeg's `zoompan` truncates
its crop offsets to whole input pixels, so at native resolution a slow move
visibly steps. At 3x, one input pixel is a third of an output pixel and the move
comes out smooth. Moves are eased in and out with a cubic curve rather than run
at constant speed, which is what separates a camera move from a slider.

Shots render individually, then chain together with cross-dissolves, take a
colour grade, and get their title cards composited on top with alpha fades.
Cards are scheduled so they never stack — the title owns the head of the film,
the end card owns the tail, captions take what is left of their own shot.

Same photos plus the same `--seed` always produce the same video.

## What this is not

This is real camera movement over your photos — the cinematic Ken Burns look,
graded and cut to music. It is not AI video generation: it cannot invent
geometry the camera never saw, so it will not walk you through a doorway into
the next room. For that you need a video model (Runway, Kling, Sora), and the
output of this tool makes a good input to one.
