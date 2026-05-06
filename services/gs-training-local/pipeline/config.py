from pathlib import Path

from pydantic import BaseModel, Field


class PipelineConfig(BaseModel):
    # Frame extraction
    fps: float = Field(default=2.0, description="Frames per second to sample from video")
    deduplicate: bool = Field(default=True, description="Use ffmpeg mpdecimate to drop near-duplicate frames")
    max_frames: int | None = Field(default=400, description="Hard cap on extracted frames; None = unlimited")

    # Frame quality filter (applied AFTER ffmpeg, BEFORE SfM)
    filter_frames: bool = Field(default=True, description="Drop blurry / dark / overexposed frames before SfM")
    filter_min_sharpness: float = Field(default=10.0, description="Absolute Laplacian-variance floor; below = catastrophic blur")
    filter_drop_below_pct: float = Field(default=10.0, description="Also drop frames below this percentile of sharpness (0 = disabled)")

    # SfM
    sfm_backend: str = Field(default="glomap", description="'glomap' (fast) or 'colmap' (reference)")
    matcher: str = Field(default="sequential", description="'sequential' (video-friendly) or 'exhaustive'")

    # Training
    trainer: str = Field(default="brush", description="'brush' or 'opensplat'")
    train_steps: int = Field(default=30000)
    brush_bin: Path | None = Field(default=None, description="Override path to brush_app binary")

    # Compression
    compress: bool = Field(default=True)
    splat_format: str = Field(default="splat32", description="'splat32' (32 bytes/gaussian, web-viewer compatible)")

    # Output
    keep_intermediate: bool = Field(default=False, description="Keep frames/sfm/raw PLY artifacts after success")
