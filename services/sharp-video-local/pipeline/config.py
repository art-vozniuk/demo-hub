from pathlib import Path

from pydantic import BaseModel, Field


class PipelineConfig(BaseModel):
    # Frame extraction. No mpdecimate / dedup — we want a continuous
    # frame sequence for playback (a dropped frame is a frozen scene
    # for ~42ms in the player, which reads as a hitch).
    fps: float = Field(default=24.0, description="Frames per second to sample from the video")
    max_frames: int | None = Field(
        default=240,
        description="Hard cap on extracted frames; None = unlimited. At 24 fps default this is ~10s.",
    )

    # ml-sharp inference. Batching trades VRAM for throughput: on an
    # M2 Max with 32GB unified RAM, batch=4 is comfortable; batch=8
    # gets close to swap territory once the rest of the OS is loaded.
    batch_size: int = Field(default=4, description="Number of frames per ml-sharp forward pass")
    # Override autodetected device. 'auto' picks 'mps' on macOS w/ MPS,
    # otherwise 'cuda' / 'cpu'.
    device: str = Field(default="auto", description="'auto' | 'mps' | 'cuda' | 'cpu'")
    # Field-of-view defaults; ml-sharp wants a focal-length-in-pixels.
    # ~62° hFOV (typical phone main lens) corresponds to f_px ≈ 0.9 * W.
    # This matches the default in the Modal sharp service.
    f_px_ratio: float = Field(default=0.9, description="Focal length in pixels = ratio * image_width")

    # Output naming + housekeeping
    keep_frames: bool = Field(default=False, description="Keep the raw .jpg frames after .splat generation")
    output_prefix: str = Field(default="frame_", description="Splat filename prefix; <prefix>00001.splat")
    output_pad: int = Field(default=5, description="Zero-padding width for splat indices")
