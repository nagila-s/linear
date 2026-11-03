"""Extrator de figuras v3 no contrato do Linear, atrás de PDF_FIGURE_EXTRACTOR."""

from __future__ import annotations

import asyncio
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image

from src.pipeline.steps.pdf_figures_v3 import EXTRACTOR_VERSION, extract_images_v3
from src.pipeline.steps.preprocess import PageArtifact
from src.vendor.pdf_figure_extractor.demo_pdf import build_sample_textbook_pdf
from src.worker.pipeline.stages import extract_images

SAMPLE_PDF = build_sample_textbook_pdf()
TEXT_ONLY_PAGES = {4, 5}


class AdapterTests(unittest.TestCase):
    def test_figures_follow_reading_order_with_metadata(self) -> None:
        items = [item for item in extract_images_v3(SAMPLE_PDF) if item.kind != "page"]
        self.assertTrue(items)
        by_page: dict[int, list[int]] = {}
        for item in items:
            by_page.setdefault(item.page_number, []).append(item.image_index)
            self.assertEqual(item.meta["extractor"], EXTRACTOR_VERSION)
            self.assertEqual(set(item.meta["bbox"]), {"x", "y", "width", "height"})
            image = Image.open(io.BytesIO(item.image_bytes))
            self.assertEqual(image.mode, "RGB")
            self.assertEqual((item.width_px, item.height_px), image.size)
            self.assertGreaterEqual(max(image.size), 760)
        for indexes in by_page.values():
            self.assertEqual(indexes, list(range(1, len(indexes) + 1)))
        self.assertTrue(TEXT_ONLY_PAGES.isdisjoint(by_page))

    def test_page_without_figure_gets_whole_page_only_with_fallback(self) -> None:
        with_fallback = extract_images_v3(SAMPLE_PDF, render_fallback_dpi=72)
        pages = {item.page_number for item in with_fallback if item.kind == "page"}
        self.assertTrue(TEXT_ONLY_PAGES <= pages)
        without = extract_images_v3(SAMPLE_PDF, render_fallback_dpi=0)
        self.assertFalse([item for item in without if item.kind == "page"])


class _Storage:
    def __init__(self, checkpoint: dict | None = None) -> None:
        self.checkpoint = checkpoint
        self.saved: dict | None = None
        self.figures: list[str] = []

    def download_json_if_exists(self, *_args) -> dict | None:
        return self.checkpoint

    def download_by_storage_path(self, path: str) -> bytes:
        return SAMPLE_PDF if path == "livro.pdf" else b"png"

    def upload_page(self, *, isbn, page_name, content, process_version) -> str:
        return f"pages/{page_name}.png"

    def upload_figure(self, *, isbn, page_folder, figure_name, content, process_version) -> str:
        path = f"figures/{page_folder}/{figure_name}"
        self.figures.append(path)
        return path

    def upload_json(self, isbn, process_version, job_id, name, payload) -> None:
        self.saved = payload


class _Repo:
    def __init__(self) -> None:
        self.next_id = 0

    def add_page(self, *_args) -> str:
        self.next_id += 1
        return f"page-{self.next_id}"

    def add_figure(self, **_kwargs) -> str:
        self.next_id += 1
        return f"fig-{self.next_id}"


def _fake_pages(_pdf: bytes, **_kwargs) -> list[PageArtifact]:
    return [PageArtifact(n, f"p{n:04}", b"png", 100, 140) for n in range(1, 7)]


def _ctx(storage: _Storage, extractor: str) -> dict:
    return {
        "storage": storage,
        "artifacts_repo": _Repo(),
        "book_id": "book",
        "isbn": "isbn",
        "job_id": "job",
        "process_version": "lin-v2",
        "pdf_storage_path": "livro.pdf",
        "pdf_render_dpi": 72,
        "figure_extractor": extractor,
    }


class StageTests(unittest.TestCase):
    def _run(self, storage: _Storage, extractor: str) -> dict:
        with mock.patch.object(extract_images, "preprocess_pdf", _fake_pages):
            return asyncio.run(extract_images.run(_ctx(storage, extractor)))

    def test_v3_records_extractor_and_figure_metadata(self) -> None:
        storage = _Storage()
        ctx = self._run(storage, "v3")
        self.assertEqual(storage.saved["figure_extractor"], EXTRACTOR_VERSION)
        detected = [fig for fig in ctx["figures"] if "extraction" in fig]
        self.assertTrue(detected)
        self.assertEqual(detected[0]["figure_key"], "fig1")
        self.assertEqual(detected[0]["extraction"]["extractor"], EXTRACTOR_VERSION)
        # Páginas só de texto continuam com a página inteira como fig1.
        for page in TEXT_ONLY_PAGES:
            self.assertEqual(ctx["figure_keys_by_page"][page], ["fig1"])

    def test_legacy_is_default_and_unchanged(self) -> None:
        storage = _Storage()
        ctx = self._run(storage, "")
        self.assertEqual(storage.saved["figure_extractor"], "legacy")
        self.assertFalse([fig for fig in ctx["figures"] if "extraction" in fig])

    def test_v3_failure_falls_back_to_legacy(self) -> None:
        storage = _Storage()
        with mock.patch.object(extract_images, "extract_images_v3", side_effect=ImportError("cv2")):
            ctx = self._run(storage, "v3")
        self.assertEqual(storage.saved["figure_extractor"], "legacy")
        self.assertTrue(ctx["figures"])

    def test_retry_reuses_checkpoint_even_if_extractor_changed(self) -> None:
        first = _Storage()
        self._run(first, "legacy")
        retry = _Storage(checkpoint=first.saved)
        with mock.patch.object(extract_images, "extract_images_v3") as v3:
            ctx = self._run(retry, "v3")
        v3.assert_not_called()
        self.assertIsNone(retry.saved)
        self.assertEqual(len(ctx["figures"]), len(first.saved["figures"]))


if __name__ == "__main__":
    unittest.main()
