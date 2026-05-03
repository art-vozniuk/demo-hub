"""PLY → compressed `.splat` (32 bytes/gaussian) for web delivery.

The output layout matches antimatter15/splat and mkkellogg/GaussianSplats3D so any
WebGL/WebGPU viewer in that family loads it directly:

    struct Gaussian {                  // 32 bytes
      float position[3];               // 12
      float scales[3];                 // 12 (already exp'd, world units)
      uint8 rgba[4];                   //  4 (DC SH → RGB; opacity through sigmoid)
      uint8 rotation[4];               //  4 (quaternion normalized, mapped [-1,1]→[0,255])
    };

We drop higher-order SH (f_rest_*) — they're 75% of a 3DGS PLY and view-dependent
detail isn't worth the bytes given the 50 MB S3 budget. Typical compression ratio
is ~10× vs raw 3DGS PLY.
"""

import logging
from pathlib import Path

import numpy as np
from plyfile import PlyData

log = logging.getLogger(__name__)

SH_C0 = 0.28209479177387814  # Y_0^0 — constant SH basis used by 3DGS for DC term

_SPLAT_DTYPE = np.dtype([
    ("xyz",    np.float32, 3),
    ("scales", np.float32, 3),
    ("rgba",   np.uint8,   4),
    ("rot",    np.uint8,   4),
])  # 32 bytes total


def compress_to_splat(ply_path: Path, out_path: Path) -> Path:
    """Convert a 3DGS-style PLY into a 32-byte-per-gaussian `.splat` blob."""
    if not ply_path.exists():
        raise FileNotFoundError(ply_path)

    log.info("loading %s", ply_path)
    plydata = PlyData.read(str(ply_path))
    v = plydata["vertex"].data
    n = len(v)
    log.info("read %d gaussians", n)

    # Positions
    xyz = np.stack([v["x"], v["y"], v["z"]], axis=-1).astype(np.float32)

    # Scales: PLY stores log-scale → exponentiate
    scales = np.exp(
        np.stack([v["scale_0"], v["scale_1"], v["scale_2"]], axis=-1).astype(np.float32)
    )

    # Rotation quaternion (w,x,y,z order in 3DGS PLY): normalize and map [-1,1]→[0,255]
    rot = np.stack(
        [v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], axis=-1
    ).astype(np.float32)
    rot_norm = np.linalg.norm(rot, axis=-1, keepdims=True)
    rot_norm[rot_norm == 0] = 1.0
    rot /= rot_norm
    rot_u8 = np.clip(np.round((rot * 0.5 + 0.5) * 255.0), 0, 255).astype(np.uint8)

    # Colors: DC SH coefficients → RGB; opacity logits → sigmoid → alpha
    dc = np.stack(
        [v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], axis=-1
    ).astype(np.float32)
    rgb = np.clip(0.5 + SH_C0 * dc, 0.0, 1.0)
    opacity = 1.0 / (1.0 + np.exp(-v["opacity"].astype(np.float32)))
    rgba_u8 = np.empty((n, 4), dtype=np.uint8)
    rgba_u8[:, :3] = np.round(rgb * 255.0).astype(np.uint8)
    rgba_u8[:, 3] = np.clip(np.round(opacity * 255.0), 0, 255).astype(np.uint8)

    # Pack to a contiguous record array → write as raw bytes
    arr = np.empty(n, dtype=_SPLAT_DTYPE)
    arr["xyz"] = xyz
    arr["scales"] = scales
    arr["rgba"] = rgba_u8
    arr["rot"] = rot_u8

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(arr.tobytes())

    size_mb = out_path.stat().st_size / (1024 * 1024)
    ratio = ply_path.stat().st_size / max(out_path.stat().st_size, 1)
    log.info("wrote %s (%.1f MB, %d gaussians, %.1fx vs PLY)",
             out_path, size_mb, n, ratio)
    if size_mb > 50:
        log.warning("output exceeds 50 MB S3 limit — reduce gaussian count during "
                    "training or apply stronger quantization")
    return out_path
