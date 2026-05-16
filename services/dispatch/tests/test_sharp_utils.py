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
        ("x", "f4"),
        ("y", "f4"),
        ("z", "f4"),
        ("f_dc_0", "f4"),
        ("f_dc_1", "f4"),
        ("f_dc_2", "f4"),
        ("opacity", "f4"),
        ("scale_0", "f4"),
        ("scale_1", "f4"),
        ("scale_2", "f4"),
        ("rot_0", "f4"),
        ("rot_1", "f4"),
        ("rot_2", "f4"),
        ("rot_3", "f4"),
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


def _make_splat_bytes(xyz: np.ndarray, alpha: np.ndarray) -> tuple[bytes, int]:
    """Hand-pack a minimal .splat-format buffer matching _SPLAT_DTYPE."""

    n = len(xyz)
    arr = np.zeros(
        n,
        dtype=np.dtype(
            [
                ("xyz", np.float32, 3),
                ("scales", np.float32, 3),
                ("rgba", np.uint8, 4),
                ("rot", np.uint8, 4),
            ]
        ),
    )
    arr["xyz"] = xyz.astype(np.float32)
    arr["scales"] = 1.0
    arr["rgba"][:, 3] = alpha.astype(np.uint8)
    return arr.tobytes(), n


def test_auto_frame_camera_ignores_far_phantom_outliers():
    """A handful of very far, low-opacity gaussians shouldn't blow up the
    pullback distance — keep the camera close to the visible bulk."""

    bulk = np.random.default_rng(0).uniform(-0.5, 0.5, size=(1000, 3))
    bulk[:, 2] += 2.0  # shift bulk to z ≈ 2
    # 5 phantom gaussians 100x farther away, near-transparent.
    phantoms = np.array([[0, 0, 200.0]] * 5)
    xyz = np.concatenate([bulk, phantoms])
    alpha = np.concatenate(
        [
            np.full(len(bulk), 200, dtype=np.uint8),  # opaque bulk
            np.full(len(phantoms), 5, dtype=np.uint8),  # near-transparent
        ]
    )
    splat_bytes, n = _make_splat_bytes(xyz, alpha)

    eye, fwd = auto_frame_camera(splat_bytes, n)
    # Bulk is ~1 unit across at z≈2. Pullback ~2.5×radius (~2) → eye_z ≈ 4-7.
    assert 3.0 < eye[2] < 15.0, f"eye too far: {eye[2]} (phantoms not filtered?)"
    assert fwd == [0.0, 0.0, -1.0]


def test_auto_frame_camera_ignores_opaque_sky_at_huge_z():
    """Real bug: ml-sharp on a sky-heavy photo produces a LOT of opaque
    gaussians at z≈150..800. Alpha filter alone doesn't catch them. The
    z-band filter must drop them and the camera must spawn near the subject,
    not 150 units away in a black void."""

    rng = np.random.default_rng(1)
    # 40% subject at z ≈ 2..4 (foreground content).
    subject = rng.uniform(-1, 1, size=(400, 3))
    subject[:, 2] = rng.uniform(2.0, 4.0, size=400)
    # 60% "sky" — opaque gaussians shoved to huge z values by unprojection.
    sky = rng.uniform(-2, 2, size=(600, 3))
    sky[:, 2] = rng.uniform(150.0, 800.0, size=600)
    xyz = np.concatenate([subject, sky])
    # Both groups fully opaque — only z-band filter can separate them.
    alpha = np.full(len(xyz), 220, dtype=np.uint8)
    splat_bytes, n = _make_splat_bytes(xyz, alpha)

    eye, fwd = auto_frame_camera(splat_bytes, n)
    # Subject at z≈3, radius capped at 5 → pullback ≤12.5 → eye_z ≤ 16.
    # If sky leaked in, eye_z would be in the hundreds (the reported regression).
    assert eye[2] < 20.0, f"sky leaked into auto-frame: eye_z={eye[2]}"
    assert eye[2] > 2.0, f"camera spawned inside subject: eye_z={eye[2]}"
    assert fwd == [0.0, 0.0, -1.0]
