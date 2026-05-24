# Modal — serverless GPU inference

Two independent Modal apps live in this directory, one per demo. They
share the same GPU + memory-snapshot pattern but use separate volumes,
endpoints, and proxy-auth tokens.

| App | Demo | Entry file | Volume | Endpoint env vars |
|---|---|---|---|---|
| `demo-hub-flux` | Flux | `flux/app.py` | `flux-models` | `MODAL_GENERATIVE_SUBMIT_URL`, `MODAL_GENERATIVE_POLL_URL` |
| `demo-hub-sharp` | SHARP (single-image → 3DGS) | `sharp/app.py` | `sharp-models` | `MODAL_SHARP_SUBMIT_URL`, `MODAL_SHARP_POLL_URL` |
| `demo-hub-trellis` | TRELLIS.2 (single-image → GLB mesh) | `trellis/app.py` | `trellis-models` | `MODAL_TRELLIS_SUBMIT_URL`, `MODAL_TRELLIS_POLL_URL` |

Every app exposes the same shape: a `submit` endpoint that spawns the
GPU job and returns a `call_id`, and a `poll` endpoint dispatch hits
on a fixed cadence until the call resolves. A sync `@fastapi_endpoint`
would trip Modal's ~60s gateway cap on a cold start; spawn-poll
sidesteps that and keeps the dispatch surface uniform across apps.

## Layout

```
services/modal/
├── setup.sh              # one-time Modal CLI + secrets bootstrap
├── common/               # shipped to containers (Modal-side) + used locally (CLI-side)
│   ├── lib.py            # logging, App + Volume bootstrap, poll_function_call, upload_to_s3
│   ├── sharp_utils.py    # Gaussians3D → splat pack + auto-frame (sharp-specific, lives
│   │                     # in common/ to dodge the ml-sharp `sharp` pip-package name clash)
│   └── cli.py            # local deploy/preload/destroy helpers (subprocess + URL grep)
├── flux/
│   ├── app.py            # Modal entry point
│   ├── deploy.py         # python flux/deploy.py
│   ├── preload.py        # python flux/preload.py
│   └── destroy.py
├── sharp/
│   ├── app.py
│   ├── deploy.py
│   ├── preload.py
│   └── destroy.py
└── trellis/
    ├── app.py
    ├── deploy.py
    ├── preload.py
    └── destroy.py
```

Each per-app script is a 3-line wrapper around a function in
`common/cli.py` (`deploy_submit_poll`, `preload`, `destroy`). The
preamble pins `cwd` + `sys.path` to `services/modal/` so the modal CLI
can resolve `from common.lib import ...` inside the app files.

## FLUX.2 klein — Flux

Serverless GPU backend for the **Flux** demo.
Runs FLUX.2 klein 4B image-conditioned editing on a Modal GPU, fronted
by submit + poll HTTP endpoints that the platform's
[dispatch worker](../dispatch) calls.

## What it gives you

- One Modal app: `demo-hub-flux`
- One persistent Modal Volume: `flux-models` — base weights live here
  permanently so cold starts don't pay HuggingFace download time.
- Two web endpoints: `POST /submit` and `POST /poll`. Result lands in
  S3 (Supabase Storage); `poll` returns the public URL.
- Memory-snapshot cold starts (pipeline already loaded onto GPU).
- Scale-to-zero with a 120s warm window.

## Setup

```bash
cd services/modal

# 1) install Modal CLI + log in (interactive only on first run; shared)
./setup.sh

# 2) populate the per-app volume with weights (CPU container, idempotent)
python flux/preload.py
python sharp/preload.py
python trellis/preload.py

# 3) deploy each app and print its endpoint URLs
python flux/deploy.py
python sharp/deploy.py
python trellis/deploy.py

# tear down (volume + secrets kept)
python flux/destroy.py
python sharp/destroy.py
python trellis/destroy.py
```

Each deploy writes both endpoint URLs (submit then poll) to a sibling
`.endpoint-flux` / `.endpoint-sharp`. Copy into the dispatch worker's
env:

```
MODAL_GENERATIVE_SUBMIT_URL=https://<workspace>--demo-hub-flux-submit.modal.run
MODAL_GENERATIVE_POLL_URL=https://<workspace>--demo-hub-flux-poll.modal.run
MODAL_SHARP_SUBMIT_URL=https://<workspace>--demo-hub-sharp-submit.modal.run
MODAL_SHARP_POLL_URL=https://<workspace>--demo-hub-sharp-poll.modal.run
MODAL_TRELLIS_SUBMIT_URL=https://<workspace>--demo-hub-trellis-submit.modal.run
MODAL_TRELLIS_POLL_URL=https://<workspace>--demo-hub-trellis-poll.modal.run
```

