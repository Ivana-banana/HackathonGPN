"""Docling-based PDF → Markdown conversion.

Thin wrapper around ``docling.DocumentConverter`` that:

* builds a converter with sensible defaults for the hackathon,
* converts a single PDF to Markdown text plus a side-folder of PNG images,
* exposes the intermediate images directory so post-processors can rename files.

All post-processing (image renaming, header/footer filtering, …) lives in
``pipeline.postprocess`` and is orchestrated by ``pipeline.orchestrator``.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


def _patch_cv2_set_num_threads() -> None:
    """Docling-IBM-models calls ``cv2.setNumThreads``; some opencv builds miss it."""
    try:
        import cv2
    except ImportError:
        return
    if not hasattr(cv2, "setNumThreads"):
        cv2.setNumThreads = lambda _n: None  # type: ignore[method-assign]


def _silence_google_logs() -> None:
    os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
    os.environ.setdefault("GLOG_minloglevel", "2")


_silence_google_logs()
_patch_cv2_set_num_threads()


# Imports below must run AFTER the env-var / monkey-patch setup above.
from docling.datamodel.accelerator_options import AcceleratorOptions  # noqa: E402
from docling.datamodel.base_models import InputFormat  # noqa: E402
from docling.datamodel.pipeline_options import (  # noqa: E402
    TableFormerMode,
    TableStructureOptions,
    ThreadedPdfPipelineOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption  # noqa: E402
from docling_core.types.doc.base import ImageRefMode  # noqa: E402


@dataclass(frozen=True)
class ConverterConfig:
    """User-facing knobs for Docling.

    Defaults target correctness over speed; flip ``fast`` for CPU-only runs.
    """

    do_ocr: bool = True
    do_table_structure: bool = True
    fast: bool = False
    device: str = "auto"  # auto | cpu | cuda | mps


def build_converter(config: ConverterConfig) -> DocumentConverter:
    """Construct a Docling ``DocumentConverter`` according to *config*."""
    if config.device != "auto":
        os.environ["DOCLING_DEVICE"] = config.device

    if config.fast:
        images_scale = 0.88
        table_mode = TableFormerMode.FAST
    else:
        images_scale = 1.0
        table_mode = TableFormerMode.ACCURATE

    pipeline_options = ThreadedPdfPipelineOptions(
        do_ocr=config.do_ocr,
        do_table_structure=config.do_table_structure,
        generate_picture_images=True,
        images_scale=images_scale,
        table_structure_options=TableStructureOptions(mode=table_mode),
        accelerator_options=AcceleratorOptions(),
    ).model_copy(deep=True)

    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        },
    )


@dataclass
class ConversionResult:
    """Outcome of converting a single PDF."""

    markdown: str
    images_dir: Path  # temp directory containing images/*.png as produced by Docling


def convert_pdf(
    pdf_path: Path,
    converter: DocumentConverter,
    workdir: Path,
) -> ConversionResult:
    """Convert *pdf_path* to Markdown.

    Images are written under ``workdir / "images"`` with Docling's native names
    (``image_<n>_<hash>.png``). Renaming to the submission-required format
    ``doc_<id>_image_<order>.png`` is done later by
    ``pipeline.postprocess.images``.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    md_path = workdir / f"{pdf_path.stem}.md"

    result = converter.convert(str(pdf_path))
    result.document.save_as_markdown(
        md_path,
        artifacts_dir=Path("images"),
        image_mode=ImageRefMode.REFERENCED,
    )

    return ConversionResult(
        markdown=md_path.read_text(encoding="utf-8"),
        images_dir=workdir / "images",
    )


def make_workdir(stem: str) -> Path:
    """Create a scratch directory for one conversion; caller is responsible for cleanup."""
    return Path(tempfile.mkdtemp(prefix=f"docling_{stem}_"))
