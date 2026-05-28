# Observability stack — operator notes

Three new services join the compose stack: `pushgateway`, `prometheus`,
`grafana`. Everything wires together over the existing `app_network`,
so no extra compose file or external network plumbing.

## Local

```
docker compose -f docker-compose.local.yml up --build
```

- Grafana UI: http://localhost:3000 (admin/admin) or `/grafana/` behind
  the nginx-local proxy (port 8080)
- Prometheus UI: not exposed publicly — `docker compose exec
  prometheus prometheus --web.enable-lifecycle ...` if you need it
- Pushgateway UI: `/pushgateway/` behind nginx

The provisioned dashboards land at:

- `Production Inference (FLUX)` — uid `inference-prod`
- `Bench Run Comparison` — uid `bench-compare` (this one feeds the LinkedIn post)
- `Cold Start Analysis` — uid `cold-start`

## Production — Pushgateway auth

The prod nginx config requires a basic-auth credential file
(`/etc/nginx/pushgateway.htpasswd`) that the existing
`jonasal/nginx-certbot` image doesn't ship. Generate it once on the VPS:

```
htpasswd -B -c /etc/nginx/pushgateway.htpasswd bench
```

The same plaintext password is what each Modal app reads from the
`pushgateway` secret as `PUSHGATEWAY_TOKEN` (the user is fixed to
`bench` in the prometheus_client handler — see
`services/modal/flux_opt/app.py:_push`). After creating the secret in
Modal:

```
modal secret create pushgateway PUSHGATEWAY_URL=https://artemv.tech/pushgateway PUSHGATEWAY_TOKEN=<the-same-plaintext>
```

The deployed Modal containers will start pushing on the first
inference. Grafana panels that read pushed metrics light up
automatically — no separate scrape config needed.

## Persisting metrics across restarts

- Prometheus: 7 day retention, 1 GB cap (configurable via the command
  args in `docker-compose.yml`)
- Pushgateway: state checkpointed every 1 min to the named volume —
  containers can scale to zero without losing the last sample
- Grafana: dashboards are file-provisioned (`./nginx/grafana/dashboards/`)
  so they survive even a wiped volume; users/preferences live in the
  named volume
