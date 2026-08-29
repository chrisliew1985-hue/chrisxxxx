# broll

Turn a folder of still photos into a cinematic B-roll clip — Ken Burns moves,
cross-fades, captions, a colour grade and music — with nothing but Python,
Pillow and ffmpeg.

Built for property listings (vertical reels for Xiaohongshu / TikTok /
Instagram, or 16:9 for YouTube), but it works for any photo set.

By default this is edit-style B-roll: real photos, moved and graded. Pass
`--animate` and each photo is first turned into a real motion clip by
Higgsfield, which this then cuts together the same way.

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

## AI motion (optional)

`--animate` replaces the Ken Burns crop with a generated clip per photo:
Higgsfield animates the still, and everything downstream — cross-fades,
captions, title, end card, grade, music — works exactly as before.

```bash
npm i -g @higgsfield/cli
higgsfield auth login          # opens a browser

python3 -m broll photos/ --animate --preset property -o listing.mp4
```

Each clip's own length sets how long it is held, so pacing follows what the
model actually produced. Generated clips are written to an `animated/` folder
beside the output and **reused on the next run** — generation costs credits,
so delete a clip to force a new take.

| Flag | |
|---|---|
| `--animate-model` | default `seedance_2_0` |
| `--animate-prompt` | the motion prompt; the default tells the model to move the camera and leave the room alone |
| `--animate-aspect` | defaults to the preset's own shape |
| `--animate-dir` | where clips are kept and reused |
| `--animate-timeout` | per generation, default `20m` |

The CLI is found on `PATH` as `higgsfield` or `hf`, or via
`BROLL_HIGGSFIELD=/path/to/higgsfield`.

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
Chinese needs), and shrink only if wrapping is not enough. One short line
reads best — a wrapped caption can reach up into the photo once a move zooms
in on it. A font that can
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

Photos are rendered at twice the output size so the Ken Burns crop lands on
a fine enough pixel grid not to judder; `--supersample 3` smooths very slow
pans further, at a real cost in render time.

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
| `broll/animate.py` | driving the Higgsfield CLI for `--animate` |
