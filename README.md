# Demo Hub

Personal demo hub for showcasing side projects.

## Live

**[artemv.tech](https://artemv.tech)**

### Gaussian Spatting

Gaussian Splatting renderer running entirely in the browser. Custom C++
WebGPU engine, every-frame GPU radix sort + EWA splat projection in WGSL.
Same code path runs natively on macOS via Dawn → Metal.

<img width="1135" height="717" alt="image" src="https://github.com/user-attachments/assets/18502ab7-9bba-4109-8a3e-29f1b775ff26" />


Source: [renderer](https://github.com/art-vozniuk/renderer)

### Face Swap

Upload a portrait and apply it to various style templates using a GAN-based image generation pipeline.

<img width="891" height="796" alt="image" src="https://github.com/user-attachments/assets/dcf22caa-6754-4239-85f5-28a5c8fbf4af" />
<img width="1009" height="502" alt="image" src="https://github.com/user-attachments/assets/44e47bcb-6e89-44d6-b0d4-21a0ebffb1e8" />
<img width="1019" height="510" alt="image" src="https://github.com/user-attachments/assets/9a445ec5-3ab7-42be-a36f-67fac2f8f058" />

### Generative Editing

Image-conditioned generative editing on FLUX.2 klein. Pick a cinematic
preset, upload a photo, get the same subject in the chosen style. The
inference itself runs on a serverless Modal A10G; the platform side is
an async dispatch worker draining a dedicated RabbitMQ queue, with ETA
backed by Redis worker heartbeats unified across both demos.

## Tech Stack

**Backend** — FastAPI, PostgreSQL, RabbitMQ, Redis, Nginx

**ML/AI** — PyTorch, ONNX Runtime, custom GAN pipeline, FLUX.2 klein on Modal

**Renderer** — C++, WebGPU, WGSL, Dawn / emdawnwebgpu, Emscripten, WebAssembly

**Frontend** — React, TypeScript, Vite, TailwindCSS

**Infra** — Docker, GitHub Actions, Supabase, Sentry, Modal

## Architecture

- **Core** — API gateway: auth, rate limiting, pipeline routing, ETA
- **Compute** — local ML inference workers (face_swap) consuming `pipelines.queue`
- **Dispatch** — async orchestration workers (generative_editing) consuming `pipelines.dispatch`, calling Modal
- **Modal** — serverless A10G GPU running FLUX.2 klein, fronted by an HTTP endpoint
- **Web** — React SPA
- **Renderer** — Emscripten WASM build served via Supabase Storage + GitHub Releases

The core service routes a queued pipeline to either `compute` or
`dispatch` based on `pipeline_name`, via a single mapping in
`services/core/app/pipelines/routing.py`. Workers from both pools
heartbeat into Redis through the shared `services/common/redis.heartbeat`
module; the core's `/pipelines/status` endpoint reads those heartbeats
plus a rolling pipeline-duration history to compute a unified
`eta_seconds` for any pending or running job.

## Project Structure

```
demo-hub/
├── services/
│   ├── common/          # Shared: auth, db, rabbitmq, redis (incl. heartbeat), s3
│   ├── core/            # API gateway + pipeline routing + ETA
│   ├── compute/         # Local ML workers (face_swap, face_recognition)
│   ├── dispatch/        # Async workers — call Modal for generative_editing
│   ├── modal/           # Modal app: FLUX.2 klein on A10G
│   ├── web/             # React frontend
│   └── external/        # renderer + face_swap submodules
├── nginx/               # Reverse proxy config
├── scripts/             # Build scripts (renderer, etc.)
├── docker-compose.yml
└── Makefile
```

## Running Locally

```bash
bash scripts/setup-local-env.sh             # one-time env scaffolding
docker compose -f docker-compose.local.yml up --build
```

For the Generative Editing demo additionally:

```bash
cd services/modal
./scripts/setup.sh    # Modal CLI + secrets
./scripts/preload.sh  # populate flux-models volume (one-shot)
./scripts/deploy.sh   # deploy inference endpoint, prints URL
```

Then drop the printed endpoint into `services/dispatch/.env.docker`:

```
MODAL_GENERATIVE_ENDPOINT_URL=https://...modal.run
MODAL_PROXY_AUTH_TOKEN_ID=...
MODAL_PROXY_AUTH_TOKEN_SECRET=...
```
