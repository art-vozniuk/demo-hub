"""Smoke test for the compress step — exercisable without ffmpeg/colmap/brush."""

from pathlib import Path

import numpy as np
import pytest
from plyfile import PlyData, PlyElement

from pipeline.compress_splat import compress_to_splat


def _write_minimal_3dgs_ply(path: Path, n: int = 100) -> None:
    """Write a tiny PLY with the fields a 3DGS exporter produces."""
    rng = np.random.default_rng(seed=0)
    xyz = rng.normal(size=(n, 3)).astype(np.float32)
    f_dc = rng.normal(size=(n, 3)).astype(np.float32) * 0.5
    scale = rng.normal(size=(n, 3)).astype(np.float32) - 2.0  # log-scale
    rot = rng.normal(size=(n, 4)).astype(np.float32)
    opacity = rng.normal(size=n).astype(np.float32)

    dtype = [
        ("x", "f4"), ("y", "f4"), ("z", "f4"),
        ("nx", "f4"), ("ny", "f4"), ("nz", "f4"),
        ("f_dc_0", "f4"), ("f_dc_1", "f4"), ("f_dc_2", "f4"),
        ("opacity", "f4"),
        ("scale_0", "f4"), ("scale_1", "f4"), ("scale_2", "f4"),
        ("rot_0", "f4"), ("rot_1", "f4"), ("rot_2", "f4"), ("rot_3", "f4"),
    ]
    arr = np.empty(n, dtype=dtype)
    arr["x"], arr["y"], arr["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    arr["nx"] = arr["ny"] = arr["nz"] = 0.0
    arr["f_dc_0"], arr["f_dc_1"], arr["f_dc_2"] = f_dc[:, 0], f_dc[:, 1], f_dc[:, 2]
    arr["opacity"] = opacity
    arr["scale_0"], arr["scale_1"], arr["scale_2"] = scale[:, 0], scale[:, 1], scale[:, 2]
    arr["rot_0"], arr["rot_1"], arr["rot_2"], arr["rot_3"] = rot[:, 0], rot[:, 1], rot[:, 2], rot[:, 3]

    el = PlyElement.describe(arr, "vertex")
    PlyData([el]).write(str(path))


def test_compress_outputs_32_bytes_per_gaussian(tmp_path):
    n = 250
    ply = tmp_path / "tiny.ply"
    out = tmp_path / "tiny.splat"
    _write_minimal_3dgs_ply(ply, n=n)

    compress_to_splat(ply, out)

    assert out.stat().st_size == n * 32, "expected 32 bytes per gaussian"


def test_compress_missing_input_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        compress_to_splat(tmp_path / "nope.ply", tmp_path / "out.splat")
