"""Prompt for image-edit models that re-letter one dialogue ("F5").

Chosen over five rounds of tests on real pages with Qwen-Image 2.1 and with
API models: one paragraph, quoted source and target text, affirmative wording
(asking to "erase" left half-erased lettering), the line breaks spelled out,
and no style hints (size/position/background words made the models redraw
the balloon or the art). Words split across lines with a hyphen were the main
source of misspellings, so those lines are re-joined first.
"""
from __future__ import annotations

PROMPT_VERSION = "f5.1"   # part of the edit cache key: a new prompt is a new edit
NEWLINE_FROM = 7          # long blocks read better one line per row than as a quoted list


def rewrap(lines: list[str], text: str) -> list[str]:
    """Re-join lines broken mid-word with a hyphen (a hyphen the text itself
    does not have) and rebalance word-wise over the remaining line count."""
    words = " ".join(text.split()).split()
    breaks = sum(1 for a, b in zip(lines, lines[1:])
                 if a.endswith("-") and b.split() and (a[:-1].split() or [""])[-1] + b.split()[0] in words)
    if not breaks or not words:
        return lines
    n = min(len(words), max(1, len(lines) - breaks))
    memo: dict[tuple[int, int], tuple[int, list[list[str]]]] = {}

    def best(i: int, k: int) -> tuple[int, list[list[str]]]:
        # split words[i:] into k consecutive lines minimising the longest one
        if k == 1:
            return len(" ".join(words[i:])), [words[i:]]
        if (i, k) not in memo:
            options = []
            for j in range(i + 1, len(words) - k + 2):
                rest_len, rest = best(j, k - 1)
                options.append((max(len(" ".join(words[i:j])), rest_len), [words[i:j]] + rest))
            memo[(i, k)] = min(options, key=lambda t: t[0])
        return memo[(i, k)]

    return [" ".join(g) for g in best(0, n)[1]]


def is_vertical(lines: list[str]) -> bool:
    """One or two characters per line: a stacked column."""
    return len(lines) >= 3 and all(len(line) <= 2 for line in lines)


def _quoted(lines: list[str]) -> str:
    return ", ".join(f'"{line}"' for line in lines)


def build_prompt(source: str, target: str, lines: list[str], language: str = "") -> str:
    """`lines`: suggested line breaks (the scanline layout); `language`: name of
    the drawn language."""
    lines = rewrap([line for line in lines if line.strip()] or [target], target)
    src, tgt = " ".join(source.split()), " ".join(target.split())
    lang = f"{language} text" if language else "new text"
    n = f"{len(lines)} line{'s' if len(lines) > 1 else ''}"
    vertical = is_vertical(lines)
    if vertical:
        layout = f"as a vertical column, one character per line from top to bottom: {_quoted(lines)}. "
    elif len(lines) >= NEWLINE_FROM:
        layout = f"in exactly {n}, with these line breaks:\n" + "\n".join(lines) + "\n"
    else:
        layout = f"in exactly {n}, in this order: {_quoted(lines)}. "
    # In a one-character column "no word split across lines" made models drop characters.
    no_split = "" if vertical else " and no word split across lines"
    return (f'Replace the lettering "{src}" in the image with the {lang} "{tgt}", written {layout}'
            f'Every character is literal: copy each letter, accent and punctuation mark exactly, with no letters '
            f'added or dropped{no_split}. Paint the {lang} in the same place, at the same letter height, in the same '
            f'lettering style as the original: the same typeface, stroke weight, colour, outline, slant and '
            f'orientation, so that the {lang} fully takes the place of the original lettering. '
            f'Keep the balloon, the artwork and all other text in the image unchanged.')
