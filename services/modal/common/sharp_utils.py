"""ml-sharp Gaussians3D → 32-byte splat blob + auto-frame.

Lives under common/ rather than sharp/ to dodge a Python name clash:
the ml-sharp pip package is also called `sharp` (its `sharp.models`,
`sharp.utils.gaussians` etc. are imported inside the Modal container),
so a local `sharp/` package on sys.path would conflict.

Tensor math (scales, rot, linearRGB→sRGB, opacity) runs on the
Gaussians' device; a single .cpu() transfer feeds the 32-byte pack.

Public 3DGS renderers do not undo the linearRGB→sRGB conversion at
display, so we bake sRGB into the .splat colors — mirrors what
sharp.utils.gaussians.save_ply does before writing the PLY.
"""

from __future__ import annotations

import numpy as np
import torch


_SRGB_THRESHOLD = 0.0031308


_SPLAT_DTYPE = np.dtype(
    [
        ("xyz", np.float32, 3),
        ("scales", np.float32, 3),
        ("rgba", np.uint8, 4),
        ("rot", np.uint8, 4),
    ]
)


def _linear_to_srgb(x: torch.Tensor) -> torch.Tensor:
    """linearRGB → sRGB (Metal Shading Language spec, §7.7.7)."""

    # clamp(min=threshold) defends the pow branch against 0**(1/2.4),
    # which is NaN-fragile on some backends. `where` will discard that
    # branch's output for x ≤ threshold, so the clamp does not perturb
    # the result, only the safety of the unused arm.
    return torch.where(
        x <= _SRGB_THRESHOLD,
        x * 12.92,
        1.055 * x.clamp(min=_SRGB_THRESHOLD).pow(1.0 / 2.4) - 0.055,
    )


@torch.no_grad()
def gaussians_to_splat_bytes(
    gaussians,
) -> tuple[bytes, int, np.ndarray, np.ndarray]:
    """Pack Gaussians3D into the 32-byte-per-gaussian .splat layout.

    Returns (splat_bytes, n, positions, alpha_u8). The two numpy arrays
    are forwarded to auto_frame_camera to spare it a second .splat parse.
    """

    pos = gaussians.mean_vectors.flatten(0, 1).contiguous()
    scales = gaussians.singular_values.flatten(0, 1).contiguous()
    quat = gaussians.quaternions.flatten(0, 1)
    colors_lin = gaussians.colors.flatten(0, 1)
    opac = gaussians.opacities.flatten(0, 1)

    quat = quat / quat.norm(dim=-1, keepdim=True).clamp(min=1e-8)
    rot_u8 = ((quat * 0.5 + 0.5) * 255.0).round().clamp(0, 255).to(torch.uint8)

    rgb_srgb = _linear_to_srgb(colors_lin).clamp(0, 1)
    rgb_u8 = (rgb_srgb * 255.0).round().clamp(0, 255).to(torch.uint8)
    alpha_u8 = (opac.clamp(0, 1) * 255.0).round().to(torch.uint8)
    rgba_u8 = torch.cat([rgb_u8, alpha_u8[..., None]], dim=-1)

    pos_np = pos.cpu().numpy().astype(np.float32, copy=False)
    scales_np = scales.cpu().numpy().astype(np.float32, copy=False)
    rgba_np = rgba_u8.cpu().numpy()
    rot_np = rot_u8.cpu().numpy()

    n = pos_np.shape[0]
    arr = np.empty(n, dtype=_SPLAT_DTYPE)
    arr["xyz"] = pos_np
    arr["scales"] = scales_np
    arr["rgba"] = rgba_np
    arr["rot"] = rot_np

    return arr.tobytes(), n, pos_np, rgba_np[:, 3]


# ml-sharp predicts gaussians in OpenCV camera coords. Real subjects sit
# at z ≈ 1..5; anything past this is sky/background hallucination dragged
# to "infinity" by the unprojection. These constants drop those outliers
# and cap the camera distance so we never spawn into a void.
_AUTO_FRAME_MAX_Z = 20.0
_AUTO_FRAME_MAX_RADIUS = 5.0
_AUTO_FRAME_MIN_RADIUS = 0.5
_AUTO_FRAME_MIN_OPACITY = 32  # uint8 ≈ 12% sigmoid


def auto_frame_camera(
    positions: np.ndarray, alpha: np.ndarray
) -> tuple[list[float], list[float]]:
    """Initial (eye, fwd) for a transient SHARP scene.

    Renderer convention: camera at +z, looking toward -z (matches catalog
    scenes in migrations/.../create_splat_scenes.py). Robust to ml-sharp's
    sky/background gaussians that get unprojected to huge z values — drop
    anything past `_AUTO_FRAME_MAX_Z`, then median + percentile on the rest,
    with a hard radius cap so a wide subject can't push the camera too far.
    """

    n = int(positions.shape[0])
    if n == 0:
        return [0.0, 0.0, 0.0], [0.0, 0.0, -1.0]

    mask = (
        (alpha > _AUTO_FRAME_MIN_OPACITY)
        & (positions[:, 2] > 0.1)
        & (positions[:, 2] < _AUTO_FRAME_MAX_Z)
    )
    if mask.sum() < max(n // 20, 100):
        mask = alpha > _AUTO_FRAME_MIN_OPACITY
        if mask.sum() < max(n // 20, 100):
            mask = np.ones(n, dtype=bool)
    xyz_kept = positions[mask]

    centroid = np.median(xyz_kept, axis=0)
    half_extent = np.percentile(np.abs(xyz_kept - centroid), 95, axis=0)
    radius = float(np.linalg.norm(half_extent))
    radius = min(max(radius, _AUTO_FRAME_MIN_RADIUS), _AUTO_FRAME_MAX_RADIUS)

    pullback = 0.01 * radius
    eye = [
        float(centroid[0]),
        float(centroid[1]),
        float(centroid[2] + pullback),
    ]
    fwd = [0.0, 0.0, -1.0]
    return eye, fwd
