"""CLI entry point: convert a directory of PDFs to Markdown.

Usage::

    python -m scripts.run --input-dir pdfs --output-dir output
    python -m scripts.run --input-dir pdfs --output-dir output --max-files 5
    python -m scripts.run --input-dir pdfs --output-dir output --zip submission.zip
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline.convert import ConverterConfig, build_converter
from pipeline.orchestrator import process_pdf
from pipeline.submission import build_submission_zip


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PDF → Markdown pipeline (GPN hackathon)")
    parser.add_argument("--input-dir", type=Path, required=True, help="Directory with input PDFs")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for output Markdown + images",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Process only the first N files (debug/smoke test)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip PDFs whose .md already exists in the output dir",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda", "mps"),
        default="auto",
        help="Docling accelerator",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Trade quality for speed (FAST TableFormer, smaller image scale)",
    )
    parser.add_argument("--no-ocr", action="store_true", help="Disable OCR")
    parser.add_argument(
        "--no-table-structure",
        action="store_true",
        help="Disable TableFormer table-structure detection",
    )
    parser.add_argument(
        "--zip",
        type=Path,
        default=None,
        help="After processing, package the output as a submission zip at this path",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if not args.input_dir.is_dir():
        sys.exit(f"ERROR: {args.input_dir} is not a directory")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(args.input_dir.glob("*.pdf"))
    if args.max_files is not None:
        pdfs = pdfs[: args.max_files]

    if args.skip_existing:
        before = len(pdfs)
        pdfs = [p for p in pdfs if not (args.output_dir / f"{p.stem}.md").is_file()]
        if before != len(pdfs):
            print(f"Skipping {before - len(pdfs)} already-processed file(s).", flush=True)

    if not pdfs:
        print("Nothing to do.", flush=True)
        return

    config = ConverterConfig(
        do_ocr=not args.no_ocr,
        do_table_structure=not args.no_table_structure,
        fast=args.fast,
        device=args.device,
    )

    print(f"Initialising Docling (device={config.device}, fast={config.fast})…", flush=True)
    converter = build_converter(config)
    print(f"Processing {len(pdfs)} PDF(s)…", flush=True)

    failed: list[str] = []
    for i, pdf in enumerate(pdfs, 1):
        print(f"  [{i}/{len(pdfs)}] {pdf.name}", end=" ", flush=True)
        try:
            process_pdf(pdf, args.output_dir, converter)
            print("OK", flush=True)
        except Exception as exc:  # noqa: BLE001 — we want to keep going on errors
            failed.append(pdf.name)
            print(f"FAILED: {exc!r}", flush=True)

    if failed:
        print(f"\n{len(failed)} file(s) failed: {failed}", flush=True)

    if args.zip is not None:
        print(f"\nBuilding submission zip at {args.zip}…", flush=True)
        build_submission_zip(args.output_dir, args.zip)
        print("Done.", flush=True)


if __name__ == "__main__":
    main()
