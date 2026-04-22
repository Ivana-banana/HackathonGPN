"""Re-apply current post-processors to an existing output directory in place.

Avoids re-running Docling when only the post-processing logic changed.
Input: a directory with ``document_NNN.md`` produced by a prior pipeline run.
Output: same directory, MDs rewritten with the current post-processing.

Usage::

    python -m scripts.reprocess --output-dir output
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pipeline.postprocess.headers_footers import strip_running_matter
from pipeline.postprocess.headings import (
    restore_em_dash_in_headings,
    restore_heading_levels,
    unescape_html_entities,
)
from pipeline.postprocess.images import (
    dedupe_image_links,
    doc_num_from_stem,
    drop_table_images,
    lowercase_default_image_alt,
    reorder_figure_captions,
)
from pipeline.postprocess.tables import (
    drop_inner_separator_rows,
    normalize_table_whitespace,
    repair_tables,
    split_merged_tables,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-apply post-processors in place")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    mds = sorted(args.output_dir.glob("document_*.md"))
    if not mds:
        raise SystemExit(f"No document_*.md found in {args.output_dir}")

    images_dir = args.output_dir / "images"
    changed = 0
    for md in mds:
        src = md.read_text(encoding="utf-8")
        out = drop_table_images(src, images_dir, doc_num_from_stem(md.stem))
        out = dedupe_image_links(out)
        out = reorder_figure_captions(out)
        out = strip_running_matter(out)
        out = split_merged_tables(out)
        out = drop_inner_separator_rows(out)
        out = repair_tables(out)
        out = normalize_table_whitespace(out)
        out = restore_heading_levels(out)
        out = restore_em_dash_in_headings(out)
        out = unescape_html_entities(out)
        out = lowercase_default_image_alt(out)
        if out != src:
            md.write_text(out, encoding="utf-8")
            changed += 1
    print(f"Rewrote {changed}/{len(mds)} file(s) in {args.output_dir}")


if __name__ == "__main__":
    main()
