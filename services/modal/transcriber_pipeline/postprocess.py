"""LLM cleanup pass over a finished transcript.

Fixes recognition errors in place — punctuation, casing, names, broken
hyphenation — without rephrasing. Off by default: it is one generation per
segment and dominates the run.
"""

from __future__ import annotations

from typing import Callable

from .llm import CleanupLlm


DEFAULT_SYSTEM_PROMPT = (
    "You are a transcript post-processor. "
    "Fix ONLY recognition errors in this speech transcript — do not rephrase "
    "or rewrite.\n\n"
    "RULES:\n"
    "1. Fix punctuation: add commas, periods, question marks, dashes\n"
    "2. Fix capitalization of names and proper nouns\n"
    "3. Fix broken dashes (e.g. 'что -то' → 'что-то')\n"
    "4. If a glossary is provided, map misheard words to glossary terms "
    "when they sound similar\n"
    "5. NEVER delete or skip any word from the original text\n"
    "6. NEVER rephrase — only fix individual words in place\n"
    "7. Keep filler words and hesitations exactly as they are\n"
    "8. Output ONLY the corrected text, no explanations"
)

# Budget per segment: ~3 tokens per character covers non-latin scripts, but a
# runaway segment must not turn into a multi-minute generation, so cap it.
MAX_TOKENS_PER_CHAR = 3
MAX_TOKENS_CEILING = 1024

# How much of the previous segment to carry as context.
CONTEXT_CHARS = 200

StatusCallback = Callable[[str, str, str], None]


def build_prompt(
    text: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    glossary: str = "",
    prev_context: str = "",
) -> str:
    parts = [system_prompt]
    if glossary:
        parts.append(f"\nGlossary of domain terms:\n{glossary}")
    if prev_context:
        parts.append(f"\nPrevious context:\n{prev_context}")
    parts.append(f"\nFix this transcript:\n{text}")
    return "\n".join(parts)


def is_plausible(original: str, fixed: str) -> bool:
    """Guard against a model that dropped or padded the segment. Cleanup edits
    words in place, so a large length change means it did something else."""

    return len(original) * 0.3 <= len(fixed) <= len(original) * 3


def postprocess_segments(
    segments: list[dict],
    llm: CleanupLlm,
    glossary: str = "",
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    on_status: StatusCallback | None = None,
) -> list[dict]:
    """Return the segments with cleaned-up text. Anything implausible keeps its
    original text rather than being dropped."""

    total = len(segments)
    if total == 0:
        if on_status:
            on_status(
                "llm",
                "LLM post-processing",
                "No transcript segments need post-processing",
            )
        return []

    result: list[dict] = []
    prev_context = ""

    for i, seg in enumerate(segments):
        text = seg["text"]
        if on_status:
            on_status(
                "llm",
                "LLM post-processing",
                f"Post-processing segment {i + 1}/{total} ({len(text)} chars)",
            )

        fixed = llm.complete(
            build_prompt(
                text,
                system_prompt=system_prompt,
                glossary=glossary,
                prev_context=prev_context,
            ),
            max_tokens=min(len(text) * MAX_TOKENS_PER_CHAR, MAX_TOKENS_CEILING),
            temperature=0.1,
        ).strip()

        if not is_plausible(text, fixed):
            fixed = text

        result.append({**seg, "text": fixed})
        prev_context = fixed[-CONTEXT_CHARS:]

    if on_status:
        on_status(
            "llm", "LLM post-processing", f"Finished AI cleanup for {total} segments"
        )
    return result
