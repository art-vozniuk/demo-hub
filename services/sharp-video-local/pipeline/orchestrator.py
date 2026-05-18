import json
import logging
import shutil
import time
from pathlib import Path

from pipeline.config import PipelineConfig
from pipeline.extract_frames import extract_frames
from pipeline.sharp_runner import SharpRunner, iter_batches, pick_device
from pipeline.splat_writer import gaussians_to_splat_bytes

log = logging.getLogger(__name__)


def run_pipeline(video: Path, output: Path, config: PipelineConfig) -> Path:
    """End-to-end: video → ffmpeg frames → ml-sharp per-frame → <output>/frame_NNNNN.splat.

    Returns the output directory. The directory layout is what the
    renderer's gsplat_player scene expects to ingest verbatim — a sorted
    sequence of .splat files plus a small playback manifest.
    """

    output.mkdir(parents=True, exist_ok=True)
    splats_dir = output / "splats"
    splats_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = output / "frames"

    # 1. Frame extraction at the playback rate. No mpdecimate — we
    # need a contiguous sequence, not a deduped subset.
    t = time.time()
    frames = extract_frames(
        video=video,
        out_dir=frames_dir,
        fps=config.fps,
        max_frames=config.max_frames,
    )
    if not frames:
        raise RuntimeError(f"no frames extracted from {video}")
    extract_s = time.time() - t

    # 2. ml-sharp inference, batched on the chosen device.
    device = pick_device(config.device)
    runner = SharpRunner(device)

    n = len(frames)
    log.info("running ml-sharp on %d frames (batch=%d, device=%s)",
             n, config.batch_size, device)

    t_infer = time.time()
    out_paths: list[Path] = []
    bytes_total = 0
    splats_total = 0

    for bi, batch in enumerate(iter_batches(frames, config.batch_size)):
        t0 = time.time()
        gaussians_list = runner.run_batch(batch, config.f_px_ratio)
        for j, g in enumerate(gaussians_list):
            blob, count = gaussians_to_splat_bytes(g)
            idx = bi * config.batch_size + j
            name = f"{config.output_prefix}{idx:0{config.output_pad}d}.splat"
            dst = splats_dir / name
            dst.write_bytes(blob)
            out_paths.append(dst)
            bytes_total += len(blob)
            splats_total += count
        log.info(
            "batch %d/%d done in %.1fs (%d frames, %.1f MB, %d splats avg)",
            bi + 1,
            (n + config.batch_size - 1) // config.batch_size,
            time.time() - t0,
            len(batch),
            sum(p.stat().st_size for p in out_paths[-len(batch):]) / (1024 * 1024),
            splats_total // max(len(out_paths), 1),
        )

    infer_s = time.time() - t_infer

    # 3. Manifest — small JSON file the renderer reads to know the
    # playback fps and frame sequence without having to glob the dir
    # again from the C++ side.
    manifest = {
        "fps": config.fps,
        "frame_count": len(out_paths),
        "prefix": config.output_prefix,
        "pad": config.output_pad,
        "source_video": video.name,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))

    if not config.keep_frames and frames_dir.exists():
        shutil.rmtree(frames_dir, ignore_errors=True)

    total = extract_s + infer_s
    log.info(
        "pipeline done in %.1f min: extract=%.1fs infer=%.1fs frames=%d total=%.1f MB → %s",
        total / 60,
        extract_s,
        infer_s,
        len(out_paths),
        bytes_total / (1024 * 1024),
        splats_dir,
    )
    return splats_dir
