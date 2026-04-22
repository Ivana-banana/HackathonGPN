"""Package the output directory into a leaderboard-ready ``submission.zip``.

Expected archive layout::

    submission.zip
    ├── document_001.md
    ├── document_002.md
    ├── ...
    └── images/
        ├── doc_1_image_1.png
        └── ...

No other files (including hidden ones) may be present.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


def build_submission_zip(output_dir: Path, zip_path: Path) -> Path:
    """Zip ``*.md`` files at the root and everything under ``images/``.

    Args:
        output_dir: Directory produced by the pipeline.
        zip_path: Destination archive path.

    Returns:
        ``zip_path``.
    """
    md_files = sorted(output_dir.glob("document_*.md"))
    images_dir = output_dir / "images"
    image_files = sorted(images_dir.glob("doc_*_image_*.png")) if images_dir.is_dir() else []

    if not md_files:
        raise FileNotFoundError(f"No document_*.md files in {output_dir}")

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for md in md_files:
            zf.write(md, arcname=md.name)
        for img in image_files:
            zf.write(img, arcname=f"images/{img.name}")

    return zip_path
