"""Modal-side helpers shared between flux/ and sharp/.

Lives next to the per-app Modal entrypoints, not on the dispatch
worker — these run inside Modal containers (logging, App + Volume
bootstrap, S3 upload, FunctionCall polling). Each app's `app.py` ships
this package via `.add_local_python_source("common.lib")`.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import uuid4

import modal


MODEL_DIR = "/models"


def configure_logging(name: str) -> logging.Logger:
    """Standard module-level log setup; returns the named logger."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return logging.getLogger(name)


def make_app(app_name: str, volume_name: str) -> tuple[modal.App, modal.Volume]:
    """Create the App + a persistent named Volume for its model weights."""

    return (
        modal.App(app_name),
        modal.Volume.from_name(volume_name, create_if_missing=True),
    )


def poll_function_call(call_id: str, log: logging.Logger) -> dict[str, Any]:
    """Non-blocking status check for a spawned Modal FunctionCall.

    Returns {status: running|done|failed|expired|error, ...}. Identical
    across apps — the only thing that varies is what's inside `result`.
    """

    if not call_id:
        return {"status": "error", "error": "call_id is required"}

    call = modal.FunctionCall.from_id(call_id)
    try:
        # timeout=0: don't wait — let dispatch own the polling cadence.
        result = call.get(timeout=0)
        return {"status": "done", "result": result}
    except TimeoutError:
        return {"status": "running"}
    except modal.exception.OutputExpiredError:
        return {"status": "expired"}
    except Exception as e:
        log.exception(f"poll: call_id={call_id} raised")
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}


def upload_to_s3(
    data_bytes: bytes,
    bucket: str,
    folder: str,
    extension: str,
) -> str:
    """Upload to S3 using credentials from the `supabase-s3` modal secret.

    Mirrors services/common/s3/client.py:S3Client.upload_file so the
    returned URL is the same shape dispatch would have produced.
    """

    import boto3
    from botocore.config import Config as BotoConfig

    key = f"{folder}/{uuid4().hex}.{extension}"
    client = boto3.client(
        "s3",
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_ACCESS_KEY_SECRET"],
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.environ["S3_REGION"],
        config=BotoConfig(retries={"max_attempts": 5, "mode": "adaptive"}),
    )
    client.put_object(Bucket=bucket, Key=key, Body=data_bytes)
    return f"{os.environ['S3_PUBLIC_BUCKETS_ENDPOINT']}/{bucket}/{key}"
