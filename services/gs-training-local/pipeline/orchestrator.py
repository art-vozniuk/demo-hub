import logging
import shutil
import time
from pathlib import Path

from pipeline.compress_splat import compress_to_splat
from pipeline.config import PipelineConfig
from pipeline.extract_frames import extract_frames
from pipeline.run_sfm import run_sfm
from pipeline.run_training import run_training
from pipeline.select_frames import filter_frames

log = logging.getLogger(__name__)


def run_pipeline(video: Path, output: Path, config: PipelineConfig) -> Path:
    """End-to-end: video → frames → SfM → trained PLY → compressed .splat.

    Returns the path to the final .splat (or PLY if compression is disabled).
    """
    output.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}

    frames_dir = output / "frames"
    sfm_dir = output / "sfm"
    train_dir = output / "train"
    final_path = output / "scene.splat" if config.compress else output / "scene.ply"

    # 1. Frames
    t = time.time()
    frames = extract_frames(
        video=video,
        out_dir=frames_dir,
        fps=config.fps,
        deduplicate=config.deduplicate,
        max_frames=config.max_frames,
    )
    timings["extract_frames"] = time.time() - t
    if not frames:
        raise RuntimeError(f"no frames extracted from {video}")

    # 1b. Quality filter — drop blur/finger/overexposed frames before SfM
    if config.filter_frames:
        t = time.time()
        frames = filter_frames(
            frames,
            min_sharpness_abs=config.filter_min_sharpness,
            drop_below_pct=config.filter_drop_below_pct,
        )
        timings["filter_frames"] = time.time() - t
        if len(frames) < 10:
            raise RuntimeError(
                f"too few frames survived quality filter: {len(frames)}. "
                "Loosen filter_min_sharpness / filter_drop_below_pct or re-shoot."
            )

    # 2. SfM
    t = time.time()
    sfm_model_dir = run_sfm(
        images_dir=frames_dir,
        out_dir=sfm_dir,
        backend=config.sfm_backend,
        matcher=config.matcher,
    )
    timings["sfm"] = time.time() - t

    # 3. GS training → PLY
    t = time.time()
    ply_path = run_training(
        images_dir=frames_dir,
        sfm_model_dir=sfm_model_dir,
        out_dir=train_dir,
        trainer=config.trainer,
        train_steps=config.train_steps,
        brush_bin=config.brush_bin,
    )
    timings["training"] = time.time() - t

    # 4. PLY → .splat (or copy PLY through unchanged)
    t = time.time()
    if config.compress:
        compress_to_splat(ply_path, final_path)
    else:
        shutil.copyfile(ply_path, final_path)
    timings["compress"] = time.time() - t

    # 5. Cleanup intermediates if not requested to keep
    if not config.keep_intermediate:
        for d in (frames_dir, sfm_dir, train_dir):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    total = sum(timings.values())
    log.info("pipeline done in %.1f min: %s", total / 60, _fmt_timings(timings))
    log.info("output: %s", final_path)
    return final_path


def _fmt_timings(t: dict[str, float]) -> str:
    return ", ".join(f"{k}={v:.1f}s" for k, v in t.items())
