# chrisxxxx — ComfyUI setup

Scripts to install and run [ComfyUI](https://github.com/comfyanonymous/ComfyUI),
the node-graph UI for Stable Diffusion and other diffusion models.

ComfyUI itself is **not vendored here**. The scripts clone it into its own
directory (`~/ComfyUI` by default) with a self-contained virtualenv, so this
repo stays small and ComfyUI can be updated independently.

## Quick start

```bash
./scripts/setup.sh              # clone ComfyUI + create venv + install deps
./scripts/download-model.sh sd15   # fetch a starter checkpoint (~2GB)
./scripts/run.sh                # serve on http://127.0.0.1:8188
```

Then open <http://127.0.0.1:8188>.

Budget roughly **8GB of disk** for the install (a 6GB virtualenv where the
PyPI torch wheel is used, ~1GB otherwise), plus whatever the checkpoints take.

## Running on a Mac

Supported, and on Apple Silicon it uses the GPU through Metal (MPS) — the same
three commands as the quick start, no flags needed:

```bash
./scripts/setup.sh && ./scripts/download-model.sh sd15 && ./scripts/run.sh
```

`setup.sh` detects Apple Silicon and installs the Metal-capable torch wheel from
PyPI (PyTorch's own wheel index carries no macOS builds). `run.sh` then asks
torch what it can use, rather than only asking about CUDA, so a Mac is driven on
MPS instead of being misread as CPU-only.

It also exports `PYTORCH_ENABLE_MPS_FALLBACK=1`. A few torch ops still have no
Metal kernel, and without it an unimplemented op aborts the whole run instead of
falling back to the CPU for that one step.

Rough expectations, 512x512 SD1.5 at 20 steps:

| Machine | Per image |
| --- | --- |
| M1/M2/M3, 16GB+ | seconds to ~30s |
| M-series, 8GB | works; SDXL is tight, keep to SD1.5 |
| Intel Mac | CPU only — minutes per image, no Metal |

Memory is unified on Apple Silicon, so image size and model competing with the
rest of the system is the usual limit. If you hit it, `./scripts/run.sh --lowvram`.

Note the scripts run under `/bin/bash`, which is still 3.2 on macOS; array
expansions are written to be safe there.

## Running on Colab, with models in Google Drive

If you have no local GPU, `colab/ComfyUI_Colab.ipynb` runs ComfyUI on Colab's
GPU and keeps everything worth keeping in Google Drive. Open it in
[Colab](https://colab.research.google.com/), set `Runtime > Change runtime type`
to GPU, and run the cells top to bottom. The last cell prints a public URL you
open in a new tab.

ComfyUI's own code is installed to the runtime's local disk — it is thousands of
small files and Drive's FUSE mount makes that painfully slow. Only the things
that are expensive to re-fetch are symlinked into `MyDrive/ComfyUI`:

- all 11 model folders (`checkpoints`, `loras`, `diffusion_models`,
  `text_encoders`, `vae`, …), so multi-GB weights download once, not once per session
- `output/`, so generated images are in Drive without exporting
- `input/` and `workflows/`

A later session skips the download entirely and is just: mount, install, launch.

Two caveats. Free Colab reclaims idle runtimes and caps GPU hours, so the URL
dies periodically — re-run the cells for a new one, nothing in Drive is lost.
And that URL is public with no password on it, so don't share it and stop the
last cell when you are finished.

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/setup.sh` | Clone/update ComfyUI, create the venv, install torch and requirements. Idempotent — safe to re-run to upgrade. |
| `scripts/run.sh` | Start the server. Auto-detects whether to pass `--cpu`. Extra args are forwarded to `main.py`. |
| `scripts/download-model.sh` | Fetch a checkpoint into `models/checkpoints`. Run with no args to list the catalog. |

### Configuration

All three read the same environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `COMFY_DIR` | `$HOME/ComfyUI` | Install location |
| `COMFY_ACCEL` | `auto` | `setup.sh`: `auto`, `cpu`, `mps`, `cu124`, `cu128` (torch build). `run.sh`: `auto`, `cpu`, `gpu`, `mps` |
| `COMFY_REF` | default branch | Git ref/tag to check out |
| `COMFY_HOST` | `127.0.0.1` | Bind address (`run.sh`) |
| `COMFY_PORT` | `8188` | Bind port (`run.sh`) |
| `HF_TOKEN` | — | Hugging Face token for gated repos (`download-model.sh`) |

Examples:

```bash
COMFY_DIR=/opt/comfy ./scripts/setup.sh      # install elsewhere
COMFY_ACCEL=cu128 ./scripts/setup.sh         # force a CUDA 12.8 build
COMFY_HOST=0.0.0.0 ./scripts/run.sh          # expose on the network
./scripts/run.sh --lowvram                   # extra flags go to main.py
```

## Running without a GPU

ComfyUI runs on CPU, but it is slow: a 512×512 SD1.5 image at 20 steps takes
roughly **1–3 minutes** on a typical 4-core machine, versus a second or two on a
decent GPU. SDXL on CPU is slow enough to be impractical. If you only have CPU,
stick to SD1.5 and low step counts.

`run.sh` passes `--cpu` automatically when `torch.cuda.is_available()` is false;
without that flag ComfyUI aborts at startup looking for a CUDA device.

## Notes on restricted networks

`setup.sh` prefers PyTorch's own wheel index (`download.pytorch.org`), which
serves a slim CPU-only build. Where that host is blocked but PyPI is allowed,
the script detects this and falls back to the PyPI wheel. That wheel bundles
CUDA, so it costs about 3GB of extra disk, but it runs fine on a CPU-only host.

Model downloads need `huggingface.co`. If it is blocked, fetch the checkpoint
elsewhere and copy it into `$COMFY_DIR/models/checkpoints/` — the filename is
all that matters, and `download-model.sh` also accepts a direct URL:

```bash
./scripts/download-model.sh https://example.com/some-model.safetensors
```

## Troubleshooting

**`no virtualenv at … — run ./scripts/setup.sh first`**
`run.sh` was pointed at a directory where setup has not run. Check `COMFY_DIR`.

**Server starts but the graph errors on "Load Checkpoint"**
No checkpoints installed. Run `./scripts/download-model.sh sd15`, then use the
refresh button in the UI so it re-scans the models directory.

**Out of memory on CPU**
Try `./scripts/run.sh --lowvram`, or use a smaller model and image size.

**Updating ComfyUI**
Re-run `./scripts/setup.sh`. It fetches the latest commit and re-syncs
dependencies into the existing venv. Pin a release with
`COMFY_REF=v0.34.0 ./scripts/setup.sh`.

## Verified

Installed and booted on this configuration:

- Linux x86_64, 4 cores, 15GB RAM, no GPU
- Python 3.11.15, torch 2.13.0 (PyPI fallback wheel), ComfyUI 0.34.0
- Server came up on CPU and served the UI with 902 node types registered

The macOS paths were **not run on a Mac** — none was available. What was checked:
accelerator detection was exercised with a stubbed `uname` (Apple Silicon -> MPS,
Intel -> CPU, Linux unchanged), and the device-detection logic against stubbed
torch builds (CUDA -> gpu, Metal -> mps, neither -> cpu, including a torch too
old to have `backends.mps` at all).

Image generation itself was not exercised, because `huggingface.co` was
blocked on that network and no checkpoint could be fetched.

The Colab notebook was **not executed** — there is no Colab runtime here. What
was checked: it is valid nbformat, every code cell compiles, its folder-linking
cell was run against a simulated clone (idempotent, survives a re-clone, writes
land in Drive), all 11 linked model folders exist in ComfyUI 0.34.0, and the
tunnel-URL regex matches real cloudflared output.
