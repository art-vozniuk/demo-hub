"""Lock in the splat byte layout + camera framing so a refactor can't
silently shift the format the WASM viewer consumes.
"""

from __future__ import annotations

import io
import struct

import numpy as np
from plyfile import PlyData, PlyElement

from services.dispatch.app.pipelines.sharp_utils import (
    auto_frame_camera,
    ply_bytes_to_splat_bytes,
)


def _build_test_ply_bytes(n: int = 8) -> bytes:
    """Build a minimal 3DGS-format PLY in memory with `n` gaussians."""

    dtype = [
        ("x", "f4"), ("y", "f4"), ("z", "f4"),
        ("f_dc_0", "f4"), ("f_dc_1", "f4"), ("f_dc_2", "f4"),
        ("opacity", "f4"),
        ("scale_0", "f4"), ("scale_1", "f4"), ("scale_2", "f4"),
        ("rot_0", "f4"), ("rot_1", "f4"), ("rot_2", "f4"), ("rot_3", "f4"),
    ]
    rng = np.random.default_rng(0)
    arr = np.zeros(n, dtype=dtype)
    arr["x"] = rng.uniform(-1, 1, n).astype("f4")
    arr["y"] = rng.uniform(-1, 1, n).astype("f4")
    # Bias z positive so auto-framing sees an OpenCV-style scene.
    arr["z"] = rng.uniform(2, 4, n).astype("f4")
    arr["scale_0"] = -2.0
    arr["scale_1"] = -2.0
    arr["scale_2"] = -2.0
    arr["rot_0"] = 1.0
    arr["opacity"] = 2.0

    el = PlyElement.describe(arr, "vertex")
    buf = io.BytesIO()
    PlyData([el]).write(buf)
    return buf.getvalue()


def test_ply_bytes_to_splat_bytes_struct_layout():
    ply_bytes = _build_test_ply_bytes(n=4)
    splat_bytes, count = ply_bytes_to_splat_bytes(ply_bytes)

    assert count == 4
    # 32 bytes/gaussian × 4 gaussians.
    assert len(splat_bytes) == 32 * 4

    # First gaussian: 3×f32 xyz then 3×f32 scales then 4×u8 rgba then 4×u8 rot.
    x, y, z, sx, sy, sz = struct.unpack_from("<6f", splat_bytes, 0)
    rgba = struct.unpack_from("<4B", splat_bytes, 24)
    rot = struct.unpack_from("<4B", splat_bytes, 28)

    # scale_0..2 of -2.0 in log-space → exp(-2.0) ≈ 0.1353
    assert abs(sx - np.exp(-2.0)) < 1e-5
    assert abs(sy - np.exp(-2.0)) < 1e-5
    assert abs(sz - np.exp(-2.0)) < 1e-5
    # opacity logit 2.0 → sigmoid ≈ 0.881 → 224.7
    assert 220 <= rgba[3] <= 228
    # rot quaternion (1,0,0,0) → normalize unchanged → mapped to (255,128,128,128)
    assert rot[0] == 255
    assert 125 <= rot[1] <= 130


def test_auto_frame_camera_pulls_back_along_positive_z():
    ply_bytes = _build_test_ply_bytes(n=32)
    splat_bytes, count = ply_bytes_to_splat_bytes(ply_bytes)
    eye, fwd = auto_frame_camera(splat_bytes, count)

    # Catalog convention: camera at +z, looking toward -z.
    assert fwd == [0.0, 0.0, -1.0]
    # Scene z bounded in [2, 4] → centroid_z ≈ 3, pullback positive → eye_z > 3
    assert eye[2] > 3.0
    # And we should pull back at least a unit beyond the far end of the scene.
    assert eye[2] > 5.0


def test_auto_frame_camera_handles_empty():
    eye, fwd = auto_frame_camera(b"", 0)
    assert eye == [0.0, 0.0, 0.0]
    assert fwd == [0.0, 0.0, -1.0]
