"""Orchestrate the per-PDF pipeline: Docling → post-processors → on-disk output.

The orchestrator is intentionally small so teammates can add new post-processing
steps by dropping files into ``pipeline.postprocess`` and registering them here.
"""

from __future__ import annotations

import gc
import shutil
from pathlib import Path

from docling.document_converter import DocumentConverter

from pipeline.convert import ConversionResult, convert_pdf, make_workdir
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
    normalize_image_names,
    reorder_figure_captions,
)
from pipeline.postprocess.tables import (
    drop_inner_separator_rows,
    normalize_table_whitespace,
    repair_tables,
    split_merged_tables,
)


def _clear_cuda_cache() -> None:
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        gc.collect()
        torch.cuda.empty_cache()


def process_pdf(
    pdf_path: Path,
    output_dir: Path,
    converter: DocumentConverter,
) -> Path:
    """Convert one PDF, apply post-processors, write ``<stem>.md`` to *output_dir*.

    Images land in ``output_dir / "images" / "doc_<n>_image_<k>.png"``.

    Returns:
        Path to the generated ``.md`` file.
    """
    stem = pdf_path.stem
    doc_num = doc_num_from_stem(stem)
    workdir = make_workdir(stem)

    try:
        result: ConversionResult = convert_pdf(pdf_path, converter, workdir)

        markdown = normalize_image_names(
            result.markdown,
            source_images_dir=result.images_dir,
            target_images_dir=output_dir / "images",
            doc_num=doc_num,
        )
        markdown = drop_table_images(markdown, output_dir / "images", doc_num)
        markdown = dedupe_image_links(markdown)
        markdown = reorder_figure_captions(markdown)
        markdown = strip_running_matter(markdown)
        markdown = split_merged_tables(markdown)
        markdown = drop_inner_separator_rows(markdown)
        markdown = repair_tables(markdown)
        markdown = normalize_table_whitespace(markdown)
        markdown = restore_heading_levels(markdown)
        markdown = restore_em_dash_in_headings(markdown)
        markdown = unescape_html_entities(markdown)
        markdown = lowercase_default_image_alt(markdown)

        out_md = output_dir / f"{stem}.md"
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(markdown, encoding="utf-8")
        return out_md
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        _clear_cuda_cache()
