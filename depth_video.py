#!/usr/bin/env python3
"""Turn an ordinary 2D video into depth-map and stereo-3D versions.

Depth comes from Depth Anything V2 (ViT-S) exported to ONNX, so the whole thing
runs on CPU with onnxruntime -- no GPU, no torch.

Pipeline
    decode (ffmpeg) -> optional letterbox crop -> per-frame depth inference
    -> temporally smoothed normalisation -> render outputs -> encode (ffmpeg)

Outputs (pick with --outputs):
    gray      grayscale depth map, near = bright
    color     depth map with a colour ramp
    sbs       full side-by-side stereo pair (left|right), for VR / 3D displays
    anaglyph  red-cyan glasses version
    compare   original on top of the colour depth map, for a quick look

Example
    python3 depth_video.py -i clip.mp4 -o out --outputs gray,color,sbs,anaglyph
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np
import onnxruntime as ort

MODEL_URL = (
    "https://github.com/fabio-sim/Depth-Anything-ONNX/releases/download/"
    "v2.0.0/depth_anything_v2_vits.onnx"
)
MODEL_SIZE = 518  # the exported graph has a fixed 1x3x518x518 input
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

COLORMAPS = {
    "inferno": cv2.COLORMAP_INFERNO,
    "magma": cv2.COLORMAP_MAGMA,
    "turbo": cv2.COLORMAP_TURBO,
    "viridis": cv2.COLORMAP_VIRIDIS,
    "plasma": cv2.COLORMAP_PLASMA,
    "bone": cv2.COLORMAP_BONE,
}


# --------------------------------------------------------------------------- #
# ffmpeg helpers
# --------------------------------------------------------------------------- #

def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        sys.exit(f"error: {name} not found on PATH")
    return path


def probe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=True,
    ).stdout
    info = json.loads(out)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    num, den = (video.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": fps,
        "duration": float(info["format"].get("duration", 0.0)),
        "has_audio": has_audio,
    }


def detect_crop(path: str, duration: float, limit: int = 24) -> tuple[int, int, int, int] | None:
    """Find the letterbox/pillarbox-free region with ffmpeg's cropdetect."""
    start = min(2.0, duration / 10.0)
    span = max(5.0, min(40.0, duration - start))
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", f"{start}", "-i", path, "-t", f"{span}",
         "-vf", f"cropdetect=limit={limit}:round=2:reset=0", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", proc.stderr)
    if not found:
        return None
    # cropdetect widens its guess as it goes; the last line is the safest.
    w, h, x, y = (int(v) for v in found[-1])
    return w, h, x, y


def decoder(path: str, crop: tuple[int, int, int, int] | None, max_frames: int | None):
    """Yield BGR frames as numpy arrays, straight out of an ffmpeg pipe."""
    vf = []
    if crop:
        w, h, x, y = crop
        vf.append(f"crop={w}:{h}:{x}:{y}")
    cmd = ["ffmpeg", "-v", "error", "-i", path]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)


def encoder(path: str, width: int, height: int, fps: float,
            audio_from: str | None, crf: int, preset: str):
    """An ffmpeg process that takes raw BGR frames on stdin."""
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{width}x{height}", "-r", f"{fps}", "-i", "-"]
    if audio_from:
        cmd += ["-i", audio_from, "-map", "0:v:0", "-map", "1:a:0",
                "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


# --------------------------------------------------------------------------- #
# depth
# --------------------------------------------------------------------------- #

def load_model(model_path: str, threads: int) -> ort.InferenceSession:
    if not os.path.exists(model_path):
        sys.exit(
            f"error: model not found at {model_path}\n"
            f"       download it with:\n"
            f"       curl -L -o {model_path} {MODEL_URL}"
        )
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])


def infer_depth(session, input_name: str, frame_bgr: np.ndarray) -> np.ndarray:
    """Return raw inverse-depth (bigger = nearer) at the model's own resolution."""
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    small = cv2.resize(rgb, (MODEL_SIZE, MODEL_SIZE), interpolation=cv2.INTER_CUBIC)
    x = small.astype(np.float32) / 255.0
    x = (x - IMAGENET_MEAN) / IMAGENET_STD
    x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
    return session.run(None, {input_name: x})[0][0]


def smooth_series(values: np.ndarray, alpha: float) -> np.ndarray:
    """Forward+backward EMA -- kills per-frame flicker without a phase shift."""
    if alpha >= 1.0 or len(values) < 2:
        return values
    fwd = np.empty_like(values)
    acc = values[0]
    for i, v in enumerate(values):
        acc = alpha * v + (1 - alpha) * acc
        fwd[i] = acc
    bwd = np.empty_like(values)
    acc = fwd[-1]
    for i in range(len(fwd) - 1, -1, -1):
        acc = alpha * fwd[i] + (1 - alpha) * acc
        bwd[i] = acc
    return bwd


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

