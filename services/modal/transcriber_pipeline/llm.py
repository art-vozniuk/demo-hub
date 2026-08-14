"""Optional transcript-cleanup LLM: Qwen2.5 quantised to 4-bit NF4.

NF4 via bitsandbytes rather than AWQ/GPTQ on purpose: it needs no compiled
kernels beyond the bitsandbytes wheel, so the container image stays a plain
pip install. A 7B lands at ~5.5GB of VRAM, which co-exists with Whisper and
pyannote on a 24GB card.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path


log = logging.getLogger(__name__)

LLM_MODEL = os.getenv("TRANSCRIBER_LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")


def is_cached(model: str | None = None) -> bool:
    """True when the weights are already in the local HF cache."""

    repo = model or LLM_MODEL
    hf_home = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface"))
    repo_dir = hf_home / "hub" / f"models--{repo.replace('/', '--')}"
    return repo_dir.exists() and any(repo_dir.iterdir())


class CleanupLlm:
    def __init__(self, model: str | None = None) -> None:
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
        )

        if not torch.cuda.is_available():
            raise RuntimeError(
                "Transcript cleanup requires a CUDA GPU (4-bit bitsandbytes "
                "kernels are GPU-only)."
            )

        self.model_id = model or LLM_MODEL
        log.info(f"loading {self.model_id} in 4-bit NF4")
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        # No explicit dtype: bnb_4bit_compute_dtype already pins the compute
        # precision, and from_pretrained's dtype kwarg was renamed across
        # transformers versions.
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            ),
            device_map={"": 0},
        )
        self._model.eval()

    def complete(
        self,
        user_message: str,
        *,
        max_tokens: int,
        temperature: float = 0.1,
    ) -> str:
        """Apply the model's chat template to `user_message` and generate."""

        import torch

        text = self._tokenizer.apply_chat_template(
            [{"role": "user", "content": user_message}],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self._tokenizer(text, return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            output = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=temperature > 0,
                temperature=temperature if temperature > 0 else None,
                pad_token_id=self._tokenizer.pad_token_id
                or self._tokenizer.eos_token_id,
            )
        # generate() returns prompt + completion; keep only what was added.
        generated = output[0][inputs["input_ids"].shape[-1] :]
        return self._tokenizer.decode(generated, skip_special_tokens=True)
