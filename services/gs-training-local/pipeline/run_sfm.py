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
    """Run COLMAP feature extraction + matching, then a mapper to produce the sparse model.

    Returns the path to the sparse model directory (containing cameras.bin,
    images.bin, points3D.bin).

    Backends:
      - "glomap"  → uses `colmap global_mapper` (the GLOMAP global SfM
                    solver, integrated into COLMAP 4.x as a built-in
                    subcommand). Falls back to incremental if the running
                    colmap binary doesn't expose global_mapper.
      - "colmap"  → uses `colmap mapper` (incremental SfM). Slower but
                    guaranteed to exist on every COLMAP build.

    Feature extraction and matching always go through `colmap`; only the
    mapper step differs.
    """
    if shutil.which("colmap") is None:
        raise RuntimeError("colmap not found; run install_dependencies.sh")
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

    # 2b. view_graph_calibrator — estimates per-camera focal length from
    # matches and writes the result back to the database. Without this step
    # the global_mapper warns "Less than 50% of cameras have prior focal
    # lengths" because ffmpeg-extracted JPGs lack EXIF, and the
    # reconstruction is noticeably worse without good intrinsic priors.
    log.info("colmap view_graph_calibrator (focal length priors)")
    subprocess.run(
        [
            "colmap", "view_graph_calibrator",
            "--database_path", str(db_path),
        ],
        check=False,  # informational; if it fails, mapper still runs
    )

    # 3. mapper
    use_global = backend == "glomap" and _colmap_has_global_mapper()
    if backend == "glomap" and not use_global:
        log.warning(
            "colmap on this system doesn't expose `global_mapper`; falling back "
            "to the incremental mapper. Upgrade colmap (brew upgrade colmap) for "
            "the faster global SfM."
        )

    if use_global:
        log.info("colmap global_mapper (built-in GLOMAP)")
        subprocess.run(
            [
                "colmap", "global_mapper",
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

    # Both mappers write into a numbered subdir (0/, 1/, ...). Pick the largest.
    model_dirs = [d for d in sparse_dir.iterdir() if d.is_dir()]
    if not model_dirs:
        raise RuntimeError(f"SfM produced no model under {sparse_dir}")
    model_dir = max(model_dirs, key=lambda d: sum(f.stat().st_size for f in d.iterdir()))
    log.info("SfM model: %s", model_dir)
    return model_dir


def _colmap_has_global_mapper() -> bool:
    """Return True if `colmap global_mapper` is a recognised subcommand.

    Older COLMAP releases (pre-4.x) don't expose this — `-h` returns a
    nonzero exit code with a "command not recognised" error. We rely on
    the exit code rather than parsing stderr so the check is robust to
    locale/format changes.
    """
    try:
        result = subprocess.run(
            ["colmap", "global_mapper", "-h"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
