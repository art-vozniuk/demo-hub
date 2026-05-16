"""Shared bootstrap for the Modal apps in this directory.

Just the bits that are byte-identical between flux_app.py and sharp_app.py
(logging config, the App + Volume pair, model dir constant). The
inference class + endpoint code stays per-app — bodies differ enough
that abstracting them would obscure more than it dedupes.
"""

from __future__ import annotations

import logging
import os
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
