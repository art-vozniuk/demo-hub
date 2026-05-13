# Modal — serverless GPU inference

Two independent Modal apps live in this directory, one per demo. They
share the same A10G + memory-snapshot pattern but use separate volumes,
endpoints, and proxy-auth tokens.

| App | Demo | Entry file | Volume | Endpoint env var |
|---|---|---|---|---|
| `demo-hub-flux` | Generative Editing | `apps/flux_app.py` | `flux-models` | `MODAL_GENERATIVE_ENDPOINT_URL` |
| `demo-hub-sharp` | SHARP (single-image → 3DGS) | `apps/sharp_app.py` | `sharp-models` | `MODAL_SHARP_ENDPOINT_URL` |

Each app boots through `apps/_common.py` for the byte-identical
bootstrap (logging config, `modal.App` + `modal.Volume` pair, model
dir). The per-app scripts under `scripts/` are thin wrappers around
shared helpers in `scripts/_lib.sh` (`run_deploy`, `run_preload`,
`run_destroy`).

## FLUX.2 klein — Generative Editing

Serverless GPU backend for the **Generative Editing** demo.
Runs FLUX.2 klein 4B image-conditioned editing on a Modal A10G, fronted
by an HTTP endpoint that the platform's [dispatch worker](../dispatch)
calls.

## What it gives you

- One Modal app: `demo-hub-flux`
- One persistent Modal Volume: `flux-models` — base weights live here
  permanently so cold starts don't pay HuggingFace download time.
- One web endpoint: `POST /` returning a base64-encoded PNG.
- Memory-snapshot cold starts (pipeline already loaded onto GPU).
- Scale-to-zero with a 120s warm window.

## Setup

```bash
cd services/modal

# 1) install Modal CLI + log in (interactive only on first run; shared)
./scripts/setup.sh

# 2) populate the per-app volume with weights (CPU container, idempotent)
./scripts/preload-flux.sh
./scripts/preload-sharp.sh

# 3) deploy each app and print its endpoint URL
./scripts/deploy-flux.sh
./scripts/deploy-sharp.sh

# tear down (volume + secrets kept)
./scripts/destroy-flux.sh
./scripts/destroy-sharp.sh
```

Each deploy writes its endpoint URL to a sibling `.endpoint-flux` /
`.endpoint-sharp`. Copy into the dispatch worker's env:

```
MODAL_GENERATIVE_ENDPOINT_URL=https://<workspace>--demo-hub-flux-generate.modal.run
MODAL_SHARP_ENDPOINT_URL=https://<workspace>--demo-hub-sharp-generate.modal.run
```

## Secrets and proxy-auth

One Modal Secret is created on this side:

- `huggingface` — keys: `HF_TOKEN`. The `FLUX.2-klein-4B` repo is open
  (Apache 2.0, no gating), so the token is optional, but having one set
  avoids hitting anonymous HF rate limits during the preload.

Proxy-auth tokens for the web endpoint are **issued by Modal directly**,
not stored as a Secret. Create one once in the dashboard at
[/settings/proxy-auth-tokens](https://modal.com/settings/proxy-auth-tokens),
then put the resulting Token ID + Token Secret into
`services/dispatch/.env.docker`:

```
MODAL_PROXY_AUTH_TOKEN_ID=<from dashboard>
MODAL_PROXY_AUTH_TOKEN_SECRET=<from dashboard>
```

The dispatch worker sends those as `Modal-Key` / `Modal-Secret` HTTP
headers; Modal validates against its own token table before letting the
request reach the endpoint.

`scripts/setup.sh` handles `huggingface` and prints the dashboard link
for the proxy-auth token.

## Why this design

- Volume preload separates the slow one-shot `huggingface_hub.snapshot_download`
  from the inference path. Without it, the first cold start would be
  ~5 minutes.
- Memory snapshots (`enable_memory_snapshot=True`) capture the
  initialised pipeline on the GPU after the first successful start; later
  cold starts restore RAM in under a second.
- `scaledown_window=120` keeps the container warm two minutes after the
  last call — typical for a portfolio demo where visitors arrive in
  bursts.
- A10G (24GB) is plenty for klein 4B: the model weighs ~13GB in bf16,
  leaving comfortable headroom for activations on a 1024-side input.
  Larger GPUs (L40S, A100) would just cost more for the same quality.
- Klein 4B is distilled — `num_inference_steps=4` and `guidance_scale=1.0`
  produce sub-second steady-state inference once the snapshot warms.

## Cost

At Modal base rates (May 2026) and the reference workload (5–20
visitors/day, ~5s warm inference each):

- Inference: ~$0.05–$0.30/month
- Storage: ~$0.50/month for the FLUX.2 klein 4B weights volume
- Cold-start overhead: negligible after the snapshot is built

If you bump traffic 100×, expect closer to $10–$30/month.

## SHARP — single-image → 3DGS

Serverless GPU backend for the **SHARP** demo. Takes one image, returns
a `.splat` blob plus an auto-framed initial camera. Wraps Apple's
[ml-sharp](https://github.com/apple/ml-sharp) feed-forward predictor —
single forward pass on A10G, ~1–3s steady-state.

Setup uses the same `./scripts/{preload,deploy,destroy}-sharp.sh`
commands documented above. The checkpoint download is ~1.4 GB from
`ml-site.cdn-apple.com` and runs Modal-side during `preload-sharp.sh`.

### Endpoint contract

`POST /` accepts the EXIF-baked photo and a precomputed focal length:

```json
{
  "image_b64": "<base64-encoded JPEG/PNG, EXIF already applied>",
  "f_px": 1234.5
}
```

and returns a standard 3DGS PLY:

```json
{
  "ply_b64": "<base64-encoded .ply bytes>",
  "ply_size_bytes": 12345678
}
```

Scope: GPU inference only. Splat packing (PLY → 32-byte/gaussian
`.splat`), auto-framing (`camera_eye` / `camera_fwd` from the
gaussian AABB), and the S3 upload all run on the dispatch worker —
plain numpy + plyfile, no GPU needed. Keeps the Modal container
focused on what the A10G is actually for.

### License caveats

ml-sharp ships under a dual license — code under
[LICENSE](https://github.com/apple/ml-sharp/blob/main/LICENSE) and model
weights under a separate
[LICENSE_MODEL](https://github.com/apple/ml-sharp/blob/main/LICENSE_MODEL).
Review both before shipping anything beyond a personal demo. The
checkpoint URL is hard-coded in `apps/sharp_app.py:CHECKPOINT_URL` — pin
to a specific commit/release of ml-sharp once Apple cuts one.
