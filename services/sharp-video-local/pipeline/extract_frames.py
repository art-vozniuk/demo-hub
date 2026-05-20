import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def extract_frames(
    video: Path,
    out_dir: Path,
    fps: float,
    max_frames: int | None,
) -> list[Path]:
    """Extract frames from a video at a fixed sampling rate via ffmpeg.

    Unlike gs-training-local (which dedup's with mpdecimate to thin out a
    handheld orbit shot), the video-to-splat-sequence player needs every
    frame in temporal order — a dropped frame would freeze the scene for
    one playback tick. So vsync=cfr + a strict fps filter, no dedup.
    """
    if not video.exists():
        raise FileNotFoundError(f"video not found: {video}")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH; brew install ffmpeg")

    out_dir.mkdir(parents=True, exist_ok=True)

    pattern = str(out_dir / "frame_%05d.jpg")
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video),
        "-vf", f"fps={fps}",
        "-qscale:v", "2",
        "-vsync", "cfr",
        pattern,
    ]
    log.info("running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)

    frames = sorted(out_dir.glob("frame_*.jpg"))
    if max_frames is not None and len(frames) > max_frames:
        # Keep the first max_frames — for video playback we want a
        # contiguous segment from t=0, not an evenly-spaced subset.
        for f in frames[max_frames:]:
            f.unlink()
        frames = frames[:max_frames]
        log.info("trimmed to first %d frames", max_frames)

    log.info("extracted %d frames to %s", len(frames), out_dir)
    return frames
