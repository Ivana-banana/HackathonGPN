"""Filter out headers, footers, page numbers, and watermarks from Markdown.

The task statement says running matter (headers/footers/watermarks/page
numbers) must **not** appear in the output — any leakage hurts the metric.

Filters applied, in order:

1. Strip inline-watermark prefixes ("ЧЕРНОВИК Рис. 1. …" → "Рис. 1. …").
2. Drop lines that are nothing but a watermark token.
3. Drop lines that are nothing but a page number.
4. Drop any non-structural line that repeats ≥3 times within the same
   document — these are true running headers/footers that Docling did not
   segregate into page-furniture metadata.
5. Collapse runs of 3+ blank lines introduced by the above removals.

Table-cell content is preserved even when it matches a watermark: removing
it would wreck the table. Repeating cells therefore never trigger rule #4.
"""

from __future__ import annotations

import re
from collections import Counter

_WATERMARK_TOKENS = (
    "ЧЕРНОВИК",
    "КОНФИДЕНЦИАЛЬНО",
    "КОПИЯ",
    "ОБРАЗЕЦ",
    "НЕ ДЛЯ РАСПРОСТРАНЕНИЯ",
    "DRAFT",
    "CONFIDENTIAL",
    "COPY",
    "SAMPLE",
    "DO NOT DISTRIBUTE",
)
_WATERMARK_SET = frozenset(t.upper() for t in _WATERMARK_TOKENS)

# Longest-first so "НЕ ДЛЯ РАСПРОСТРАНЕНИЯ" is tried before "DO NOT DISTRIBUTE"
# (both span multiple whitespace-separated words).
_INLINE_WATERMARK_RE = re.compile(
    r"^(?:"
    + "|".join(sorted((re.escape(t) for t in _WATERMARK_TOKENS), key=len, reverse=True))
    + r")\s+",
    flags=re.IGNORECASE,
)

_PAGE_NUMBER_RE = re.compile(r"^\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*$")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

_REPEAT_MIN_COUNT = 3
_REPEAT_MAX_LEN = 120


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_structural(stripped: str) -> bool:
    """Markdown elements that must not be touched by the repeating-line filter."""
    if not stripped:
        return True
    first = stripped[0]
    return first in "|#-*>!`" or stripped.startswith("```")


def _is_watermark_line(stripped: str) -> bool:
    return stripped.upper() in _WATERMARK_SET


def _is_page_number_line(line: str) -> bool:
    return bool(_PAGE_NUMBER_RE.match(line))


def _strip_inline_watermark(line: str) -> str:
    """Remove a watermark prefix (with trailing whitespace) from *line*."""
    return _INLINE_WATERMARK_RE.sub("", line, count=1)


def _strip_inline_watermark_in_row(line: str) -> str:
    """Apply inline-watermark stripping to each cell of a Markdown table row."""
    parts = line.split("|")
    if len(parts) < 3:
        return line
    for i in range(1, len(parts) - 1):
        cell = parts[i]
        stripped = cell.strip()
        if not stripped:
            continue
        # Whole cell is a watermark token (no trailing text → prefix regex misses it).
        if stripped.upper() in _WATERMARK_SET:
            parts[i] = " "
            continue
        new_content = _strip_inline_watermark(stripped)
        if new_content != stripped:
            leading = cell[: len(cell) - len(cell.lstrip())]
            trailing = cell[len(cell.rstrip()):]
            parts[i] = f"{leading}{new_content}{trailing}"
    return "|".join(parts)


def _running_lines(lines: list[str]) -> frozenset[str]:
    """Lines that repeat ≥3 times outside tables/headings = running matter."""
    counts: Counter[str] = Counter()
    for line in lines:
        stripped = line.strip()
        if _is_table_line(line) or _is_structural(stripped):
            continue
        if len(stripped) > _REPEAT_MAX_LEN:
            continue
        counts[stripped] += 1
    return frozenset(s for s, c in counts.items() if c >= _REPEAT_MIN_COUNT)


def strip_running_matter(markdown: str) -> str:
    """Drop watermarks, bare page numbers, and running headers/footers."""
    raw_lines = markdown.splitlines()

    # Pass 1: strip inline watermarks (cells handled per-cell).
    prepped: list[str] = []
    for line in raw_lines:
        if _is_table_line(line):
            prepped.append(_strip_inline_watermark_in_row(line))
        else:
            prepped.append(_strip_inline_watermark(line))

    # Pass 2: identify running lines against the prepped content.
    running = _running_lines(prepped)

    kept: list[str] = []
    for line in prepped:
        if _is_table_line(line):
            kept.append(line)
            continue
        stripped = line.strip()
        if _is_watermark_line(stripped):
            continue
        if _is_page_number_line(line):
            continue
        if stripped and stripped in running:
            continue
        kept.append(line)

    joined = "\n".join(kept)
    joined = _MULTI_BLANK_RE.sub("\n\n", joined)
    return joined.rstrip() + "\n"
