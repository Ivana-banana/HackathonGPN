"""Rename Docling's image artefacts to the hackathon-required format.

The evaluator checks that every ``![...](images/doc_<id>_image_<k>.png)`` link
matches an actual PNG in ``images/`` and that the ``<id>`` corresponds to the
host document. A mismatch zeroes the ``image_score`` sub-metric.

This module:

1. Walks the markdown left-to-right and, for each Docling image link, picks the
   next ordinal ``k`` and remaps the target filename.
2. Moves the PNG (or converts JPEG → PNG) to the shared submission images dir.
3. Rewrites the markdown links in place.

It also exposes ``drop_table_images``: when an image reference is immediately
followed by a Markdown table (the ``image_with_table`` block type in the task
spec), the gold MD has only the table text and no PNG. The helper removes such
refs and deletes the now-orphan PNGs, then renumbers remaining images so the
sequence stays dense (1, 2, 3, …).

Docling writes links of the form ``images/image_<n>_<hash>.(png|jpg)``.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

_DOCLING_IMG_LINK = re.compile(
    r"images[\\/](image_\d+_[a-f0-9]+\.(?:png|jpe?g))",
    flags=re.IGNORECASE,
)


def doc_num_from_stem(stem: str) -> int:
    """Parse ``document_051`` → ``51``. Raise if the stem is malformed."""
    try:
        _, tail = stem.rsplit("_", 1)
        return int(tail)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Cannot extract document number from stem {stem!r}") from exc


def _save_as_png(src: Path, dst: Path) -> None:
    """Move ``src`` to ``dst``, converting JPEG → PNG if necessary."""
    if src.suffix.lower() in (".jpg", ".jpeg"):
        from PIL import Image

        with Image.open(src) as im:
            im.save(dst, format="PNG")
        src.unlink()
    else:
        shutil.move(str(src), str(dst))


def normalize_image_names(
    markdown: str,
    source_images_dir: Path,
    target_images_dir: Path,
    doc_num: int,
) -> str:
    """Rename images and rewrite markdown links.

    Args:
        markdown: Docling-generated markdown.
        source_images_dir: Directory where Docling wrote the images.
        target_images_dir: Destination ``images/`` dir next to the final ``.md``.
        doc_num: Integer extracted from ``document_NNN`` (no leading zeros).

    Returns:
        Markdown with links rewritten to ``images/doc_<doc_num>_image_<k>.png``.
    """
    target_images_dir.mkdir(parents=True, exist_ok=True)

    renames: dict[str, str] = {}
    order = 1
    for match in _DOCLING_IMG_LINK.finditer(markdown):
        old_name = match.group(1)
        if old_name in renames:
            continue
        src = source_images_dir / old_name
        if not src.is_file():
            # Docling emitted a link to a non-existent file; drop the link later.
            continue
        new_name = f"doc_{doc_num}_image_{order}.png"
        renames[old_name] = new_name
        _save_as_png(src, target_images_dir / new_name)
        order += 1

    out = markdown
    for old, new in sorted(renames.items(), key=lambda kv: -len(kv[0])):
        # Docling may emit either slash style depending on OS; normalise to '/'.
        out = out.replace(f"images/{old}", f"images/{new}")
        out = out.replace(f"images\\{old}", f"images/{new}")
    return out


_FINAL_IMG_LINK_RE = re.compile(r"!\[[^\]]*\]\(images/(doc_\d+_image_\d+\.png)\)")
_IMG_LINE_RE = re.compile(r"^\s*!\[[^\]]*\]\(images/(doc_\d+_image_\d+\.png)\)\s*$")
_IMG_LINE_WITH_NUM_RE = re.compile(
    r"^\s*!\[[^\]]*\]\(images/doc_\d+_image_(\d+)\.png\)\s*$"
)
_FIG_CAPTION_RE = re.compile(r"^\s*(?:Рис\.|Fig\.)\s*(\d+)\.?\s+", re.IGNORECASE)
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")


def _next_nonblank(lines: list[str], start: int) -> int:
    j = start
    while j < len(lines) and not lines[j].strip():
        j += 1
    return j


def reorder_figure_captions(markdown: str) -> str:
    """Swap ``caption → image`` to GT's ``image → caption`` order.

    Docling sometimes emits a figure caption before its image. GT always has
    the image first, caption after. To avoid breaking an already-correct
    ``image_k → caption_{k+1}`` sequence, swap only when the caption's number
    equals the number baked into the following image's filename.
    """
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        cap_match = _FIG_CAPTION_RE.match(lines[i])
        if not cap_match:
            i += 1
            continue
        j = _next_nonblank(lines, i + 1)
        if j >= len(lines):
            break
        img_match = _IMG_LINE_WITH_NUM_RE.match(lines[j])
        if img_match and cap_match.group(1) == img_match.group(1):
            lines[i], lines[j] = lines[j], lines[i]
            i = j + 1
        else:
            i += 1
    return "\n".join(lines)


_DEFAULT_ALT_RE = re.compile(r"!\[Image\]\(")


def lowercase_default_image_alt(markdown: str) -> str:
    """Match GT's lowercase ``![image]`` alt text — Docling capitalises it."""
    return _DEFAULT_ALT_RE.sub("![image](", markdown)


