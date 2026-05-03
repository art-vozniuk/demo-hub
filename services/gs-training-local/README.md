# gs-training-local

Local Mac pipeline that turns a phone video of an object into a compressed Gaussian-Splatting scene ready to drop on S3 and load by the WebGPU renderer.

```
phone video (.mov / .mp4)
    ↓ ffmpeg + mpdecimate
~200–400 unique frames
    ↓ COLMAP feature extract+match  →  GLOMAP global mapper
sparse model (cameras, poses, sparse points)
    ↓ Brush (Rust + wgpu, native Apple Silicon)
3DGS PLY (raw, ~150–300 MB)
    ↓ compress (drop higher-order SH, quantize quat+rgba)
scene.splat (32 bytes/gaussian, ≤50 MB target for S3)
```

This is a **prototype** — runs locally on a MacBook, no queue, no UI. The same code is meant to evolve into a worker behind the existing RabbitMQ/S3 stack later.

## Install

```bash
cd services/gs-training-local
./install_dependencies.sh
```

The installer is idempotent. It installs (skipping anything already present):

| Tool | Source | Purpose |
|---|---|---|
| `ffmpeg`, `cmake`, `ninja`, `eigen`, `ceres-solver`, … | Homebrew | Build deps + frame extraction |
| `colmap` | Homebrew | SIFT extraction & matching |
| `glomap` | Source build into `$(brew --prefix)` if missing | Global SfM, ~10–50× faster than COLMAP mapper |
| `brush_app` | Prebuilt GitHub release into `./.bin/` (or `cargo` fallback) | GS trainer on Metal via wgpu |
| `uv` | Homebrew | Python env manager |

After install, activate the Python env and run:

```bash
uv sync
uv run python -m pipeline.cli run \
    --video ~/Movies/cup.mov \
    --output scenes/cup
```

## CLI

```
Usage: python -m pipeline.cli run [OPTIONS]

  Run the full pipeline.

Options:
  --video FILE                    [required]
  --output DIRECTORY              [required]
  --fps FLOAT                     [default: 2.0]
  --max-frames INTEGER            [default: 400]      # 0 = unlimited
  --sfm [glomap|colmap]           [default: glomap]
  --matcher [sequential|exhaustive]  [default: sequential]
  --trainer [brush|opensplat]     [default: brush]
  --steps INTEGER                 [default: 30000]
  --no-compress                   Skip PLY → .splat
  --keep-intermediate             Don't delete frames/sfm/raw PLY
  --brush-bin FILE                Override path to brush_app
```

## Capture guidance

Quality of the result is mostly determined by what you film, not by training time.

- **Static subject.** Anything moving in frame (your hand, leaves) breaks SfM.
- **Smooth orbital path.** A spiral around the object — rising or falling slightly — is ideal. Stay roughly the same distance.
- **Cover all sides.** Strict planar orbit leaves dead zones top/bottom. Tilt the phone.
- **60 FPS, locked exposure.** Don't let the phone auto-adjust mid-shot.
- **30–90 seconds.** With `--fps 2 --max-frames 400` that gives 60–180 dedup'd frames — enough for SfM without blowing up training time.

## Expected timings on M2 Max

| Stage | Time | Notes |
|---|---|---|
| Frame extraction | <30 s | ffmpeg + mpdecimate |
| COLMAP feature extract + match | 1–3 min | SIFT on CPU; matcher `sequential` is much faster than `exhaustive` for video |
| GLOMAP mapper | 1–3 min | global SfM |
| Brush training (30k steps) | 20–30 min | dominant cost |
| Compression to .splat | 5–15 s | numpy-only |
| **Total** | **~30 min** | for ~250 frames |

If you swap `--sfm colmap`, the mapper step alone goes 15–30 min instead of 1–3 — that's the whole reason GLOMAP is the default.

## Output layout

```
<output>/
├── scene.splat          # final, S3-ready
└── (intermediate dirs deleted unless --keep-intermediate)
```

With `--keep-intermediate`:

```
<output>/
├── scene.splat
├── frames/              # extracted frames
├── sfm/                 # COLMAP database + sparse model
└── train/               # raw PLY + brush dataset symlinks
```

## What this is NOT

- Not for production. No queue, no auth, no remote workers.
- Doesn't run inside Docker (depends on Metal / native binaries).
- Doesn't enforce the 50 MB S3 limit beyond a warning — if your scene is denser than ~1.5 M gaussians at 32 B/g, the `.splat` will exceed it and you'll need to either reduce gaussian count during training or apply stronger quantization.

## Productionization sketch (later)

This pipeline lives in `services/gs-training-local/` deliberately separately from the deployed `services/compute/`. To productionize:

1. Wrap `run_pipeline` as a Celery / RabbitMQ task. Existing infra in `docker-compose.yml` already has RabbitMQ.
2. Worker pulls video from S3, writes `scene.splat` back to S3.
3. `services/core` exposes a "submit job" endpoint, returns scene URL when done.
4. Workers stay on Mac (Apple Silicon Metal acceleration) — bare-metal mac mini fleet, not Docker. Linux/CUDA workers are also possible but require a different image (probably the existing `services/compute`).
