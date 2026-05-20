# sharp-video-local

Local Mac pipeline that turns a phone video into a sequence of per-frame
Gaussian-Splatting scenes via Apple's [ml-sharp](https://github.com/apple/ml-sharp).
Companion to `services/gs-training-local` — that one does the slow,
high-quality per-clip SfM + GS training pipeline (one splat per video);
this one does fast, frame-by-frame single-image inference (one splat per
frame) so the WebGPU renderer can play the result back as a moving
gaussian-splat "video".

```
phone video (.mov / .mp4)
    ↓ ffmpeg @ 24 fps (no dedup — strict temporal sequence)
N frames
    ↓ ml-sharp predictor, batched on MPS (M2 Max: batch=4 by default)
N × Gaussians3D
    ↓ pack to 32-byte .splat layout (sRGB-baked colors, quat-quantized rot)
<output>/splats/frame_00001.splat  ...  frame_NNNNN.splat
<output>/manifest.json
```

Each frame is ~30–40 MB at ml-sharp's default density, so a 10-second
clip at 24 fps lands around ~9 GB on disk. Adjust `--fps` / `--max-frames`
to taste.

## Install

```bash
brew install ffmpeg
cd services/sharp-video-local
uv sync
```

ml-sharp is GitHub-only and pulls a ~1.5 GB checkpoint on first run
(`~/.cache/sharp-video-local/sharp_2572gikvuh.pt`, mirrored from
`https://ml-site.cdn-apple.com`). Subsequent runs reuse the cache.

## CLI

```bash
uv run python -m pipeline.cli run \
    --video ~/Movies/cup.mov \
    --output scenes/cup
```

| Flag | Default | Notes |
|---|---|---|
| `--video FILE` | required | Phone video (.mp4 / .mov / anything ffmpeg reads). |
| `--output DIR` | required | Receives `splats/` + `manifest.json`. |
| `--fps FLOAT` | `24.0` | Playback rate. The renderer reads this back from the manifest. |
| `--max-frames INT` | `240` | Hard cap on frame count (0 = unlimited). |
| `--batch-size INT` | `4` | ml-sharp forward-batch on MPS. 8 fits on M2 Max if you have headroom. |
| `--device` | `auto` | `auto` picks MPS on macOS, CUDA on Linux, else CPU. |
| `--f-px-ratio FLOAT` | `0.9` | `f_px = ratio * image_width` (≈ 62° hFOV; phone main lens default). |
| `--keep-frames` | off | Keep raw `.jpg` frames after the splats are written. |

## Playing the result

The companion renderer scene `gsplat_player` (see
`services/external/renderer/Sandbox/src/Scenes/GaussianSplatPlayerScene.cpp`)
loads the output directory and plays it back at the manifest's fps:

```bash
cd services/external/renderer
cmake -S . -B build
cmake --build build --target Sandbox -j 8
./build/Sandbox --scene=gsplat_player --player_dir=$PWD/../../sharp-video-local/scenes/cup/splats
```

## Output layout

```
<output>/
├── manifest.json          # fps, frame_count, prefix, pad
└── splats/
    ├── frame_00001.splat
    ├── frame_00002.splat
    └── ...
```

`manifest.json` is just metadata. The renderer can fall back to globbing
`*.splat` in lexicographic order if the manifest is missing.

## Expected timings on M2 Max

| Stage | Time per 10s @ 24fps (240 frames) | Notes |
|---|---|---|
| Frame extraction | <10 s | ffmpeg fps filter |
| ml-sharp inference | ~3–6 min | dominant cost; batch=4 ~halves vs batch=1 |
| Splat packing + disk write | ~30 s | numpy + .splat write |

If MPS runs out of memory mid-batch, drop to `--batch-size 2` (or 1) —
the orchestrator does not currently downshift on its own.

## Caveats

- ml-sharp single-image inference produces a Gaussians3D in OpenCV
  camera coords; the renderer's `SplatLoader` already bakes the
  180°-X transform so +Y-up works downstream. No extra alignment
  pass is needed here.
- Frame-to-frame coherence is whatever ml-sharp happens to produce
  from independent forward passes — there's no temporal smoothing.
  Expect some flicker on textureless regions; reduce by smoothing
  in post or by feeding higher-frame-rate input and dropping later.
