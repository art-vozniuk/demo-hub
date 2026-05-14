"""CPU post-processing for SHARP outputs: 3DGS PLY → .splat + auto-frame.

PLY→splat math is a copy of services/gs-training-local/pipeline/
compress_splat.py; that package would drag torch into dispatch, so we
inline the ~50 lines here. Keep the two in sync.
"""

from __future__ import annotations

import io
import logging

import numpy as np
from plyfile import PlyData


log = logging.getLogger(__name__)


# SH Y_0^0 — DC term 3DGS PLYs use to encode base RGB.
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


# ml-sharp predicts gaussians in OpenCV camera coords. Real subjects sit
# at z ≈ 1..5; anything past this is sky/background hallucination dragged
# to "infinity" by the unprojection. These constants drop those outliers
# and cap the camera distance so we never spawn into a void.
_AUTO_FRAME_MAX_Z = 20.0
_AUTO_FRAME_MAX_RADIUS = 5.0
_AUTO_FRAME_MIN_RADIUS = 0.5
_AUTO_FRAME_MIN_OPACITY = 32  # uint8 ≈ 12% sigmoid


def auto_frame_camera(
    splat_bytes: bytes, gaussian_count: int
) -> tuple[list[float], list[float]]:
    """Initial (eye, fwd) for a transient SHARP scene.

    Renderer convention: camera at +z, looking toward -z (matches catalog
    scenes in migrations/.../create_splat_scenes.py). Robust to ml-sharp's
    sky/background gaussians that get unprojected to huge z values — drop
    anything past `_AUTO_FRAME_MAX_Z`, then median + percentile on the rest,
    with a hard radius cap so a wide subject can't push the camera too far.
    """

    if gaussian_count == 0:
        return [0.0, 0.0, 0.0], [0.0, 0.0, -1.0]

    raw = np.frombuffer(splat_bytes, dtype=np.uint8).reshape(gaussian_count, 32)
    xyz = raw[:, :12].view(np.float32).reshape(gaussian_count, 3)
    alpha = raw[:, 27]

    # Step 1: alpha + z-band filter. Sky gaussians often have high alpha
    # (sky is opaque) so opacity alone won't catch them — the z cap does.
    mask = (
        (alpha > _AUTO_FRAME_MIN_OPACITY)
        & (xyz[:, 2] > 0.1)
        & (xyz[:, 2] < _AUTO_FRAME_MAX_Z)
    )
    # Fallback if z-band stranded us with <5% (e.g. legitimately deep scene).
    if mask.sum() < max(gaussian_count // 20, 100):
        mask = alpha > _AUTO_FRAME_MIN_OPACITY
        if mask.sum() < max(gaussian_count // 20, 100):
            mask = np.ones(gaussian_count, dtype=bool)
    xyz_kept = xyz[mask]

    centroid = np.median(xyz_kept, axis=0)
    half_extent = np.percentile(np.abs(xyz_kept - centroid), 95, axis=0)
    radius = float(np.linalg.norm(half_extent))
    # Clamp so the camera lands in a usable framing range regardless of
    # any remaining outliers or unusually wide subjects.
    radius = min(max(radius, _AUTO_FRAME_MIN_RADIUS), _AUTO_FRAME_MAX_RADIUS)

    pullback = 2.5 * radius
    eye = [
        float(centroid[0]),
        float(centroid[1]),
        float(centroid[2] + pullback),
    ]
    fwd = [0.0, 0.0, -1.0]
    log.info(
        "auto-frame: kept=%d/%d centroid=%s radius=%.3f eye=%s fwd=%s",
        int(mask.sum()),
        gaussian_count,
        centroid.tolist(),
        radius,
        eye,
        fwd,
    )
    return eye, fwd
