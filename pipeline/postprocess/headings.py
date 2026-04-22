"""Restore heading levels that Docling flattens.

Docling emits every section heading as ``##``, losing the real hierarchy.
The gold Markdown uses ``#`` for the document title, ``###`` for chapters/
sections ("Глава — …", "Раздел: …"), and ``####`` for numbered subsections
("1. Sharable even-keeled throughput").

This module only acts when *every* heading in the document is ``##`` — a
strong signal that Docling flattened the structure. If any other level is
present, we trust Docling's output and leave it alone.
"""

from __future__ import annotations

import html
import re

_HEADING_RE = re.compile(r"^(#+)\s+(.+?)\s*$")
_SUBSECTION_NUM_RE = re.compile(r"^\s*\d+\.\s")


def unescape_html_entities(markdown: str) -> str:
    """Decode HTML entities that Docling occasionally leaks into the markdown.

    Most commonly ``&amp;`` for a literal ``&``. Gold MD never contains entities.
    """
    return html.unescape(markdown)


def restore_em_dash_in_headings(markdown: str) -> str:
    """Replace ' - ' with ' — ' inside heading lines.

    Docling loses the em dash (U+2014) used as a separator in chapter and
    section titles, emitting a plain hyphen-minus instead. Replacement is
    scoped to lines starting with ``#`` to avoid touching body text where a
    hyphen with surrounding spaces may be intentional.
    """
    out_lines: list[str] = []
    for line in markdown.splitlines():
        if line.lstrip().startswith("#"):
            line = line.replace(" - ", " — ")
        out_lines.append(line)
    return "\n".join(out_lines)


def restore_heading_levels(markdown: str) -> str:
    """Promote the first heading to H1 and demote flat ``##`` to ``###``/``####``."""
    lines = markdown.splitlines()
    headings: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        m = _HEADING_RE.match(stripped)
        if m:
            headings.append((i, len(m.group(1)), m.group(2)))

    if not headings:
        return markdown
    if {h[1] for h in headings} != {2}:
        return markdown

    for idx, (i, _, text) in enumerate(headings):
        original = lines[i]
        leading = original[: len(original) - len(original.lstrip())]
        if idx == 0:
            new_hashes = "#"
        elif _SUBSECTION_NUM_RE.match(text):
            new_hashes = "####"
        else:
            new_hashes = "###"
        lines[i] = f"{leading}{new_hashes} {text}"
    return "\n".join(lines)
