"""Reject low-quality frames before SfM.

Phone-shot orbital videos almost always contain a few catastrophic frames:
finger occlusion, motion blur from a fast pan, severe over/under-exposure
when the camera passes a window, etc. Feeding these to COLMAP wastes time
(it can't register them) and feeding them to GS training poisons the model
near those camera angles — Brush honestly tries to reproduce the mush.

The filter is intentionally simple and side-effect-free at the metric layer
so the thresholds are explainable:

  sharpness  = variance of the Laplacian on grayscale  (higher = sharper)
  brightness = mean grayscale                          (very low = lens covered)
  hot_pct    = fraction of pixels > 240                (very high = lens flare / overexposed)

We drop a frame if ANY of:
  - sharpness < min_sharpness_abs        (absolute floor)
  - sharpness < drop_below_pct percentile (relative; covers cases where
    the whole video is soft so the abs floor is too aggressive)
  - mean brightness < min_mean_brightness  (lens covered / pitch black)
  - hot_pct > max_hot_pct                  (washed out)

Returns the list of surviving frames; bad frames are *deleted from disk*
so they don't leak into COLMAP's image_path. We log a summary so the
operator can sanity-check the cuts.
"""

import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)


def _metrics(img_gray: np.ndarray) -> tuple[float, float, float]:
    sharp = float(cv2.Laplacian(img_gray, cv2.CV_64F).var())
    mean = float(img_gray.mean())
    hot = float((img_gray > 240).mean())
    return sharp, mean, hot


def filter_frames(
    frames: list[Path],
    min_sharpness_abs: float = 10.0,
    drop_below_pct: float = 10.0,
    min_mean_brightness: float = 30.0,
    max_hot_pct: float = 0.30,
    delete_rejected: bool = True,
) -> list[Path]:
    """Filter frames by sharpness/brightness; return survivors."""
    if not frames:
        return frames

    rows: list[tuple[Path, float, float, float]] = []
    for fp in frames:
        img = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
        if img is None:
            log.warning("skipping unreadable frame: %s", fp)
            continue
        sharp, mean, hot = _metrics(img)
        rows.append((fp, sharp, mean, hot))

    sharps = np.array([r[1] for r in rows])
    pct_floor = float(np.percentile(sharps, drop_below_pct)) if drop_below_pct > 0 else 0.0
    abs_floor = max(min_sharpness_abs, pct_floor)

    keep: list[Path] = []
    rejected: list[tuple[str, str]] = []
    for fp, sharp, mean, hot in rows:
        reason = None
        if sharp < abs_floor:
            reason = f"blur (sharp={sharp:.0f} < {abs_floor:.0f})"
        elif mean < min_mean_brightness:
            reason = f"too dark (mean={mean:.0f})"
        elif hot > max_hot_pct:
            reason = f"overexposed (hot%={hot * 100:.0f})"
        if reason:
            rejected.append((fp.name, reason))
            if delete_rejected:
                fp.unlink()
        else:
            keep.append(fp)

    log.info(
        "frame quality filter: kept %d/%d (sharp floor=%.0f, abs=%.0f, p%g=%.0f)",
        len(keep), len(rows), abs_floor, min_sharpness_abs, drop_below_pct, pct_floor,
    )
    if rejected:
        log.info("rejected %d frames:", len(rejected))
        for name, reason in rejected:
            log.info("  - %s  (%s)", name, reason)

    return sorted(keep)
