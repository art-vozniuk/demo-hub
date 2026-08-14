# Deploy & Modal environments runbook

How the production stack and the Modal GPU apps get deployed, and how to run a
full local dev loop against an isolated Modal `dev` environment.

- **Backend** (`core`, `dispatch`, `compute`, `web`, `nginx`, `prometheus`,
  `grafana`) runs on the VDS (`artemv.tech`) from `docker-compose.yml` using
  `ghcr.io/art-vozniuk/*` images.
- **Modal GPU apps** run serverless on Modal: `flux` (legacy — serves the live
  demo), `sharp`, `trellis`, `flux_t2i`, `transcriber`, plus `flux_opt`
  (experimental) and `gateway` (single web entry point). Every model app is
  endpoint-less and invoked by name through the gateway.

---

## Modal environments

Two [Modal environments](https://modal.com/docs/guide/environments) isolate
apps, secrets, and volumes:

| Env    | Purpose                                            | Deploys via                |
|--------|----------------------------------------------------|----------------------------|
| `main` | production (the workspace's default environment)   | CI/CD (or `make deploy-prod`) |
| `dev`  | laptop development against `docker-compose.local.yml` | `make ... -dev` from your laptop |

- `modal` selects the environment from the `MODAL_ENVIRONMENT` env var. The
  Makefile targets and the CI workflow set it; nothing reads a hard-coded env.
- `modal.Cls.from_name(app, cls)` resolves within the **current** environment by
  default (pass `environment_name=` only for cross-env). So the gateway in `dev`
  routes to the `flux_opt` app in `dev`, and the gateway in `main` would route to
  `flux_opt` in `main` — no cross-talk.
- There is **no metrics secret**: containers return their per-request timings
  inside generate() responses (dispatch records them into Prometheus), and
  Modal's workspace-level **OpenTelemetry integration** pushes system metrics
  (containers, GPU/CPU/mem, input events) for *all* environments to the prod
  Prometheus — see section C below. Dev runs show up there under
  `environment_name="dev"`.

---

## Gateway & the web-function cap

Modal's free/Starter tier caps **web functions at 8 per workspace**, and the
cap is documented as workspace-level — do not assume it's per-environment.

Every model app is **endpoint-less**: it exposes no `@modal.fastapi_endpoint`
and is invoked by name (`modal.Cls.from_name`) through the gateway. So the
gateway's `submit` + `poll` pair is the workspace's entire web-function spend:

| App | Web functions |
|------------------------------------------------|---|
| `gateway`                                      | submit + poll = 2 |
| `flux`, `sharp`, `trellis`, `flux_t2i`, `transcriber`, `flux_opt` | 0 each |
| **total**                                      | **2 of 8** |

- **Adding a model app costs 0 web functions.** A new demo is a new app
  directory plus one row in `gateway/app.py:ROUTES`.
- **Deploy order matters:** model apps first, gateway last. Its ROUTES resolve
  apps by name, so a route must never go live before the app it points at.
  `deploy-modal.yml` enforces this (`deploy-gateway` needs `deploy-models`).
- In `dev` the gateway runs via **`modal serve`**, whose endpoints are ephemeral
  and **do not count** against the cap.

---

## Production deploy (env = `main`)

### A. Modal apps — CI/CD

Modal deploys run in the **`deploy-modal` job of
`.github/workflows/deploy-core-infra.yml`** (manual `workflow_dispatch`,
alongside the VDS deploy).

- **Per-app gating:** an app deploys only when its own dir — or
  `services/modal/common/`, which ships into every app — changed since the
  `last-deploy` tag (same detection as the service images).
- **Order:** model apps first, **gateway last** — its ROUTES resolve apps by
  name, so a new route must not go live before the app it points at.
- **Auth:** repo secrets `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` (Modal service
  token, Contributor on `main`); `MODAL_ENVIRONMENT=main` set by the job.
- The shared `last-deploy` tag advances (in the `tag` job) only after BOTH the
  VDS and Modal deploys succeed.

**Bootstrap once:** deploy the gateway to `main` to learn its URLs, then set repo
secrets `MODAL_GATEWAY_SUBMIT_URL` / `MODAL_GATEWAY_POLL_URL` (baked into the
dispatch image at build). The old per-app `MODAL_*_URL` repo secrets are unused.

**Prerequisites in the `main` environment** (create once, values = prod):

```bash
modal secret create supabase-s3 \
  S3_ACCESS_KEY_ID=... S3_ACCESS_KEY_SECRET=... \
  S3_ENDPOINT=... S3_REGION=... S3_PUBLIC_BUCKETS_ENDPOINT=... --env main
modal secret create huggingface HF_TOKEN=... --env main
```

The `flux-models` volume already exists in `main` (prod flux uses it); `flux_opt`
shares it.

**Per-app volume preloads** (once per environment, from a laptop with `modal`
logged in — they run on Modal CPU containers and are idempotent):

```bash
cd services/modal
python sharp/preload.py
python trellis/preload.py
python flux_t2i/preload.py
python transcriber/preload.py        # Whisper sizes + pyannote, ~5.5GB
python transcriber/preload_llm.py    # optional transcript cleanup LLM, ~15GB
```

`transcriber` additionally needs the account owning the `huggingface` secret's
`HF_TOKEN` to have accepted the model terms for **both**
[pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
and [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
— they are gated, and without that `preload.py` fails with a pointer to exactly
this. Requests with `llm_cleanup: true` fail fast until `preload_llm.py` has
run, so skipping it degrades one optional toggle rather than the demo.

**Manual fallback** (from a laptop with the service token exported, or a
logged-in `modal`):

```bash
make -C services/modal deploy-prod           # flux, sharp, trellis, flux_t2i, transcriber
make -C services/modal deploy-prod-flux-opt   # optional, experimental
```

### B. Backend + observability stack — bring it up together

The production `nginx.conf` proxies `/otel/` (→ Prometheus's OTLP receiver) and
`/grafana/` to the `prometheus` and `grafana` containers. **nginx resolves
upstream hostnames at startup**, so those containers must already exist on
`app_network` when nginx starts — otherwise nginx (which fronts the whole site)
fails to boot. They're in nginx's `depends_on`, but the config and the services
must roll out **together**:

```bash
# on the VDS, in the demo-hub checkout
docker compose -f docker-compose.yml up -d --remove-orphans
docker compose -f docker-compose.yml up -d --force-recreate nginx
```

The existing `deploy core infra` workflow already does exactly this. Do **not**
recreate nginx alone before the new services exist.

### C. Modal OpenTelemetry integration (real system metrics)

Modal's workspace-level [OTel integration](https://modal.com/docs/guide/otel-integration)
pushes `modal.container.running`, `modal.gpu.*`, `modal.cpu/memory.*` and
`modal.input_events.*` (tagged `app_name` / `function_name` /
`environment_name`) into our Prometheus, which ingests OTLP natively
(`--web.enable-otlp-receiver`). nginx fronts the receiver at
`https://artemv.tech/otel/` with basic auth; logs pushes are swallowed with 204
(we only want metrics). These feed the **Modal System** Grafana dashboard,
including the real-cost panels (container uptime × GPU rate).

1. Create the basic-auth file **once** on the VDS, inside the `demo-hub`
   checkout (user `otel`, pick a strong password):

   ```bash
   htpasswd -B -c nginx/otel.htpasswd otel
   ```

   The deploy `touch`es an empty file first when it's missing, so the
   bind-mount can never become a directory by accident. **Until a real
   credential is set, `/otel/` returns 403** — Modal pushes are rejected and
   the Modal System dashboard stays empty, **but the site stays up**. The file
   is gitignored (`*.htpasswd`) — never commit it.

2. In the Modal dashboard → workspace **Settings → Metrics / OpenTelemetry**,
   configure:
   - **Push URL:** `https://artemv.tech/otel`
   - **Secret:** one header key
     `OTEL_HEADER_Authorization` = `Basic <base64 of "otel:<password>">`
     (`printf 'otel:<password>' | base64`)

   Use the integration's **test** button — Prometheus should start showing
   `modal_*` series (Grafana → Explore → metric browser). The integration is
   configured per **workspace** (one endpoint for all environments); panels
   filter by `environment_name`.

3. If the metric names that arrive differ from the panels' best-guess names
   (OTLP→Prometheus translation can append `_total`/unit suffixes), adjust
   `nginx/grafana/dashboards/modal_system.json` once against the live names.

### D. Post-deploy checklist

```bash
curl -fsS https://artemv.tech/health            # -> healthy
```

- Run a generation in the **live flux demo** — exercises
  `generative_editing*` → gateway → `demo-hub-flux`. This is the prod path that
  must keep working.
- Run a **Transcriber** job on a short clip — exercises the newest app and, on a
  cold container, the whole snapshot-restore path.
- Open `https://artemv.tech/grafana/` — **Platform Overview** and **Pipeline
  Detail** should populate from that one run (panels are built to show single
  runs, not just averages under load), and the run should appear as one full
  trace in Sentry (search by its `pipeline_id` tag).

---

## Dev environment (env = `dev`) runbook

Goal: drive `flux_opt` on Modal from the **local** compose stack and see metrics
in local Grafana — fully isolated from prod. No tunnel needed: containers
return their timings inside generate() responses, and the local dispatch
records them into the local Prometheus.

```
laptop docker-compose.local.yml          Modal (env=dev)
┌───────────────────────────────┐
│ dispatch ─ MODAL_GATEWAY_* ───────────▶ gateway (modal serve, ephemeral)
│   │                           │              │ from_name
│   │ records timings from      │              ▼
│   │ generate() responses      │         flux_opt (modal deploy)
│   ▼                           │
│ prometheus ─ grafana :3000    │
└───────────────────────────────┘
```

(Modal *system* metrics — GPU util, container counts — go to the **prod**
Prometheus via the workspace-level OTel integration regardless of environment;
filter the Modal System dashboard by `environment_name="dev"`.)

1. **Create the dev environment + secrets** (interactive; run it yourself):

   ```bash
   make -C services/modal setup-dev-env
   ```

   This runs `modal environment create dev` and helps create the dev
   `supabase-s3` / `huggingface` secrets. (`scripts/setup-modal-dev.sh`.)

2. **Start the local stack:**

   ```bash
   bash scripts/setup-local-env.sh            # one-time .env.docker files
   docker compose -f docker-compose.local.yml up --build -d
   ```

3. **Point Modal at `dev` for the rest:**

   ```bash
   export MODAL_ENVIRONMENT=dev
   ```

4. **Preload weights into the dev volume, then deploy `flux_opt` to dev:**

   ```bash
   make -C services/modal preload-dev
   make -C services/modal deploy-dev      # `modal deploy` — NOT serve
   ```

   `flux_opt` must be **deployed** (not served): the gateway resolves it with
   `modal.Cls.from_name(...)`, which only sees **deployed** apps.

5. **Serve the gateway in dev (ephemeral, hot-reload):**

   ```bash
   make -C services/modal serve-gateway-dev   # modal serve gateway/app.py
   ```

   `modal serve` prints submit/poll URLs (ephemeral; they don't count against the
   8-web-function cap). Keep this running — it hot-reloads on edits.

6. **Wire the gateway URLs into dispatch** — put them in
   `services/dispatch/.env.docker` (the container's `CMD` does
   `export $(cat /app/.env)`, so values here win over compose `environment:`):

   ```
   MODAL_GATEWAY_SUBMIT_URL=https://<...>-gateway-submit-dev.modal.run
   MODAL_GATEWAY_POLL_URL=https://<...>-gateway-poll-dev.modal.run
   MODAL_PROXY_AUTH_TOKEN_ID=<from the Modal dashboard>
   MODAL_PROXY_AUTH_TOKEN_SECRET=<from the Modal dashboard>
   ```

   The gateway endpoints require proxy-auth, so the proxy-auth token pair must be
   set too (workspace-level; same values as prod). Restart dispatch:

   ```bash
   docker compose -f docker-compose.local.yml up -d dispatch
   ```

7. **Run a `flux_opt_a10g` generation** through the local stack and watch it land:

   - pipeline metrics → local Grafana at `http://localhost:3000` (or `/grafana/`
     via nginx:8080) — Pipeline Detail shows the run's stage breakdown;
   - the gateway terminal shows the spawn → `flux_opt` container; phase timings
     come back inside the generate() response (the `_obs` block) and dispatch
     records them — no tunnel, no pushgateway;
   - the full waterfall (API → queue → dispatch → container phases) appears as
     one trace in Sentry, tagged with the `pipeline_id`.

---

## Guardrails — don't break prod

- **Don't touch the live demo path:** `generative_editing` /
  `generative_editing_custom` → gateway → `demo-hub-flux`. The frontend depends
  on it.
- **`MODAL_GATEWAY_SUBMIT_URL` / `_POLL_URL` must be set in prod.** Dispatch
  reaches every model app through the gateway (`modal_client._invoke_gateway`),
  so an unset pair breaks all Modal-backed demos, not just the newest one. They
  are baked into the dispatch image at build from repo secrets.
- **Deploy the gateway last.** Its ROUTES resolve model apps by name, so a new
  route going live before its app means a `submit` that can't find its target.
- **`compute` dep lockstep:** if you change dependencies in `services/common`,
  relock compute or its worker crashes on the first job
  (`pipeline_worker._process` lazily imports `services.common.observability.metrics`):

  ```bash
  uv --directory services/compute lock --python 3.12
  ```

- **Never commit secrets:** tokens, `.env*`, ngrok URLs, `*.htpasswd` are
  gitignored — keep CI secrets in GitHub Secrets and Modal secrets in Modal.
