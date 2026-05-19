"""Batched ml-sharp inference on MPS / CUDA / CPU.

Holds the checkpoint in memory once, then loops over batches of frames
to produce one Gaussians3D per input image. The Modal sibling
(services/modal/sharp/app.py::SharpInference._run_inference) is the
canonical reference for the inference recipe — internal_shape, focal
normalization, identity extrinsics for unproject — but it runs
batch=1 on A10G; here we batch on the predictor call to amortize the
~5–10 s/frame MPS overhead on M2 Max.
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

log = logging.getLogger(__name__)


# Same upstream weights the Modal service downloads (services/modal/sharp/app.py).
CHECKPOINT_URL = "https://ml-site.cdn-apple.com/models/sharp/sharp_2572gikvuh.pt"
INTERNAL_SHAPE = (1536, 1536)


def _patch_sharp_for_mps() -> None:
    """Force tensor args through .contiguous() before each upsample block —
    SPN encoder feeds non-contiguous torch.split views into conv2d, which
    MPS rejects with 'view size is not compatible with stride'."""
    from sharp.utils import training as _t

    if getattr(_t, "_meme_fusion_mps_patched", False):
        return

    _orig = _t.checkpoint_wrapper

    def _patched(self, fn, *args):
        fixed = tuple(
            a.contiguous() if isinstance(a, torch.Tensor) and not a.is_contiguous() else a
            for a in args
        )
        return _orig(self, fn, *fixed)

    _t.checkpoint_wrapper = _patched
    _t._meme_fusion_mps_patched = True

    # Same alias the encoder imported `from sharp.utils.training import checkpoint_wrapper`,
    # which captures the original function reference. Override that too.
    import sharp.models.encoders.spn_encoder as _spn
    _spn.checkpoint_wrapper = _patched


def pick_device(requested: str) -> torch.device:
    """Resolve 'auto' / 'mps' / 'cuda' / 'cpu' against what's actually available."""

    if requested == "auto":
        if torch.backends.mps.is_available():
            return torch.device("mps")
        if torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")
    return torch.device(requested)


def _cache_dir() -> Path:
    # Mirrors the Modal service's MODEL_DIR convention but lives in
    # the user's cache so we don't have to deal with permissions.
    p = Path.home() / ".cache" / "sharp-video-local"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_checkpoint() -> Path:
    """Download the ml-sharp checkpoint once into the per-user cache. Idempotent."""

    target = _cache_dir() / "sharp_2572gikvuh.pt"
    if target.exists():
        return target

    tmp = target.with_suffix(target.suffix + ".tmp")
    # Apple's CDN has been observed to reset mid-download; retry a few times.
    last_err: Exception | None = None
    for attempt in range(1, 6):
        t0 = time.perf_counter()
        try:
            log.info("downloading ml-sharp checkpoint from %s", CHECKPOINT_URL)
            urllib.request.urlretrieve(CHECKPOINT_URL, tmp)
            tmp.replace(target)
            size_mb = target.stat().st_size / (1024 * 1024)
            log.info("checkpoint downloaded (%.1f MB) in %.1fs",
                     size_mb, time.perf_counter() - t0)
            return target
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_err = e
            log.warning("checkpoint download attempt %d failed: %r", attempt, e)
            tmp.unlink(missing_ok=True)
            if attempt < 5:
                time.sleep(min(2 ** attempt, 30))

    raise RuntimeError(f"failed to download ml-sharp checkpoint: {last_err!r}")