## Secrets and proxy-auth

Two Modal Secrets are used:

- `huggingface` — keys: `HF_TOKEN`. The `FLUX.2-klein-4B` repo is open
  (Apache 2.0, no gating), so the token is optional, but having one set
  avoids hitting anonymous HF rate limits during the preload.
- `supabase-s3` — keys: `S3_ACCESS_KEY_ID`, `S3_ACCESS_KEY_SECRET`,
  `S3_ENDPOINT`, `S3_REGION`, `S3_PUBLIC_BUCKETS_ENDPOINT`. Used by
  both inference containers to upload results directly to S3 (so the
  poll response is a small URL instead of a base64 blob).

Proxy-auth tokens for the web endpoints are **issued by Modal directly**,
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

`setup.sh` handles `huggingface` and prints the dashboard link
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
a `.splat` URL plus an auto-framed initial camera. Wraps Apple's
[ml-sharp](https://github.com/apple/ml-sharp) feed-forward predictor —
single forward pass on A10G, ~1–3s steady-state.

Setup uses the same `python sharp/{preload,deploy,destroy}.py`
commands documented above. The checkpoint download is ~1.4 GB from
`ml-site.cdn-apple.com` and runs Modal-side during `python sharp/preload.py`.

### Endpoint contract

Same shape as flux — `POST /submit` to kick off the GPU job, `POST /poll`
to fetch the result. Submit takes the EXIF-baked photo, a precomputed
focal length, and the target S3 bucket:

```json
{
  "image_b64": "<base64-encoded JPEG/PNG, EXIF already applied>",
  "f_px": 1234.5,
  "image_bucket": "media"
}
```

and returns a Modal FunctionCall handle:

```json
{ "call_id": "fc-...", "request_id": "abc12345" }
```

`POST /poll` returns one of:

```json
{ "status": "running" }
{ "status": "done", "result": {
    "result_url": "https://.../sharp_results/<uuid>.splat",
    "splat_size_bytes": 12345678,
    "gaussian_count": 1500000,
    "camera_eye": [x, y, z],
    "camera_fwd": [x, y, z]
} }
{ "status": "failed",  "error": "..." }
{ "status": "expired" }
```

Scope: GPU inference + splat pack + S3 upload. Auto-framing
(`camera_eye` / `camera_fwd` from the gaussian AABB) runs on the
same container — the AABB is already in GPU memory. Dispatch only
forwards the result URL.

### License caveats

ml-sharp ships under a dual license — code under
[LICENSE](https://github.com/apple/ml-sharp/blob/main/LICENSE) and model
weights under a separate
[LICENSE_MODEL](https://github.com/apple/ml-sharp/blob/main/LICENSE_MODEL).
Review both before shipping anything beyond a personal demo. The
checkpoint URL is hard-coded in `sharp/app.py:CHECKPOINT_URL` — pin
to a specific commit/release of ml-sharp once Apple cuts one.

## TRELLIS.2 — single-image → GLB mesh

Serverless GPU backend for the **GLB mesh** output of the editor's
generate flow. Takes one image, returns a PBR-textured `.glb` URL.
Wraps Microsoft's [TRELLIS.2](https://github.com/microsoft/TRELLIS.2)
image-to-3D pipeline (`microsoft/TRELLIS.2-4B`). Same shape as sharp —
`POST /submit` + `POST /poll`, result lands in S3.

Setup uses the same `python trellis/{preload,deploy,destroy}.py`
commands documented above. Weights download Modal-side during
`python trellis/preload.py`.

### Endpoint contract

Submit takes the source image's S3 location:

```json
{ "image_bucket": "media", "image_key": "generative_results/<uuid>.png" }
```

`POST /poll` returns one of:

```json
{ "status": "running" }
{ "status": "done", "result": {
    "result_url": "https://.../trellis_results/<uuid>.glb",
    "glb_size_bytes": 12345678
} }
{ "status": "failed",  "error": "..." }
{ "status": "expired" }
```

### Image build caveat

Unlike flux/sharp (pure pip installs), TRELLIS.2 compiles custom CUDA
extensions (O-Voxel, FlexGEMM, CuMesh, nvdiffrast, nvdiffrec) from a
`--recursive` clone, so the image starts from a CUDA *devel* base for
`nvcc`. The build recipe in `trellis/app.py:trellis_image` is a
best-effort first pass per the TRELLIS.2 README — expect to iterate on
the `run_commands` steps (versions, submodule paths) until it goes
green. Nothing else in the stack depends on the exact recipe.

GPU: 512-res inference targets an A10G (24GB). If a real input OOMs,
bump the `@app.cls(gpu=...)` tier to `L40S` (48GB) — do not drop the
render resolution.
