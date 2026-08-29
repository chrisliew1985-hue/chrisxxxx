#!/usr/bin/env python3
"""Replace two actors' faces in a clip with two identities taken from stills.

The source video is the motion reference: every head angle, mouth shape, blink
and gesture stays exactly as shot. The PNGs are identity references only -- what
gets transferred is the face, not a cut-out of the photo.

Pipeline
    pass A  detect + embed every face, link into tracks, lock each track to one
            identity for its whole life (a track can never flip A <-> B)
    pass B  swap each locked face, paste through an XSeg occlusion mask so hands
            crossing the face stay in front, composite back, encode with ffmpeg

Models (all fetched by setup_face_replace.sh):
    buffalo_l          detection + ArcFace embeddings
    inswapper_128      the swap itself
    xseg_1             occlusion-aware face mask
    gfpgan_1.4         optional face restoration (off by default, see --enhance)
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import subprocess
import sys
import time

import cv2
import numpy as np
import onnxruntime as ort

from insightface.app import FaceAnalysis
from insightface.model_zoo import get_model
from insightface.utils import face_align


# --------------------------------------------------------------------------- #
# ffmpeg io
# --------------------------------------------------------------------------- #

def probe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    num, den = (v.get("r_frame_rate") or "30/1").split("/")
    return {"width": int(v["width"]), "height": int(v["height"]),
            "fps": float(num) / float(den),
            "duration": float(info["format"].get("duration", 0.0)),
            "has_audio": any(s["codec_type"] == "audio" for s in info["streams"])}


def decoder(path: str, crop):
    vf = f"crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]}" if crop else None
    cmd = ["ffmpeg", "-v", "error", "-i", path]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10 ** 8)


def encoder(path, w, h, fps, audio_from, crf, preset):
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-"]
    if audio_from:
        cmd += ["-i", audio_from, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-movflags", "+faststart", path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


# --------------------------------------------------------------------------- #
# identity tracking
# --------------------------------------------------------------------------- #

class _Target:
    """Minimal stand-in for an insightface Face -- the swapper only needs kps."""
    __slots__ = ("kps",)

    def __init__(self, kps):
        self.kps = kps


def iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def build_tracks(per_frame, iou_thr=0.3, max_gap=8):
    """Link detections into tracks. Identity is decided per track, never per frame."""
    tracks, live = [], []
    for fn in sorted(per_frame):
        for det in per_frame[fn]:
            best, best_i = None, 0.0
            for t in live:
                if fn - t["last"] > max_gap:
                    continue
                s = iou(t["bbox"], det["bbox"])
                if s > best_i:
                    best, best_i = t, s
            if best is not None and best_i >= iou_thr:
                best["dets"].append(det); best["bbox"] = det["bbox"]; best["last"] = fn
            else:
                t = {"dets": [det], "bbox": det["bbox"], "last": fn}
                tracks.append(t); live.append(t)
        live = [t for t in live if fn - t["last"] <= max_gap]
    return tracks


def lock_identities(tracks, centroids, thr, margin):
    """One decision per track, from its mean embedding -- so it cannot flip."""
    for t in tracks:
        E = np.stack([d["emb"] for d in t["dets"]])
        mean = E.mean(0); mean /= np.linalg.norm(mean)
        sims = centroids @ mean
        k = int(sims.argmax())
        order = np.sort(sims)[::-1]
        # needs to look like one lead AND clearly more like that one than the other
        t["ident"] = k if (sims[k] >= thr and (order[0] - order[1]) >= margin) else -1
        t["sim"] = float(sims[k]); t["margin"] = float(order[0] - order[1])
    return tracks


# --------------------------------------------------------------------------- #
# swap + occlusion-aware paste
# --------------------------------------------------------------------------- #

class Compositor:
    def __init__(self, swapper, xseg_path, gfpgan_path=None, threads=4):
        self.swapper = swapper
        so = ort.SessionOptions(); so.intra_op_num_threads = threads
        self.xseg = ort.InferenceSession(xseg_path, so, providers=["CPUExecutionProvider"])
        self.gfpgan = (ort.InferenceSession(gfpgan_path, so, providers=["CPUExecutionProvider"])
                       if gfpgan_path else None)

    def face_mask(self, aimg_256):
        inp = cv2.cvtColor(aimg_256, cv2.COLOR_BGR2RGB).astype(np.float32)[None] / 255.0
        m = self.xseg.run(None, {"input": inp})[0][0, :, :, 0]
        return np.clip(m, 0.0, 1.0)

    def restore(self, bgr_512):
        x = cv2.cvtColor(bgr_512, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = ((x - 0.5) / 0.5).transpose(2, 0, 1)[None]
        y = self.gfpgan.run(None, {self.gfpgan.get_inputs()[0].name: x})[0][0]
        y = np.clip(y.transpose(1, 2, 0) * 0.5 + 0.5, 0, 1) * 255.0
        return cv2.cvtColor(y.astype(np.uint8), cv2.COLOR_RGB2BGR)

    def apply(self, img, target_face, source_face, enhance_blend=0.0, feather=0.06):
        """Swap one face and blend it in behind whatever occludes it."""
        fake, M = self.swapper.get(img, target_face, source_face, paste_back=False)  # 128x128
        aimg_256, M256 = face_align.norm_crop2(img, target_face.kps, 256)

        fake_256 = cv2.resize(fake, (256, 256), interpolation=cv2.INTER_CUBIC)
        if self.gfpgan is not None and enhance_blend > 0.0:
            up = self.restore(cv2.resize(fake_256, (512, 512), interpolation=cv2.INTER_CUBIC))
            up = cv2.resize(up, (256, 256), interpolation=cv2.INTER_AREA)
            fake_256 = cv2.addWeighted(fake_256, 1.0 - enhance_blend, up, enhance_blend, 0)

        # match the plate's local colour so the patch sits in the same light
        fake_256 = color_transfer(fake_256, aimg_256)

        mask = self.face_mask(aimg_256)
        k = max(3, int(256 * feather) | 1)
        mask = cv2.erode(mask, np.ones((k // 2 | 1, k // 2 | 1), np.uint8), 1)
        mask = cv2.GaussianBlur(mask, (k, k), 0)[:, :, None]

        IM = cv2.invertAffineTransform(M256)
        h, w = img.shape[:2]
        warped = cv2.warpAffine(fake_256, IM, (w, h), borderValue=0.0)
        wmask = cv2.warpAffine(mask, IM, (w, h), borderValue=0.0)
        if wmask.ndim == 2:
            wmask = wmask[:, :, None]
        return (warped.astype(np.float32) * wmask
                + img.astype(np.float32) * (1.0 - wmask)).astype(np.uint8)


def color_transfer(src, ref):
    """Push src's mean/std toward ref in LAB, so lighting and grade carry over."""
    s = cv2.cvtColor(src, cv2.COLOR_BGR2LAB).astype(np.float32)
    r = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype(np.float32)
    for c in range(3):
        ss, rs = s[..., c].std(), r[..., c].std()
        s[..., c] = (s[..., c] - s[..., c].mean()) * (rs / (ss + 1e-5)) + r[..., c].mean()
    return cv2.cvtColor(np.clip(s, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("--person-a", required=True, help="identity reference for lead A")
    ap.add_argument("--person-b", required=True, help="identity reference for lead B")
    ap.add_argument("-o", "--output", default="final_replace.mp4")
    ap.add_argument("--models", default="models")
    ap.add_argument("--crop", default="auto", help="'auto', 'none', or W:H:X:Y")
    ap.add_argument("--map", default="1:A,0:B",
                    help="lead index -> reference, e.g. '1:A,0:B'")
    ap.add_argument("--sim-thr", type=float, default=0.30,
                    help="min similarity to a lead before a track is swapped")
    ap.add_argument("--margin", type=float, default=0.05,
                    help="min gap between the two leads' scores; below this the "
                         "track is left alone rather than risk a swap of identity")
    ap.add_argument("--enhance", type=float, default=0.0,
                    help="GFPGAN blend 0..1. Off by default: it re-hallucinates "
                         "detail per frame, which shimmers in motion, and costs "
                         "~2.6 s per face on CPU")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="slow")
    ap.add_argument("--cache", default="cache_tracks.pkl")
    ap.add_argument("--reuse-tracks", action="store_true")
    args = ap.parse_args()

    info = probe(args.input)
    canvas = (info["width"], info["height"])
    if args.crop == "auto":
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-ss", "2", "-i", args.input, "-t", "30",
             "-vf", "cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"],
            capture_output=True, text=True)
        import re
        found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", proc.stderr)
        crop = tuple(int(v) for v in found[-1]) if found else None
        if crop and crop[:2] == canvas:
            crop = None
    elif args.crop == "none":
        crop = None
    else:
        crop = tuple(int(p) for p in args.crop.split(":"))
    W, H = (crop[0], crop[1]) if crop else canvas
    total = int(round(info["duration"] * info["fps"]))
    if args.max_frames:
        total = min(total, args.max_frames)

    print(f"input   {info['width']}x{info['height']} @ {info['fps']:.3f} fps, "
          f"{info['duration']:.2f}s, {total} frames, audio={info['has_audio']}")
    print(f"crop    {crop if crop else 'none'}  -> working plate {W}x{H}")

    app = FaceAnalysis(name="buffalo_l", root=os.path.dirname(args.models) or ".",
                       providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    swapper = get_model(f"{args.models}/inswapper_128.onnx", providers=["CPUExecutionProvider"])
    comp = Compositor(swapper, f"{args.models}/xseg_1.onnx",
                      f"{args.models}/gfpgan_1.4.onnx" if args.enhance > 0 else None,
                      args.threads)

    refs = {}
    for tag, path in (("A", args.person_a), ("B", args.person_b)):
        img = cv2.imread(path)
        if img is None:
            sys.exit(f"error: cannot read {path}")
        faces = app.get(img)
        if not faces:
            sys.exit(f"error: no face found in {path}")
        refs[tag] = sorted(faces, key=lambda f: -(f.bbox[2] - f.bbox[0]))[0]
        print(f"ref {tag}  {os.path.basename(path)}  face {refs[tag].bbox.astype(int).tolist()}")

    frame_bytes = W * H * 3

    # ---------------- pass A: detect, embed, track ---------------- #
    if args.reuse_tracks and os.path.exists(args.cache):
        blob = pickle.load(open(args.cache, "rb"))
        per_frame, centroids = blob["per_frame"], blob["centroids"]
        print(f"\npass A  reusing {args.cache}")
    else:
        print(f"\npass A  detecting and embedding ({total} frames)")
        proc = decoder(args.input, crop)
        per_frame, n, t0 = {}, 0, time.time()
        while n < total:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            per_frame[n] = [dict(bbox=f.bbox.astype(float), kps=f.kps.astype(float),
                                 emb=f.normed_embedding.astype(np.float32),
                                 score=float(f.det_score)) for f in app.get(frame)]
            n += 1
            if n % 50 == 0 or n == total:
                el = time.time() - t0
                print(f"  {n}/{total}  {el/n:.2f}s/frame  eta {el/n*(total-n)/60:.1f} min", flush=True)
        proc.terminate(); proc.stdout.close(); proc.wait()
        total = n

        # the two leads = the two biggest, longest-lived identities
        allE, allA = [], []
        for fn, ds in per_frame.items():
            for d in ds:
                allE.append(d["emb"])
                allA.append((d["bbox"][2] - d["bbox"][0]) * (d["bbox"][3] - d["bbox"][1]))
        allE, allA = np.stack(allE), np.array(allA)
        big = allA > np.percentile(allA, 45)
        Eb = allE[big]
        lab, cents = -np.ones(len(Eb), int), []
        for i in np.argsort(-allA[big]):
            for k, c in enumerate(cents):
                if float(Eb[i] @ c) > 0.45:
                    lab[i] = k
                    cents[k] = c * 0.92 + Eb[i] * 0.08
                    cents[k] /= np.linalg.norm(cents[k])
                    break
            else:
                cents.append(Eb[i].copy()); lab[i] = len(cents) - 1
        sizes = [(lab == k).sum() for k in range(len(cents))]
        top = np.argsort(sizes)[::-1][:2]
        centroids = np.stack([Eb[lab == k].mean(0) / np.linalg.norm(Eb[lab == k].mean(0))
                              for k in top]).astype(np.float32)
        print(f"  leads found: {sizes[top[0]]} and {sizes[top[1]]} detections, "
              f"cross-similarity {float(centroids[0] @ centroids[1]):.3f}")
        pickle.dump({"per_frame": per_frame, "centroids": centroids}, open(args.cache, "wb"))

    mapping = {}
    for part in args.map.split(","):
        lead, tag = part.split(":")
        mapping[int(lead)] = tag.strip().upper()
    print(f"  mapping: " + ", ".join(f"lead {k} -> Person {v}" for k, v in sorted(mapping.items())))

    tracks = lock_identities(build_tracks(per_frame), centroids, args.sim_thr, args.margin)
    assign = {}
    kept = {0: 0, 1: 0}
    for t in tracks:
        if t["ident"] < 0:
            continue
        kept[t["ident"]] += len(t["dets"])
        for d in t["dets"]:
            assign[id(d)] = mapping[t["ident"]]
    print(f"  {len(tracks)} tracks; swapping {kept[0]} + {kept[1]} faces, "
          f"{sum(len(v) for v in per_frame.values()) - kept[0] - kept[1]} bystander faces untouched")

    # ---------------- pass B: swap, paste, encode ---------------- #
    audio = args.input if info["has_audio"] else None
    out = encoder(args.output, canvas[0], canvas[1], info["fps"], audio, args.crf, args.preset)
    proc = decoder(args.input, crop)
    print(f"\npass B  swapping and encoding -> {args.output}")
    t0, swapped = time.time(), 0
    for n in range(total):
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        plate = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        for d in per_frame.get(n, []):
            tag = assign.get(id(d))
            if tag is None:
                continue
            plate = comp.apply(plate, _Target(d["kps"]), refs[tag], args.enhance)
            swapped += 1
        if crop:
            full = np.zeros((canvas[1], canvas[0], 3), np.uint8)
            full[crop[3]:crop[3] + H, crop[2]:crop[2] + W] = plate
        else:
            full = plate
        out.stdin.write(full.tobytes())
        if (n + 1) % 25 == 0 or n + 1 == total:
            el = time.time() - t0
            print(f"  {n+1}/{total}  {swapped} swaps  {el/(n+1):.2f}s/frame  "
                  f"eta {el/(n+1)*(total-n-1)/60:.1f} min", flush=True)
    proc.terminate(); proc.stdout.close(); proc.wait()
    out.stdin.close()
    if out.wait() != 0:
        sys.exit("error: encoder failed")
    print(f"\ndone  {args.output}  ({os.path.getsize(args.output)/1e6:.1f} MB, {swapped} face swaps)")


if __name__ == "__main__":
    main()
