"""Cut generated clips into a listing film, with a rhythm.

Where assemble_clips.py gives every shot the same length and the same slow
dissolve, this one takes a per-shot window, screen time, playback speed and
transition length. Uniform shots and long dissolves are what make a reel
feel flat; varying them, and cutting rather than dissolving, is the fix.
"""
"""Cut a set of generated clips into one vertical listing film."""
import os, re, subprocess, sys, urllib.request
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, TR = 1080, 1920, 30, 0.9
FF = os.environ.get("FF", "ffmpeg")
FONTS = ("/usr/share/fonts/truetype/Montserrat-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def font(size):
    for p in FONTS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    for root, _, fs in os.walk("/usr/share/fonts"):
        for f in sorted(fs):
            if f.lower().endswith((".ttf", ".otf")):
                return ImageFont.truetype(os.path.join(root, f), size)
    raise SystemExit("no font found")


def lw(f, line, tr):
    return f.getlength(line) if not tr else sum(f.getlength(c) for c in line) + tr * (len(line) - 1)


def wrap(f, text, tr, avail):
    rows = []
    for line in text.split("\n"):
        if lw(f, line, tr) <= avail or not line:
            rows.append(line); continue
        units, join = (line.split(" "), " ")
        cur = ""
        for u in units:
            cand = f"{cur}{join}{u}" if cur else u
            if cur and lw(f, cand, tr) > avail:
                rows.append(cur); cur = u
            else:
                cur = cand
        if cur:
            rows.append(cur)
    return rows


def _write(d, rows, f, tr, top, lh, sp, fill, dy=0):
    for i, row in enumerate(rows):
        x, y = (W - lw(f, row, tr)) / 2, top + i * (lh + sp) + dy
        if not tr:
            d.text((x, y), row, font=f, fill=fill)
        else:
            for c in row:
                d.text((x, y), c, font=f, fill=fill)
                x += f.getlength(c) + tr


def text_png(path, text, size, tracking=0.0, place="center", y=0, wash=0.0):
    """One transparent text layer, centred horizontally, with a soft shadow."""
    f, tr = font(size), tracking * size
    rows = wrap(f, text, tr, W * 0.84)
    asc, desc = f.getmetrics()
    lh, sp = asc + desc, round(size * 0.35)
    block = len(rows) * lh + (len(rows) - 1) * sp
    top = (H - block) // 2 if place == "center" else (y - block if place == "bottom" else y)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * wash)))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _write(ImageDraw.Draw(shade), rows, f, tr, top, lh, sp, (0, 0, 0, 150), max(round(size * .05), 2))
    layer.alpha_composite(shade.filter(ImageFilter.GaussianBlur(max(size * .10, 3))))
    _write(ImageDraw.Draw(layer), rows, f, tr, top, lh, sp, (255, 255, 255, 255))
    layer.save(path)
    return path


def scrim(path):
    band = int(H * .38)
    col = Image.new("RGBA", (1, H), (0, 0, 0, 0))
    px = col.load()
    for o in range(band):
        px[0, H - 1 - o] = (0, 0, 0, round(255 * .62 * (1 - o / band) ** 2.2))
    col.resize((W, H), Image.BILINEAR).save(path)
    return path


def card(path, color="#0d0f12"):
    Image.new("RGB", (W, H), color).save(path, "JPEG", quality=95)
    return path


def duration(path):
    err = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    m = re.search(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)", err)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def fetch(url, dest):
    if not (os.path.exists(dest) and os.path.getsize(dest)):
        urllib.request.urlretrieve(url, dest)
    return dest


def build(shots, title, subtitle, endcard, endcard_sub, out, work=".", grade=None):
    """shots: dicts of url, caption, start, dur, speed, cut.

    `dur` is screen time, `speed` how fast the source is played to fill it, and
    `cut` the dissolve into this shot - a few frames reads as a hard cut.
    """
    os.makedirs(work, exist_ok=True)
    scrim_png = scrim(f"{work}/scrim.png")
    chains, clips = [], []
    seen = {}

    for i, s in enumerate(shots):
        url = s["url"]
        if url not in seen:
            seen[url] = fetch(url, f"{work}/src{len(seen):02d}.mp4")
        dur, cap = s["dur"], s.get("caption", "")
        ov = []
        if cap:
            ov.append((text_png(f"{work}/cap{i}.png", cap, round(H * .034), 0.03,
                                "bottom", round(H * .90)), 0.15, dur))
        if s.get("title"):
            ov.append((text_png(f"{work}/t.png", title, round(H * .055), 0.10,
                                "center", 0, wash=0.32), 0.25, dur))
            if subtitle:
                ov.append((text_png(f"{work}/st.png", subtitle, round(H * .022), 0.16,
                                    "top", round(H * .60)), 0.5, dur))
        clips.append(dict(src=seen[url], start=s.get("start", 0.0), dur=dur,
                          speed=s.get("speed", 1.0), cut=s.get("cut", 0.06), ov=ov))

    if endcard:
        dur = 3.0
        ov = [(text_png(f"{work}/e1.png", endcard, round(H * .046), 0.06, "top",
                        round(H * .40)), 0.15, dur)]
        if endcard_sub:
            ov.append((text_png(f"{work}/e2.png", endcard_sub, round(H * .021), 0.10,
                                "top", round(H * .50)), 0.45, dur))
        clips.append(dict(src=card(f"{work}/end.jpg"), start=0.0, dur=dur,
                          speed=1.0, cut=0.5, ov=ov))

    inputs, index_of, count = [], {}, 0
    def add(args, path):
        nonlocal count
        inputs.extend(args + ["-i", path]); count += 1
        return count - 1

    for i, c in enumerate(clips):
        if c["src"].endswith(".jpg"):
            args = ["-loop", "1", "-framerate", str(FPS), "-t", f"{c['dur']:.3f}"]
        else:
            # Pull `dur * speed` seconds of source, then play it back in `dur`.
            args = ["-ss", f"{c['start']:.3f}", "-t", f"{c['dur'] * c['speed']:.3f}"]
        index_of[("clip", i)] = add(args, c["src"])
    index_of["scrim"] = add([], scrim_png)
    for i, c in enumerate(clips):
        for j, (png, _, _) in enumerate(c["ov"]):
            index_of[("ov", i, j)] = add(["-loop", "1", "-framerate", str(FPS),
                                          "-t", f"{c['dur']:.3f}"], png)

    chains.append(f"[{index_of['scrim']}:v]split={len(clips)}" +
                  "".join(f"[sc{i}]" for i in range(len(clips))))

    for i, c in enumerate(clips):
        v = f"[{index_of[('clip', i)]}:v]"
        if c["speed"] != 1.0:
            chains.append(f"{v}setpts=PTS/{c['speed']:.4f}[sp{i}]")
            v = f"[sp{i}]"
        chains.append(f"{v}split=2[bg{i}][fg{i}]")
        chains.append(f"[bg{i}]scale={W}:{H}:force_original_aspect_ratio=increase,"
                      f"crop={W}:{H},gblur=sigma=42,eq=brightness=-0.18[bb{i}]")
        chains.append(f"[fg{i}]scale={W}:-2[ff{i}]")
        node, stage, layers = f"[bb{i}][ff{i}]overlay=(W-w)/2:(H-h)/2", 0, [f"[sc{i}]"]
        for j, (png, tin, tout) in enumerate(c["ov"]):
            lab = f"[o{i}_{j}]"
            chains.append(f"[{index_of[('ov', i, j)]}:v]format=rgba,setpts=PTS-STARTPTS"
                          f",fade=t=in:st={tin:.2f}:d=0.25:alpha=1"
                          f",fade=t=out:st={max(tout - 0.3, tin):.2f}:d=0.3:alpha=1{lab}")
            layers.append(lab)
        for layer in layers:
            base = f"[b{i}_{stage}]"
            chains.append(f"{node}{base}")
            node = f"{base}{layer}overlay=0:0:format=auto"
            stage += 1
        chains.append(f"{node},setpts=PTS-STARTPTS,format=yuv420p,fps={FPS},"
                      f"trim=duration={c['dur']:.3f},setsar=1[c{i}]")

    cur, elapsed = "[c0]", clips[0]["dur"]
    for i in range(1, len(clips)):
        lab, t = f"[x{i}]", clips[i]["cut"]
        chains.append(f"{cur}[c{i}]xfade=transition=fade:duration={t:.3f}"
                      f":offset={elapsed - t:.3f}{lab}")
        cur, elapsed = lab, elapsed + clips[i]["dur"] - t

    grade = grade or ("eq=contrast=1.12:saturation=1.10:gamma=0.97,"
                      "colorbalance=rs=-0.015:bs=0.020:rh=0.030:bh=-0.015,"
                      "vignette=angle=PI/6.5,unsharp=5:5:0.55:5:5:0.0")
    chains.append(f"{cur}{grade},fade=t=in:st=0:d=0.4,"
                  f"fade=t=out:st={max(elapsed - 0.9, 0):.3f}:d=0.9,format=yuv420p[v]")

    cmd = ([FF, "-y", "-hide_banner", "-loglevel", "error", "-stats"] + inputs +
           ["-filter_complex", ";".join(chains), "-map", "[v]", "-c:v", "libx264",
            "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-r", str(FPS), "-t", f"{elapsed:.3f}", "-movflags", "+faststart", out])
    print(f"{len(clips)} shots -> {W}x{H} @ {FPS}fps, {elapsed:.1f}s", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print("\n".join((r.stdout + r.stderr).splitlines()[-25:]), flush=True)
        raise SystemExit(r.returncode)
    print("wrote", out, os.path.getsize(out), "bytes", flush=True)
