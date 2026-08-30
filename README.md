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
| `COMFY_ACCEL` | `auto` | `setup.sh`: `auto`, `cpu`, `cu124`, `cu128` (torch build). `run.sh`: `auto`, `cpu`, `gpu` |
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
