"""CPU post-processing for SHARP outputs.

Modal returns a standard 3DGS PLY. Everything past that — packing into
the 32-byte/gaussian .splat layout and choosing an initial camera —
is plain numpy and runs here on the dispatch worker, keeping the GPU
container focused on inference.

The PLY → splat math mirrors
`services/gs-training-local/pipeline/compress_splat.py`. Inlined here
because pulling gs-training-local into dispatch's dep graph would drag
in torch and the COLMAP helpers we don't need. Keep the two in sync.
"""

from __future__ import annotations

import io
import logging

import numpy as np
from plyfile import PlyData


log = logging.getLogger(__name__)


# Spherical-harmonics Y_0^0 — the DC term used by 3DGS PLYs to encode
# the base RGB color before per-direction view-dependent terms.
SH_C0 = 0.28209479177387814


_SPLAT_DTYPE = np.dtype(
    [
        ("xyz", np.float32, 3),
        ("scales", np.float32, 3),
        ("rgba", np.uint8, 4),
        ("rot", np.uint8, 4),
    ]
)


def ply_bytes_to_splat_bytes(ply_bytes: bytes) -> tuple[bytes, int]:
    """3DGS-standard PLY (in memory) → 32-byte-per-gaussian .splat blob.

    Output layout (matches antimatter15/splat + mkkellogg/GaussianSplats3D):

        struct Gaussian {                  // 32 bytes
          float position[3];               // 12
          float scales[3];                 // 12 (already exp'd)
          uint8 rgba[4];                   //  4 (SH DC → RGB; sigmoid opacity)
          uint8 rotation[4];               //  4 ([-1,1] → [0,255])
        };
    """

    plydata = PlyData.read(io.BytesIO(ply_bytes))
    v = plydata["vertex"].data
    n = len(v)
    log.info("ply→splat: read %d gaussians", n)

    xyz = np.stack([v["x"], v["y"], v["z"]], axis=-1).astype(np.float32)
    scales = np.exp(
        np.stack(
            [v["scale_0"], v["scale_1"], v["scale_2"]], axis=-1
        ).astype(np.float32)
    )
    rot = np.stack(
        [v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], axis=-1
    ).astype(np.float32)
    rot_norm = np.linalg.norm(rot, axis=-1, keepdims=True)
    rot_norm[rot_norm == 0] = 1.0
    rot /= rot_norm
    rot_u8 = np.clip(np.round((rot * 0.5 + 0.5) * 255.0), 0, 255).astype(np.uint8)

    dc = np.stack(
        [v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], axis=-1
    ).astype(np.float32)
    rgb = np.clip(0.5 + SH_C0 * dc, 0.0, 1.0)
    opacity = 1.0 / (1.0 + np.exp(-v["opacity"].astype(np.float32)))
    rgba_u8 = np.empty((n, 4), dtype=np.uint8)
    rgba_u8[:, :3] = np.round(rgb * 255.0).astype(np.uint8)
    rgba_u8[:, 3] = np.clip(np.round(opacity * 255.0), 0, 255).astype(np.uint8)

    arr = np.empty(n, dtype=_SPLAT_DTYPE)
    arr["xyz"] = xyz
    arr["scales"] = scales
    arr["rgba"] = rgba_u8
    arr["rot"] = rot_u8

    return arr.tobytes(), n


def auto_frame_camera(
    splat_bytes: bytes, gaussian_count: int
) -> tuple[list[float], list[float]]:
    """Pick an initial (eye, fwd) so the user sees something on first load.

    SHARP follows OpenCV convention with the reconstructed scene
    centered around (0, 0, +z). Centroid + AABB half-extent (max-axis,
    not full-distance — quieter to single-gaussian outliers), then a
    2.5×radius pull-back along -z. Good enough for transient SHARP
    results where there's no curated camera in the catalog.
    """

    if gaussian_count == 0:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]

    # Re-interpret the first 12 bytes of each 32-byte record as xyz
    # floats without copying the rest of the blob.
    raw = np.frombuffer(splat_bytes, dtype=np.uint8).reshape(gaussian_count, 32)
    xyz = raw[:, :12].view(np.float32).reshape(gaussian_count, 3)

    centroid = xyz.mean(axis=0)
    half_extent = np.abs(xyz - centroid).max(axis=0)
    radius = float(np.linalg.norm(half_extent))
    if radius < 1e-3:
        radius = 1.0

    pullback = max(2.5 * radius, 1.0)
    eye = [
        float(centroid[0]),
        float(centroid[1]),
        float(centroid[2] - pullback),
    ]
    fwd = [0.0, 0.0, 1.0]
    log.info(
        "auto-frame: centroid=%s radius=%.3f eye=%s fwd=%s",
        centroid.tolist(),
        radius,
        eye,
        fwd,
    )
    return eye, fwd