def dedupe_image_links(markdown: str) -> str:
    """Drop repeated standalone image references to the same PNG.

    Docling occasionally emits two ``![...](images/doc_<n>_image_<k>.png)``
    references pointing at the same file (e.g. when an image straddles a
    page break). Gold MD links each image exactly once. We keep only the
    first standalone occurrence and drop later ones (along with a single
    blank line that may follow, to avoid leaving doubled blank lines).
    """
    lines = markdown.splitlines()
    seen: set[str] = set()
    drop_idx: set[int] = set()

    for i, line in enumerate(lines):
        m = _IMG_LINE_RE.match(line)
        if not m:
            continue
        fname = m.group(1)
        if fname in seen:
            drop_idx.add(i)
            if i + 1 < len(lines) and not lines[i + 1].strip():
                drop_idx.add(i + 1)
        else:
            seen.add(fname)

    if not drop_idx:
        return markdown
    return "\n".join(line for i, line in enumerate(lines) if i not in drop_idx)


def drop_table_images(markdown: str, images_dir: Path, doc_num: int) -> str:
    """Drop ``image_with_table`` references and renumber remaining images.

    An image reference on its own line that is immediately followed (ignoring
    blanks) by a table row is interpreted as the ``image_with_table`` content
    type: the gold has only the table text and no PNG. The matching PNG is
    deleted from *images_dir*. Surviving images are renumbered 1..N so the
    sequence stays dense.

    Returns the rewritten markdown.
    """
    lines = markdown.splitlines()
    doomed_filenames: set[str] = set()
    kept_lines: list[str] = []
    drop_line_indexes: set[int] = set()

    for i, line in enumerate(lines):
        m = _IMG_LINE_RE.match(line)
        if not m:
            continue
        fname = m.group(1)
        j = _next_nonblank(lines, i + 1)
        if j < len(lines) and _TABLE_LINE_RE.match(lines[j]):
            doomed_filenames.add(fname)
            drop_line_indexes.add(i)

    if not doomed_filenames:
        return markdown

    # 1) Remove doomed image-only lines.
    for idx, line in enumerate(lines):
        if idx in drop_line_indexes:
            continue
        kept_lines.append(line)
    reduced = "\n".join(kept_lines)

    # 2) Delete the doomed PNGs from disk.
    for fname in doomed_filenames:
        (images_dir / fname).unlink(missing_ok=True)

    # 3) Renumber remaining image references so the sequence is 1..N again.
    #    Walk in document order, assign new ordinals, and rename on disk.
    renames: dict[str, str] = {}
    new_order = 1
    for match in _FINAL_IMG_LINK_RE.finditer(reduced):
        old = match.group(1)
        if old in renames:
            continue
        new = f"doc_{doc_num}_image_{new_order}.png"
        if old != new:
            renames[old] = new
        new_order += 1

    # Apply renames both in markdown and on disk. Use a two-phase temp rename
    # to avoid name collisions when cycles exist (rare but possible).
    if renames:
        tmp_suffix = ".__tmp__"
        for old in renames:
            src = images_dir / old
            if src.is_file():
                src.rename(images_dir / (old + tmp_suffix))
        for old, new in renames.items():
            stg = images_dir / (old + tmp_suffix)
            if stg.is_file():
                stg.rename(images_dir / new)

        for old, new in sorted(renames.items(), key=lambda kv: -len(kv[0])):
            reduced = reduced.replace(f"images/{old}", f"images/{new}")

    return reduced
