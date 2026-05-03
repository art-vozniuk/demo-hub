import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def extract_frames(
    video: Path,
    out_dir: Path,
    fps: float,
    deduplicate: bool,
    max_frames: int | None,
) -> list[Path]:
    """Extract frames from a video using ffmpeg.

    With `deduplicate=True`, uses the mpdecimate filter to drop near-identical
    consecutive frames — this typically halves the dataset size on phone video
    without losing coverage. Returns the sorted list of extracted frame paths.
    """
    if not video.exists():
        raise FileNotFoundError(f"video not found: {video}")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH; run install_dependencies.sh")

    out_dir.mkdir(parents=True, exist_ok=True)

    vf = f"fps={fps}"
    if deduplicate:
        vf += ",mpdecimate"

    pattern = str(out_dir / "frame_%05d.jpg")
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video),
        "-vf", vf,
        "-qscale:v", "2",
        "-vsync", "vfr",
        pattern,
    ]
    log.info("running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)

    frames = sorted(out_dir.glob("frame_*.jpg"))
    if max_frames is not None and len(frames) > max_frames:
        # Keep evenly spaced subset rather than chopping the tail.
        step = len(frames) / max_frames
        keep = {frames[int(i * step)] for i in range(max_frames)}
        for f in frames:
            if f not in keep:
                f.unlink()
        frames = sorted(out_dir.glob("frame_*.jpg"))
        log.info("downsampled to %d frames (cap=%d)", len(frames), max_frames)

    log.info("extracted %d frames to %s", len(frames), out_dir)
    return frames
