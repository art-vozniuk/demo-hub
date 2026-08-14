"""Audio → diarized transcript, for Linux + NVIDIA.

Ported from the Apple-Silicon pipeline in
[art-vozniuk/transcriber](https://github.com/art-vozniuk/transcriber) (MIT).
That repo stays as it is — MLX-Whisper on a Mac, with its own Gradio app; this
is an independent CUDA implementation of the same stages, so neither side
constrains the other.

What the port changes, and why:

- **ASR**: MLX-Whisper → faster-whisper (CTranslate2, float16). MLX is
  macOS-only. CTranslate2 exposes the same word timestamps, the same
  `initial_prompt`, and the same three confidence signals the hallucination
  filter reads, so the stage behaves the same.
- **VAD**: torch.hub Silero → the Silero ONNX bundled inside the
  faster-whisper wheel. No repo clone, no network at run time.
- **Cleanup LLM**: MLX 4-bit Qwen → the same Qwen quantised to 4-bit NF4 via
  transformers + bitsandbytes.
- **Audio decode**: torchaudio → ffmpeg, which is the only decoder that
  reliably reads m4a/opus/webm and is already in the container.

Everything else — VAD chunking, the hallucination filter, word-level speaker
assignment with flicker smoothing, segment merging — is the same logic.

Shipped into the Modal image via `.add_local_python_source(...)`; see
services/modal/transcriber/app.py.
"""

from .pipeline import TranscriptionPipeline, TranscriptionResult

__all__ = ["TranscriptionPipeline", "TranscriptionResult"]
