import logging
from pathlib import Path

import click
from rich.logging import RichHandler

from pipeline.config import PipelineConfig
from pipeline.orchestrator import run_pipeline


@click.group()
def main():
    """Local video → per-frame .splat pipeline (Mac, MPS)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )


@main.command()
@click.option("--video",  required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--fps",         default=24.0, type=float, show_default=True)
@click.option("--max-frames",  default=240,  type=int,   show_default=True,
              help="Cap on frame count; 0 = unlimited")
@click.option("--batch-size",  default=4,    type=int,   show_default=True,
              help="ml-sharp batch size. M2 Max comfortably handles 4; bump if you have headroom.")
@click.option("--device",      default="auto",
              type=click.Choice(["auto", "mps", "cuda", "cpu"]), show_default=True)
@click.option("--f-px-ratio",  default=0.9,  type=float, show_default=True,
              help="Focal length in pixels = ratio * image_width (default ~62° hFOV).")
@click.option("--keep-frames", is_flag=True,
              help="Keep the raw .jpg frames after generating the .splat sequence.")
def run(video, output, fps, max_frames, batch_size, device, f_px_ratio, keep_frames):
    """Run the full pipeline."""
    config = PipelineConfig(
        fps=fps,
        max_frames=max_frames if max_frames > 0 else None,
        batch_size=batch_size,
        device=device,
        f_px_ratio=f_px_ratio,
        keep_frames=keep_frames,
    )
    out = run_pipeline(video=video, output=output, config=config)
    click.echo(f"\n✓ pipeline finished: {out}")


if __name__ == "__main__":
    main()
