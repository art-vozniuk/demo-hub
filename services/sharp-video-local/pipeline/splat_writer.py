"""ml-sharp Gaussians3D → 32-byte splat blob.

Mirrors services/modal/common/sharp_utils.gaussians_to_splat_bytes — kept
local to avoid a cross-service import (the Modal service ships its copy
with `add_local_python_source`, which doesn't apply here). The byte
layout is the antimatter15 .splat that the WebGPU renderer consumes.
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

    return torch.where(
        x <= _SRGB_THRESHOLD,
        x * 12.92,
        1.055 * x.clamp(min=_SRGB_THRESHOLD).pow(1.0 / 2.4) - 0.055,
    )


@torch.no_grad()
def gaussians_to_splat_bytes(gaussians) -> tuple[bytes, int]:
    """Pack a single Gaussians3D batch element into the .splat layout.

    Caller is responsible for slicing the batched Gaussians3D down to
    one element before passing it in — see SharpVideoRunner for the
    per-batch-item loop.
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

    return arr.tobytes(), n
