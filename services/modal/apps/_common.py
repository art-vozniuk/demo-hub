"""Shared bootstrap for the Modal apps in this directory.

Just the bits that are byte-identical between flux_app.py and sharp_app.py
(logging config, the App + Volume pair, model dir constant). The
inference class + endpoint code stays per-app — bodies differ enough
that abstracting them would obscure more than it dedupes.
"""

from __future__ import annotations

import logging

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