class SharpRunner:
    """Holds the predictor in memory, runs batched MPS forward passes."""

    def __init__(self, device: torch.device):
        from sharp.models import PredictorParams, create_predictor

        if device.type == "mps":
            _patch_sharp_for_mps()

        ckpt_path = _ensure_checkpoint()
        log.info("loading ml-sharp predictor (device=%s)", device)
        t0 = time.perf_counter()
        state_dict = torch.load(
            str(ckpt_path), weights_only=True, map_location="cpu", mmap=True
        )
        self.predictor = create_predictor(PredictorParams())
        self.predictor.load_state_dict(state_dict, assign=True)
        self.predictor.eval()
        self.predictor.to(device)
        self.device = device
        log.info("predictor ready in %.1fs", time.perf_counter() - t0)

    @torch.no_grad()
    def run_batch(
        self,
        image_paths: list[Path],
        f_px_ratio: float,
    ) -> list:
        """Run one batched ml-sharp forward; return a list of per-image Gaussians3D."""

        from sharp.utils.gaussians import unproject_gaussians

        imgs_pt: list[torch.Tensor] = []
        intrinsics_per_img: list[torch.Tensor] = []
        disparities: list[float] = []
        orig_shapes: list[tuple[int, int]] = []

        for p in image_paths:
            pil = Image.open(p).convert("RGB")
            arr = np.array(pil)
            h, w = arr.shape[:2]
            f_px = float(w) * f_px_ratio
            t = torch.from_numpy(arr).float().permute(2, 0, 1) / 255.0
            imgs_pt.append(
                F.interpolate(t[None], size=INTERNAL_SHAPE, mode="bilinear",
                              align_corners=True)[0]
            )
            disparities.append(f_px / w)
            intr = torch.tensor(
                [
                    [f_px, 0.0, w / 2.0, 0.0],
                    [0.0, f_px, h / 2.0, 0.0],
                    [0.0, 0.0, 1.0,      0.0],
                    [0.0, 0.0, 0.0,      1.0],
                ]
            ).float()
            intr[0] *= INTERNAL_SHAPE[0] / w
            intr[1] *= INTERNAL_SHAPE[1] / h
            intrinsics_per_img.append(intr)
            orig_shapes.append((h, w))

        batch = torch.stack(imgs_pt, dim=0).to(self.device)
        disparity_factor = torch.tensor(disparities).float().to(self.device)

        # The batched forward is the win — predictor() is the slow op.
        t_fwd = time.perf_counter()
        gaussians_batched = self.predictor(batch, disparity_factor)
        # MPS dispatches are async; sync so the timing reflects real GPU work.
        if self.device.type == "mps":
            torch.mps.synchronize()
        fwd_s = time.perf_counter() - t_fwd

        # Post-forward MPS pool snapshot (peak during forward is higher).
        mem_msg = ""
        if self.device.type == "mps":
            curr_gb = torch.mps.current_allocated_memory() / (1024 ** 3)
            drv_gb = torch.mps.driver_allocated_memory() / (1024 ** 3)
            mem_msg = f", mps_alloc={curr_gb:.2f}GB, mps_driver={drv_gb:.2f}GB"
        log.info(
            "forward: batch=%d fwd=%.2fs (%.2fs/frame)%s",
            len(image_paths), fwd_s, fwd_s / max(1, len(image_paths)), mem_msg,
        )

        # ml-sharp's unproject_gaussians takes a single image's intrinsics
        # + a single Gaussians3D batch element. Loop in Python — cheap
        # compared to the forward we just paid for.
        results = []
        for i in range(len(image_paths)):
            single = _slice_gaussians_batch(gaussians_batched, i)
            results.append(
                unproject_gaussians(
                    single,
                    torch.eye(4).to(self.device),
                    intrinsics_per_img[i].to(self.device),
                    INTERNAL_SHAPE,
                )
            )

        # MPS pool creeps to ~28GB on M2 Max otherwise → swap thrash.
        del gaussians_batched, batch, disparity_factor
        if self.device.type == "mps":
            torch.mps.empty_cache()

        return results


def _slice_gaussians_batch(g, i: int):
    """Slice 1-element from a batched Gaussians3D NamedTuple; .contiguous()
    sidesteps the same MPS stride bug patched in checkpoint_wrapper."""
    cls = type(g)
    fields = list(getattr(g, "_fields", ()))
    kwargs = {}
    for field in fields:
        val = getattr(g, field)
        if isinstance(val, torch.Tensor):
            kwargs[field] = val[i : i + 1].contiguous()
        else:
            kwargs[field] = val
    return cls(**kwargs)


def iter_batches(items: list[Path], batch_size: int) -> Iterator[list[Path]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]
