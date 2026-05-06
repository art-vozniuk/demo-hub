import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def run_training(
    images_dir: Path,
    sfm_model_dir: Path,
    out_dir: Path,
    trainer: str,
    train_steps: int,
    brush_bin: Path | None = None,
) -> Path:
    """Run GS training. Returns the path to the produced PLY file.

    Brush expects nerfstudio/COLMAP layout with `images/` and `sparse/0/`.
    We assemble that layout in `out_dir/dataset` so we don't move the original
    intermediate artifacts.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir = out_dir / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    # Brush wants images/ and sparse/0/ at dataset root
    img_link = dataset_dir / "images"
    sparse_link = dataset_dir / "sparse" / "0"
    if img_link.exists() or img_link.is_symlink():
        img_link.unlink()
    img_link.symlink_to(images_dir.resolve(), target_is_directory=True)
    sparse_link.parent.mkdir(parents=True, exist_ok=True)
    if sparse_link.exists() or sparse_link.is_symlink():
        sparse_link.unlink()
    sparse_link.symlink_to(sfm_model_dir.resolve(), target_is_directory=True)

    if trainer == "brush":
        return _train_brush(dataset_dir, out_dir, train_steps, brush_bin)
    elif trainer == "opensplat":
        return _train_opensplat(dataset_dir, out_dir, train_steps)
    else:
        raise ValueError(f"unknown trainer: {trainer!r}")


def _train_brush(dataset_dir: Path, out_dir: Path, steps: int, brush_bin: Path | None) -> Path:
    bin_path = _resolve_brush_bin(brush_bin)
    # Brush quirks (verified against `brush_app --help`):
    #   - `--with-viewer` is a no-arg flag; passing `false` after it gets eaten
    #     as a positional path arg and confuses the loader. Just don't pass it
    #     when we want headless.
    #   - `--export-path` is a *directory* and `--export-name` is the filename
    #     within it (NOT a single file path).
    #   - `--export-every` defaults to 5000, so a small run (e.g. 1000 steps)
    #     produces no PLY at all unless we pin export-every <= total-steps.
    # Eval cadence + save-to-disk gives us periodic rendered snapshots in
    # `out_dir/eval_<step>/` of the held-out frames vs ground-truth, which
    # is the only headless way to compare iterations objectively without a
    # GUI viewer. Cost is negligible (a few hundred ms per eval pass).
    log.info("brush training (%d steps) → %s/scene.ply", steps, out_dir)
    subprocess.run(
        [
            str(bin_path),
            str(dataset_dir),
            "--total-steps", str(steps),
            "--export-every", str(steps),
            "--export-path", str(out_dir),
            "--export-name", "scene.ply",
            "--eval-split-every", "8",
            "--eval-every", str(max(steps // 6, 1000)),
            "--eval-save-to-disk",
        ],
        check=True,
    )

    # Brush sometimes templates `{iter}` into the export name; if our literal
    # "scene.ply" wasn't honored, fall back to whichever PLY brush actually
    # wrote in this directory.
    ply_out = out_dir / "scene.ply"
    if not ply_out.exists():
        candidates = sorted(out_dir.glob("*.ply"))
        if not candidates:
            raise RuntimeError(f"brush produced no PLY in {out_dir}")
        ply_out = candidates[-1]
        log.warning("brush wrote PLY under unexpected name; using %s", ply_out)
    return ply_out


def _train_opensplat(dataset_dir: Path, out_dir: Path, steps: int) -> Path:
    if shutil.which("opensplat") is None:
        raise RuntimeError("opensplat not found in PATH; brew install opensplat")
    ply_out = out_dir / "scene.ply"
    log.info("opensplat training (%d steps) → %s", steps, ply_out)
    subprocess.run(
        [
            "opensplat",
            str(dataset_dir),
            "-n", str(steps),
            "-o", str(ply_out),
        ],
        check=True,
    )
    return ply_out


def _resolve_brush_bin(override: Path | None) -> Path:
    if override is not None:
        if not override.exists():
            raise FileNotFoundError(f"brush_bin override does not exist: {override}")
        return override

    # Default: ./.bin/brush_app inside the service dir (where install_dependencies.sh puts it)
    service_root = Path(__file__).resolve().parents[1]
    local = service_root / ".bin" / "brush_app"
    if local.exists():
        return local

    # Fallback: PATH
    path_bin = shutil.which("brush_app")
    if path_bin:
        return Path(path_bin)

    raise RuntimeError(
        f"brush_app not found at {local} or in PATH; run install_dependencies.sh"
    )
