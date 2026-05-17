"""Bake gsplat's CUDA kernels into the image at build time.

gsplat ships only a `py3-none-any` Python wrapper; its CUDA kernels
are JIT-compiled by `torch.utils.cpp_extension` on the first call to
`rasterization()`. Without this, every cold start spends ~1-3 minutes
re-running nvcc, blowing past Modal's ~60s sync gateway cap and
making each user's first request painful.

Solution: invoke `rasterization()` once during `Image.run_function`
(with `gpu="A10G"`). The compiled `.so` files land in
`$TORCH_EXTENSIONS_DIR`, which is part of the image layer, so every
later cold start finds them already on disk.

Imports are kept inside `prebuild()` so this module is safe to import
locally when modal CLI parses sharp/app.py — torch + gsplat aren't
installed on the dev machine.
"""


def prebuild() -> None:
    import torch
    from gsplat import rasterization

    n = 8
    means = torch.zeros((n, 3), device="cuda")
    quats = torch.zeros((n, 4), device="cuda")
    quats[:, 0] = 1.0  # identity quaternion (w=1)
    scales = torch.ones((n, 3), device="cuda") * 0.1
    opacities = torch.ones((n,), device="cuda") * 0.5
    colors = torch.ones((n, 3), device="cuda")
    viewmats = torch.eye(4, device="cuda")[None]
    Ks = torch.tensor(
        [[[100.0, 0.0, 64.0], [0.0, 100.0, 64.0], [0.0, 0.0, 1.0]]],
        device="cuda",
    )
    rasterization(means, quats, scales, opacities, colors, viewmats, Ks, 128, 128)
    print("gsplat: CUDA kernels prebuilt and cached in image layer")
