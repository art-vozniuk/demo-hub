import logging
from pathlib import Path

import click
from rich.logging import RichHandler

from pipeline.config import PipelineConfig
from pipeline.orchestrator import run_pipeline


@click.group()
def main():
    """Local video → Gaussian Splatting pipeline (Mac)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )


@main.command()
@click.option("--video",  required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--fps",         default=2.0,    type=float, show_default=True)
@click.option("--max-frames",  default=400,    type=int,   show_default=True, help="Cap on frame count; 0 = unlimited")
@click.option("--sfm",         default="glomap",  type=click.Choice(["glomap", "colmap"]), show_default=True)
@click.option("--matcher",     default="sequential", type=click.Choice(["sequential", "exhaustive"]), show_default=True)
@click.option("--trainer",     default="brush",   type=click.Choice(["brush", "opensplat"]), show_default=True)
@click.option("--steps",       default=30000,  type=int,   show_default=True)
@click.option("--no-compress", is_flag=True, help="Skip PLY → .splat compression")
@click.option("--keep-intermediate", is_flag=True, help="Don't delete frames/sfm/raw PLY after success")
@click.option("--brush-bin",   default=None,   type=click.Path(exists=True, dir_okay=False, path_type=Path))
def run(video, output, fps, max_frames, sfm, matcher, trainer, steps, no_compress, keep_intermediate, brush_bin):
    """Run the full pipeline."""
    config = PipelineConfig(
        fps=fps,
        max_frames=max_frames if max_frames > 0 else None,
        sfm_backend=sfm,
        matcher=matcher,
        trainer=trainer,
        train_steps=steps,
        compress=not no_compress,
        keep_intermediate=keep_intermediate,
        brush_bin=brush_bin,
    )
    out = run_pipeline(video=video, output=output, config=config)
    click.echo(f"\n✓ pipeline finished: {out}")


if __name__ == "__main__":
    main()
