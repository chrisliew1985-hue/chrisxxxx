# broll

Turn a folder of still photos into a cinematic B-roll clip — Ken Burns moves,
cross-fades, captions, a colour grade and music — with nothing but Python,
Pillow and ffmpeg.

Built for property listings (vertical reels for Xiaohongshu / TikTok /
Instagram, or 16:9 for YouTube), but it works for any photo set.

> This is edit-style B-roll: real photos, moved and graded. It does not
> animate the contents of a photo — that needs an image-to-video model.

## Install

```bash
pip install Pillow
# ffmpeg: apt install ffmpeg / brew install ffmpeg
# or, as a fallback that ships its own binary:
pip install imageio-ffmpeg
```

`broll` finds ffmpeg on `PATH`, falls back to `imageio-ffmpeg`, and honours
`BROLL_FFMPEG=/path/to/ffmpeg`. No `drawtext` support is required — all type
is rendered with Pillow and overlaid as image layers.

## Use

```bash
python3 -m broll photos/ -o listing.mp4
```

Photos are used in file-name order (`2` sorts before `10`), so number them
in the order you want them on screen.

A full listing reel:

```bash
python3 -m broll photos/ \
  --preset property \
  --captions captions.txt \
  --title "THE WOODLANDS" \
  --subtitle "Horizon Hills  ·  Brand New Cluster Home" \
  --end-card "RM 1.98 mil" \
  --end-card-sub "Chris Liew   REN 08014\nPropNex Realty\n+60 10-369 8656" \
  --music track.mp3 --fit-music \
  -o listing.mp4
```

See `examples/woodlands/` for that command as a runnable script.

## Presets

| Preset | Frame | Pace |
|---|---|---|
| `vertical` | 1080×1920 | 3.4s holds — Reels, TikTok, Xiaohongshu |
| `horizontal` | 1920×1080 | 3.8s holds — YouTube |
| `square` | 1080×1080 | 3.2s holds — feed posts |
| `property` | 1080×1920 | 4.2s holds, gentler moves, longer dissolves |
| `property-wide` | 1920×1080 | 4.6s holds, gentler moves |

Every preset value can be overridden: `--seconds`, `--transition`, `--zoom`,
`--fps`.

## How photos meet the frame

Landscape photos lose most of their width to a 9:16 crop. `--fill auto`
(the default) measures that loss: within `--max-crop` (default 0.30) it
crops to fill, and beyond it crops only that far and floats the rest on a
blurred, darkened copy of the same photo, with a soft drop shadow under it.

Force the behaviour with `--fill crop`, `--fill blur`, or `--fill pad`
(a flat `--pad-color` backdrop instead of a blur). `--crop-anchor
top|center|bottom` decides which part survives a crop.

EXIF rotation is applied before anything else, so phone photos come out the
right way up.

## Captions

`--captions` takes a `.txt` with one line per photo — a blank line leaves
that photo clean — or a `.json` list, or a `.json` object keyed by file name.

Long lines wrap on `·` first, then spaces, then characters (which is what
Chinese needs), and shrink only if wrapping is not enough. A font that can
render the text is picked automatically; override with `--font`.

Captions sit over a soft gradient that darkens the bottom of frame; turn it
off with `--no-scrim`.

## Music

`--music track.mp3` loops the track if it is shorter than the film, and
fades it in and out. `--fit-music` goes the other way and sets the per-photo
hold so the film lands on the end of the track.

## Grades

`--grade cinematic` (default) applies a gentle S-curve, cool shadows against
warm highlights, a vignette, light sharpening and a whisper of grain.
`clean` and `warm` are lighter touches; `none` leaves the photos alone.

## Rendering

`--preview` renders fast and rough for checking timing. Drop it for the
final file (CRF 18, x264 `slow`). `--dry-run` prints the ffmpeg command
instead of running it, and `--keep-temp` leaves the intermediate frames and
text layers on disk.

## Layout

| File | Role |
|---|---|
| `broll/cli.py` | argument parsing, and turning photos into clips |
| `broll/presets.py` | frame sizes and pacing |
| `broll/images.py` | orientation, framing, blurred backdrop |
| `broll/motion.py` | Ken Burns moves as zoompan expressions |
| `broll/text.py` | type rendering, wrapping, the gradient scrim |
| `broll/graph.py` | the ffmpeg filtergraph |
| `broll/media.py` | finding and running ffmpeg |