def stereo_pair(frame: np.ndarray, norm_depth: np.ndarray,
                divergence_px: float, convergence: float):
    """Depth-image-based rendering: one frame + its depth -> a left/right pair.

    Inverse (backward) warping, so there are no holes to inpaint. Blurring the
    disparity horizontally keeps object edges from tearing.
    """
    h, w = norm_depth.shape
    disp = (norm_depth - convergence) * divergence_px
    disp = cv2.GaussianBlur(disp, (0, 0), sigmaX=max(w / 200.0, 1.0), sigmaY=1.0)

    xx, yy = np.meshgrid(np.arange(w, dtype=np.float32),
                         np.arange(h, dtype=np.float32))
    half = disp.astype(np.float32) * 0.5
    left = cv2.remap(frame, xx + half, yy, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)
    right = cv2.remap(frame, xx - half, yy, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_REPLICATE)
    return left, right


def anaglyph(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Red-cyan, Dubois-style mixing -- less ghosting than a raw channel swap."""
    l = left.astype(np.float32)
    r = right.astype(np.float32)
    lb, lg, lr = l[..., 0], l[..., 1], l[..., 2]
    rb, rg, rr = r[..., 0], r[..., 1], r[..., 2]
    out_r = 0.437 * lr + 0.449 * lg + 0.164 * lb - 0.011 * rr - 0.032 * rg - 0.007 * rb
    out_g = -0.062 * lr - 0.062 * lg - 0.024 * lb + 0.377 * rr + 0.761 * rg + 0.009 * rb
    out_b = -0.048 * lr - 0.050 * lg - 0.017 * lb - 0.026 * rr - 0.093 * rg + 1.234 * rb
    return np.clip(np.stack([out_b, out_g, out_r], axis=-1), 0, 255).astype(np.uint8)


def restore_canvas(img: np.ndarray, canvas: tuple[int, int],
                   crop: tuple[int, int, int, int]) -> np.ndarray:
    """Paste a cropped frame back onto the original (letterboxed) canvas."""
    cw, ch = canvas
    w, h, x, y = crop
    out = np.zeros((ch, cw, 3), dtype=img.dtype)
    out[y:y + h, x:x + w] = img
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Make depth-map and stereo-3D versions of a video.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--outdir", default="out")
    ap.add_argument("--model", default="models/depth_anything_v2_vits.onnx")
    ap.add_argument("--outputs", default="gray,color,sbs,anaglyph",
                    help="comma-separated: gray,color,sbs,anaglyph,compare")
    ap.add_argument("--crop", default="auto",
                    help="'auto' letterbox detection, 'none', or W:H:X:Y")
    ap.add_argument("--pad", action="store_true",
                    help="paste the depth maps back onto the original canvas, "
                         "so gray/color keep the source framing")
    ap.add_argument("--colormap", default="inferno", choices=sorted(COLORMAPS))
    ap.add_argument("--divergence", type=float, default=2.0,
                    help="stereo strength, as a %% of frame width")
    ap.add_argument("--convergence", type=float, default=0.5,
                    help="0..1 depth that sits on the screen plane")
    ap.add_argument("--smooth", type=float, default=0.25,
                    help="EMA factor for depth normalisation (1.0 = off)")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--keep-cache", action="store_true")
    args = ap.parse_args()

    require_tool("ffmpeg")
    require_tool("ffprobe")

    wanted = [o.strip() for o in args.outputs.split(",") if o.strip()]
    unknown = set(wanted) - {"gray", "color", "sbs", "anaglyph", "compare"}
    if unknown:
        sys.exit(f"error: unknown output(s): {', '.join(sorted(unknown))}")

    os.makedirs(args.outdir, exist_ok=True)
    cache_dir = os.path.join(args.outdir, ".cache")
    os.makedirs(cache_dir, exist_ok=True)

    info = probe(args.input)
    canvas = (info["width"], info["height"])
    print(f"input   {args.input}")
    print(f"        {info['width']}x{info['height']} @ {info['fps']:.3f} fps, "
          f"{info['duration']:.1f}s, audio={info['has_audio']}")

    if args.crop == "auto":
        crop = detect_crop(args.input, info["duration"])
        if crop and (crop[0], crop[1]) == canvas:
            crop = None
    elif args.crop == "none":
        crop = None
    else:
        parts = args.crop.split(":")
        if len(parts) != 4:
            sys.exit("error: --crop must be 'auto', 'none', or W:H:X:Y")
        crop = tuple(int(p) for p in parts)  # type: ignore[assignment]

    if crop:
        w, h, x, y = crop
        print(f"crop    {w}x{h}+{x}+{y} (letterbox removed)")
    else:
        w, h = canvas
        print("crop    none")

    # ffmpeg's x264 wants even dimensions.
    if w % 2 or h % 2:
        sys.exit(f"error: working size {w}x{h} must be even; set --crop manually")

    session = load_model(args.model, args.threads)
    input_name = session.get_inputs()[0].name

    total = int(round(info["duration"] * info["fps"]))
    if args.max_frames:
        total = min(total, args.max_frames)

    # ---------------- pass 1: depth ---------------- #
    depth_path = os.path.join(cache_dir, "depth_f16.raw")
    depth_mm = np.memmap(depth_path, dtype=np.float16, mode="w+", shape=(total, h, w))
    lo = np.zeros(total, dtype=np.float32)
    hi = np.zeros(total, dtype=np.float32)

    proc = decoder(args.input, crop, args.max_frames)
    frame_bytes = w * h * 3
    n = 0
    t0 = time.time()
    print(f"\npass 1/2  depth inference ({total} frames)")
    while n < total:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        raw = infer_depth(session, input_name, frame)
        full = cv2.resize(raw, (w, h), interpolation=cv2.INTER_CUBIC)
        depth_mm[n] = full.astype(np.float16)
        lo[n], hi[n] = np.percentile(full, (2.0, 98.0))
        n += 1
        if n % 25 == 0 or n == total:
            done = time.time() - t0
            eta = done / n * (total - n)
            print(f"  {n}/{total}  {done/n:.2f}s/frame  eta {eta/60:.1f} min",
                  flush=True)
    proc.terminate()
    proc.stdout.close()
    proc.wait()

    if n == 0:
        sys.exit("error: decoded 0 frames")
    total = n
    lo, hi = lo[:total], hi[:total]
    depth_mm.flush()
    depth_mm = np.memmap(depth_path, dtype=np.float16, mode="r",
                         shape=(int(os.path.getsize(depth_path) / (h * w * 2)), h, w))

    # Smoothing the normalisation window instead of the depth itself keeps
    # detail while stopping the whole image from pulsing frame to frame.
    lo_s = smooth_series(lo, args.smooth)
    hi_s = smooth_series(hi, args.smooth)
    span = np.maximum(hi_s - lo_s, 1e-6)

    # ---------------- pass 2: render ---------------- #
    audio = None if (args.no_audio or not info["has_audio"]) else args.input
    pad = args.pad and crop is not None
    out_w, out_h = (canvas if pad else (w, h))

    writers: dict[str, subprocess.Popen] = {}
    paths: dict[str, str] = {}

    def add(key: str, name: str, ww: int, hh: int) -> None:
        p = os.path.join(args.outdir, name)
        paths[key] = p
        writers[key] = encoder(p, ww, hh, info["fps"], audio, args.crf, args.preset)

    if "gray" in wanted:
        add("gray", "depth_gray.mp4", out_w, out_h)
    if "color" in wanted:
        add("color", "depth_color.mp4", out_w, out_h)
    if "sbs" in wanted:
        add("sbs", "stereo_sbs.mp4", w * 2, h)
    if "anaglyph" in wanted:
        add("anaglyph", "anaglyph_red_cyan.mp4", w, h)
    if "compare" in wanted:
        add("compare", "compare.mp4", w, h * 2)

    div_px = args.divergence / 100.0 * w
    cmap = COLORMAPS[args.colormap]

    proc = decoder(args.input, crop, args.max_frames)
    t0 = time.time()
    print(f"\npass 2/2  rendering {', '.join(wanted)}")
    for i in range(total):
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        d = depth_mm[i].astype(np.float32)
        norm = np.clip((d - lo_s[i]) / span[i], 0.0, 1.0)
        gray8 = (norm * 255.0).astype(np.uint8)

        if "gray" in writers:
            img = cv2.cvtColor(gray8, cv2.COLOR_GRAY2BGR)
            writers["gray"].stdin.write(
                (restore_canvas(img, canvas, crop) if pad else img).tobytes())
        color_img = None
        if "color" in writers or "compare" in writers:
            color_img = cv2.applyColorMap(gray8, cmap)
        if "color" in writers:
            writers["color"].stdin.write(
                (restore_canvas(color_img, canvas, crop) if pad else color_img).tobytes())
        if "compare" in writers:
            writers["compare"].stdin.write(np.vstack([frame, color_img]).tobytes())
        if "sbs" in writers or "anaglyph" in writers:
            left, right = stereo_pair(frame, norm, div_px, args.convergence)
            if "sbs" in writers:
                writers["sbs"].stdin.write(np.hstack([left, right]).tobytes())
            if "anaglyph" in writers:
                writers["anaglyph"].stdin.write(anaglyph(left, right).tobytes())

        if (i + 1) % 100 == 0 or i + 1 == total:
            done = time.time() - t0
            print(f"  {i+1}/{total}  eta {done/(i+1)*(total-i-1)/60:.1f} min",
                  flush=True)

    proc.terminate()
    proc.stdout.close()
    proc.wait()
    for key, wr in writers.items():
        wr.stdin.close()
        if wr.wait() != 0:
            print(f"warning: encoder for {key} exited non-zero", file=sys.stderr)

    if not args.keep_cache:
        shutil.rmtree(cache_dir, ignore_errors=True)

    print("\ndone")
    for key in wanted:
        p = paths[key]
        if os.path.exists(p):
            print(f"  {p}  ({os.path.getsize(p)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
