"""Repair words split across visual lines inside Markdown table cells.

The source PDFs render narrow table columns, which causes the extractor to
emit words broken across visual lines ("Подробн ость" for "Подробность").
The fix uses morphological signals from ``pymorphy3``: two adjacent tokens
are joined when the concatenation is a known Russian word and at least one
half of the split is itself *not* a valid word on its own. This avoids
merging legitimate phrases like "скрытый идея", where both halves are
complete words.
"""

from __future__ import annotations

import re
from functools import lru_cache

import pymorphy3
from spellchecker import SpellChecker

_morph = pymorphy3.MorphAnalyzer()
_english = SpellChecker(language="en")

# Short Cyrillic function-words that must never be treated as word-tails.
_STOPWORDS = frozenset(
    {
        "во", "с", "в", "у", "к", "на", "по", "от", "до", "из", "без", "над",
        "под", "при", "про", "для", "через", "между",
        "и", "а", "но", "да", "или", "же", "ни", "не", "ли", "бы",
        "что", "как", "где", "куда", "когда", "чем", "кто",
        "то", "та", "те", "тот", "этот", "эта", "это", "эти",
        "я", "ты", "он", "мы", "вы", "их", "его", "её",
        "уже", "ещё", "еще", "там", "тут",
        "один", "два", "три", "все", "сам",
    }
)


@lru_cache(maxsize=32768)
def _is_known_ru(word: str) -> bool:
    """True if *word* (lowercased) is in pymorphy's Russian dictionary."""
    for parse in _morph.parse(word.lower()):
        if parse.is_known:
            return True
    return False


@lru_cache(maxsize=32768)
def _is_known_en(word: str) -> bool:
    return word.lower() in _english


_BROKEN_WORD_RE_RU = re.compile(
    r"(?P<left>[А-ЯЁа-яё]{2,})(?P<gap>\s+)(?P<right>[а-яё]{1,6})(?=[\s.,;:!?)»\]]|$)"
)
_BROKEN_WORD_RE_EN = re.compile(
    r"(?P<left>[A-Za-z]{3,})(?P<gap>\s+)(?P<right>[a-z]{1,3})(?=[\s.,;:!?)»\]]|$)"
)


def _join_if_broken_ru(match: re.Match) -> str:
    left = match.group("left")
    right = match.group("right")

    if right.lower() in _STOPWORDS:
        return match.group(0)

    joined = left + right
    if len(joined) < 5:
        return match.group(0)

    if not _is_known_ru(joined):
        return match.group(0)

    # If both halves are also valid Russian words by themselves, the pair is
    # most likely legitimate prose ("скрытый идея"): refuse to merge.
    if _is_known_ru(left) and _is_known_ru(right):
        return match.group(0)

    return joined


def _join_if_broken_en(match: re.Match) -> str:
    """English counterpart — deliberately stricter.

    Join only when the concatenation is a known English word *and* the left
    half is not — that rules out "This us" → "Thisus" while still recovering
    "Participan t" → "Participant". pyspellchecker's vocabulary is modest so
    we accept missing a few novel compounds (e.g. "Synergized") to stay safe.
    """
    left = match.group("left")
    right = match.group("right")

    joined = left + right
    if len(joined) < 5:
        return match.group(0)

    if not _is_known_en(joined):
        return match.group(0)
    if _is_known_en(left):
        return match.group(0)

    return joined


def _repair_cell(cell: str) -> str:
    prev = None
    out = cell
    # Iterate: one pass joins one break; multi-split words need several passes.
    while prev != out:
        prev = out
        out = _BROKEN_WORD_RE_RU.sub(_join_if_broken_ru, out)
        out = _BROKEN_WORD_RE_EN.sub(_join_if_broken_en, out)
    return out


def _is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_separator_row(line: str) -> bool:
    return bool(re.match(r"^\s*\|[\s\-:|]+\|\s*$", line))


