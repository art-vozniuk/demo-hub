"""Local CLI helpers for deploy/preload/destroy scripts.

These run on the developer's machine, not inside Modal containers —
they shell out to the `modal` CLI, stream its output, and extract
endpoint URLs. Per-app scripts (flux/deploy.py etc.) are thin wrappers
around these functions. Each script's preamble puts services/modal/ on
sys.path and chdirs into it, so `modal deploy flux/app.py` and the
`from common.lib import ...` lines inside those apps both resolve.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def _run_streaming(cmd: list[str]) -> str:
    """Run `cmd`, tee stdout/stderr to the terminal, return captured stdout."""

    captured: list[str] = []
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        captured.append(line)
    rc = proc.wait()
    if rc != 0:
        raise SystemExit(rc)
    return "".join(captured)


def deploy_submit_poll(
    app_path: str,
    endpoint_file: str,
    app_name: str,
    submit_env: str,
    poll_env: str,
) -> None:
    """Deploy a Modal app that exposes a submit + poll endpoint pair.

    Greps the `modal deploy` output for the two web endpoints (matched
    by app_name, e.g. demo-hub-sharp), writes them to endpoint_file in
    submit-then-poll order, and prints the env var assignments the
    dispatch worker needs.
    """

    print(f"Deploying {app_path}...")
    out = _run_streaming(["modal", "deploy", app_path])

    submit_re = rf"https://[^\s]+--{re.escape(app_name)}-submit\.modal\.run"
    poll_re = rf"https://[^\s]+--{re.escape(app_name)}-poll\.modal\.run"
    submit_match = re.search(submit_re, out)
    poll_match = re.search(poll_re, out)
    if not submit_match or not poll_match:
        print("Failed to extract submit/poll URLs from modal output.", file=sys.stderr)
        raise SystemExit(1)

    submit_url, poll_url = submit_match.group(0), poll_match.group(0)
    Path(endpoint_file).write_text(f"{submit_url}\n{poll_url}\n")

    print()
    print("Deployed.")
    print(f"  Submit:    {submit_url}")
    print(f"  Poll:      {poll_url}")
    print(f"  Stored at: {Path(endpoint_file).resolve()}")
    print()
    print("Set on the dispatch worker:")
    print(f"  {submit_env}={submit_url}")
    print(f"  {poll_env}={poll_url}")


def preload(app_path: str) -> None:
    """Run the app's preload_weights function once (idempotent)."""

    _run_streaming(["modal", "run", f"{app_path}::preload_weights"])
    print("Volume populated successfully.")


def destroy(app_name: str, volume_name: str) -> None:
    """Stop a deployed app. Volume + secrets are preserved."""

    subprocess.run(["modal", "app", "stop", app_name], check=False)
    print(f"Stopped {app_name}. Volume '{volume_name}' and secrets are preserved.")
