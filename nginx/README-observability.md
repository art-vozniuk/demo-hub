# Observability stack — operator notes

Two services join the compose stack: `prometheus` and `grafana`. Everything
wires together over the existing `app_network`, so no extra compose file or
external network plumbing. There is **no push gateway**: Modal containers
return per-request timings inside their generate() responses (`_obs` block)
and the dispatch worker records them; Modal *system* metrics arrive via the
workspace OTel integration straight into Prometheus's native OTLP receiver.

> Deploy ordering (bring the stack up together so nginx can resolve its
> `/otel/` and `/grafana/` upstreams), the Modal OTel integration setup, and
> the prod/dev Modal runbooks live in [../docs/DEPLOY.md](../docs/DEPLOY.md).

## Local

```
docker compose -f docker-compose.local.yml up --build
```

- Grafana UI: http://localhost:3000 (admin/admin) or `/grafana/` behind
  the nginx-local proxy (port 8080)
- Prometheus UI: not exposed publicly

The provisioned dashboards:

- `Platform Overview` — uid `platform-overview` — core HTTP RED, pipeline
  counts/e2e/queue-wait, Postgres/RabbitMQ health, scrape targets
- `Pipeline Detail` — uid `pipeline-detail` — per-application stage
  breakdown (queue → modal overhead → cold start → phases), cold starts,
  Modal HTTP edge
- `Cost / Capacity (estimated)` — uid `cost-capacity` — estimated GPU
  seconds/$ from returned timings; works in dev with zero Modal-side setup
- `Modal System (real)` — uid `modal-system` — Modal-pushed workspace
  metrics (containers, GPU/CPU/mem, input events) + real-uptime cost; needs
  the OTel integration enabled (docs/DEPLOY.md, section C)

Panels are deliberately built around `increase()` / avg-per-run over the
selected window, so a single dev run renders as real numbers instead of a
flatline; quantile panels are labelled as needing sustained load.

## Production — OTLP intake auth

`/otel/` is protected by basic auth against `/etc/nginx/otel.htpasswd`
(host-mounted, gitignored). Generate once on the VPS in the demo-hub
checkout:

```
htpasswd -B -c nginx/otel.htpasswd otel
```

then configure the Modal integration with push URL `https://artemv.tech/otel`
and header `OTEL_HEADER_Authorization: Basic <base64 otel:password>` — full
steps in docs/DEPLOY.md.

## Persisting metrics across restarts

- Prometheus: 7 day retention, 1 GB cap (configurable via the command
  args in `docker-compose.yml`); ingests OTLP pushes with a 30 m
  out-of-order window (`nginx/prometheus.yml`)
- Grafana: dashboards are file-provisioned (`./nginx/grafana/dashboards/`)
  so they survive even a wiped volume; users/preferences live in the
  named volume