def drop_inner_separator_rows(markdown: str) -> str:
    """Drop ``| --- | --- |`` rows that appear in the middle of a table block.

    Docling occasionally emits a separator row inside the data section of a
    table (the first separator, right after the header row, is the legitimate
    one). These extras are pure noise and never appear in GT.
    """
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if not _is_table_row(lines[i]):
            out.append(lines[i])
            i += 1
            continue
        start = i
        while i < len(lines) and _is_table_row(lines[i]):
            i += 1
        block = lines[start:i]
        # Keep block[0] (header) and block[1] (legitimate separator) as-is.
        # In block[2:], drop any further separator rows.
        kept = block[:2]
        for row in block[2:]:
            if _is_separator_row(row):
                continue
            kept.append(row)
        out.extend(kept)
    return "\n".join(out)


def normalize_table_whitespace(markdown: str) -> str:
    """Collapse Docling's wide-padded table cells to GT's compact ``| x | y |`` style.

    Docling emits cells padded with many spaces to visually align columns
    (``| мгновение    |   ...``). GT uses a single space on each side of every
    pipe and renders each separator cell as ``---``. This function normalises
    only table rows (lines starting with ``|``); body text is left untouched.
    """
    out: list[str] = []
    for line in markdown.splitlines():
        if not _is_table_row(line):
            out.append(line)
            continue
        leading = line[: len(line) - len(line.lstrip())]
        cells = line.strip().split("|")[1:-1]
        if _is_separator_row(line):
            normalised = " | ".join("---" for _ in cells)
        else:
            normalised = " | ".join(c.strip() for c in cells)
        out.append(f"{leading}| {normalised} |")
    return "\n".join(out)


_HEADER_CELL_RE = re.compile(
    r"^[A-Za-zА-ЯЁа-яё][A-Za-zА-ЯЁа-яё\-]*(?:\s[A-Za-zА-ЯЁа-яё\-]+)*$"
)


def _cell_looks_like_header(cell: str) -> bool:
    s = cell.strip()
    if not (3 <= len(s) <= 40):
        return False
    if not s[0].isupper():
        return False
    return bool(_HEADER_CELL_RE.match(s))


def _row_looks_like_header(row: str) -> bool:
    """True when every cell looks like a column title (capitalised, alpha-only)."""
    cells = row.split("|")[1:-1]
    if len(cells) < 2:
        return False
    return all(_cell_looks_like_header(c) for c in cells)


def split_merged_tables(markdown: str) -> str:
    """Split tables that Docling fused by inserting a break at each mid-table header row.

    Docling sometimes emits two adjacent same-width tables as one block. The
    second table's header row ends up sitting among the first table's data.
    This function walks each table block and, whenever a data row has only
    header-like cells, closes the current table and starts a new one.
    """
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if not _is_table_row(lines[i]):
            out.append(lines[i])
            i += 1
            continue
        start = i
        while i < len(lines) and _is_table_row(lines[i]):
            i += 1
        out.extend(_split_block(lines[start:i]))
    return "\n".join(out)


def _split_block(block: list[str]) -> list[str]:
    if len(block) < 3 or not _is_separator_row(block[1]):
        return block
    result: list[str] = [block[0], block[1]]
    for row in block[2:]:
        if _row_looks_like_header(row):
            ncols = row.count("|") - 1
            result.append("")
            result.append(row)
            result.append("| " + " | ".join(["---"] * ncols) + " |")
        else:
            result.append(row)
    return result


def repair_tables(markdown: str) -> str:
    """Repair broken Cyrillic words within every table cell of *markdown*."""
    out_lines: list[str] = []
    for line in markdown.splitlines():
        if not _is_table_row(line) or _is_separator_row(line):
            out_lines.append(line)
            continue

        parts = line.split("|")
        for i in range(1, len(parts) - 1):
            parts[i] = _repair_pipe_cell(parts[i])
        out_lines.append("|".join(parts))

    return "\n".join(out_lines)


def _repair_pipe_cell(cell_with_padding: str) -> str:
    stripped = cell_with_padding.strip()
    if not stripped:
        return cell_with_padding
    leading = cell_with_padding[: len(cell_with_padding) - len(cell_with_padding.lstrip())]
    trailing = cell_with_padding[len(cell_with_padding.rstrip()):]
    return f"{leading}{_repair_cell(stripped)}{trailing}"
