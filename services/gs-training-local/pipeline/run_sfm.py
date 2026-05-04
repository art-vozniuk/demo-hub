import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def run_sfm(
    images_dir: Path,
    out_dir: Path,
    backend: str,
    matcher: str,
) -> Path:
    """Run COLMAP feature extraction + matching, then either GLOMAP or COLMAP mapper.

    Returns the path to the sparse model directory (containing cameras.bin, images.bin, points3D.bin).

    GLOMAP only replaces the *mapper* step (the slow incremental SfM solver) with a
    global optimizer that's 10–50× faster. Feature extraction and matching still go
    through COLMAP.
    """
    if shutil.which("colmap") is None:
        raise RuntimeError("colmap not found; run install_dependencies.sh")
    if backend == "glomap" and shutil.which("glomap") is None:
        raise RuntimeError("glomap not found; run install_dependencies.sh or fall back to backend='colmap'")
    if backend not in {"glomap", "colmap"}:
        raise ValueError(f"unknown sfm backend: {backend!r}")
    if matcher not in {"sequential", "exhaustive"}:
        raise ValueError(f"unknown matcher: {matcher!r}")

    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "database.db"
    sparse_dir = out_dir / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)

    # 1. feature extraction
    # NB: --SiftExtraction.use_gpu / --SiftMatching.use_gpu are CUDA-only
    # flags in COLMAP's CLI. Homebrew's colmap is built without CUDA (no
    # CUDA on Apple Silicon), so passing them aborts with "unrecognised
    # option". CPU SIFT is the default and is what we want here.
    log.info("colmap feature_extractor")
    subprocess.run(
        [
            "colmap", "feature_extractor",
            "--database_path", str(db_path),
            "--image_path", str(images_dir),
            "--ImageReader.single_camera", "1",
            "--ImageReader.camera_model", "OPENCV",
        ],
        check=True,
    )

    # 2. matching
    matcher_cmd = "sequential_matcher" if matcher == "sequential" else "exhaustive_matcher"
    log.info("colmap %s", matcher_cmd)
    subprocess.run(
        [
            "colmap", matcher_cmd,
            "--database_path", str(db_path),
        ],
        check=True,
    )

    # 3. mapper (GLOMAP or COLMAP)
    if backend == "glomap":
        log.info("glomap mapper (global SfM)")
        subprocess.run(
            [
                "glomap", "mapper",
                "--database_path", str(db_path),
                "--image_path", str(images_dir),
                "--output_path", str(sparse_dir),
            ],
            check=True,
        )
    else:
        log.info("colmap mapper (incremental SfM)")
        subprocess.run(
            [
                "colmap", "mapper",
                "--database_path", str(db_path),
                "--image_path", str(images_dir),
                "--output_path", str(sparse_dir),
            ],
            check=True,
        )

    # GLOMAP/COLMAP both write into a numbered subdir (0/, 1/, ...). Pick the largest.
    model_dirs = [d for d in sparse_dir.iterdir() if d.is_dir()]
    if not model_dirs:
        raise RuntimeError(f"SfM produced no model under {sparse_dir}")
    model_dir = max(model_dirs, key=lambda d: sum(f.stat().st_size for f in d.iterdir()))
    log.info("SfM model: %s", model_dir)
    return model_dir
