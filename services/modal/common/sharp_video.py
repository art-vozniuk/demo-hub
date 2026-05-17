"""Optional: render an orbit/wobble preview MP4 from a Gaussians3D scene.

Toggled by `RENDER_VIDEO` in sharp/app.py. Off by default the module is
never imported, so its heavy deps (gsplat, imageio[ffmpeg]) and the
extra wall-clock time stay out of the pipeline.

The wobble is a small lateral camera oscillation around the prediction
camera's viewpoint — the same "Spatial Photo" parallax effect that
iPhone Live Photos and Google Cinematic Photos use. ml-sharp predicts
gaussians in OpenCV camera coords with the prediction camera at the
world origin looking +z; we offset the rendering camera by a few
centimeters in x and re-aim it at the subject's centroid.
"""

from __future__ import annotations

import io
import math
import os
import tempfile
from typing import Any

import numpy as np
import torch

from common.sharp_utils import _linear_to_srgb


@torch.no_grad()
def render_wobble_mp4(
    gaussians: Any,
    width: int = 512,
    height: int = 512,
    num_frames: int = 48,
    fps: int = 24,
    wobble_amplitude: float = 0.15,
) -> bytes:
    """Render `num_frames` of a left-right wobble video; return the MP4 bytes.

    - `wobble_amplitude`: peak lateral camera offset in meters
    - `width` / `height`: kept at multiples of 16 so libx264 doesn't whine
    """

    from gsplat import rasterization
    import imageio.v2 as imageio

    device = gaussians.mean_vectors.device

    means = gaussians.mean_vectors.flatten(0, 1).contiguous()
    scales = gaussians.singular_values.flatten(0, 1).contiguous()
    quats = gaussians.quaternions.flatten(0, 1).contiguous()
    quats = quats / quats.norm(dim=-1, keepdim=True).clamp(min=1e-8)
    colors = gaussians.colors.flatten(0, 1).contiguous()
    opacities = gaussians.opacities.flatten(0, 1).contiguous()

    # Centroid z of confidently-opaque gaussians: where the subject sits in
    # the scene. The camera aims at (0, 0, centroid_z).
    mask = opacities > 0.1
    if mask.sum() == 0:
        mask = torch.ones_like(opacities, dtype=torch.bool)
    centroid_z = float(means[mask][:, 2].median().item())
    centroid_z = max(centroid_z, 0.5)  # avoid degenerate ~0 distance
    target = torch.tensor([0.0, 0.0, centroid_z], device=device)
    up = torch.tensor([0.0, -1.0, 0.0], device=device)  # OpenCV y-down

    f_px = float(width) * 0.9
    K = torch.tensor(
        [
            [f_px, 0.0, width / 2.0],
            [0.0, f_px, height / 2.0],
            [0.0, 0.0, 1.0],
        ],
        device=device,
        dtype=torch.float32,
    )

    frames: list[np.ndarray] = []
    for i in range(num_frames):
        t = 2.0 * math.pi * i / num_frames
        eye = torch.tensor(
            [math.sin(t) * wobble_amplitude, 0.0, 0.0],
            device=device,
            dtype=torch.float32,
        )

        # OpenCV look_at: z_cam = forward (toward target), x_cam = right, y_cam = down.
        z_cam = target - eye
        z_cam = z_cam / z_cam.norm()
        x_cam = torch.linalg.cross(up, z_cam)
        x_cam = x_cam / x_cam.norm()
        y_cam = torch.linalg.cross(z_cam, x_cam)
        rot = torch.stack([x_cam, y_cam, z_cam], dim=0)
        viewmat = torch.eye(4, device=device, dtype=torch.float32)
        viewmat[:3, :3] = rot
        viewmat[:3, 3] = -rot @ eye

        rendered, _alpha, _info = rasterization(
            means=means,
            quats=quats,
            scales=scales,
            opacities=opacities,
            colors=colors,
            viewmats=viewmat[None],
            Ks=K[None],
            width=width,
            height=height,
            render_mode="RGB",
        )
        img_lin = rendered[0].clamp(0.0, 1.0)
        img_srgb = _linear_to_srgb(img_lin).clamp(0.0, 1.0)
        img_u8 = (img_srgb * 255.0).round().clamp(0, 255).to(torch.uint8)
        frames.append(img_u8.cpu().numpy())

    # imageio writes only to disk; round-trip via a temp file. Smaller code
    # surface than driving PyAV directly.
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    try:
        with imageio.get_writer(
            tmp.name,
            fps=fps,
            codec="libx264",
            pixelformat="yuv420p",
            macro_block_size=None,
            quality=8,
        ) as writer:
            for frame in frames:
                writer.append_data(frame)
        with open(tmp.name, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass
