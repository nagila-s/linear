"""Testes da extração de texto nativo (descarte de miniaturas)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.steps.pdf_text_styles import extract_page_text_styles


class _FakePage:
    def __init__(self, spans: list[tuple[str, float]]) -> None:
        self._spans = spans

    def get_fonts(self) -> list:
        return []

    def get_text(self, _kind: str) -> dict:
        lines = [
            {"spans": [{"text": text, "size": size, "font": "Nunito", "flags": 0}]}
            for text, size in self._spans
        ]
        return {"blocks": [{"type": 0, "lines": lines}]}


def _text(page: _FakePage) -> str:
    return "".join(run.text for run in extract_page_text_styles(page, 1).runs)


class MiniatureFilterTests(unittest.TestCase):
    def test_drops_tiny_text_when_miniatures_dominate(self) -> None:
        page = _FakePage(
            [
                ("Conecte as ideias", 10.2),
                ("No final de cada capítulo, essa seção traz atividades.", 9.9),
                ("1. Com suas palavras, fale sobre os primeiros habitantes do Brasil. " * 4, 2.5),
            ]
        )
        text = _text(page)
        self.assertIn("Conecte as ideias", text)
        self.assertIn("No final de cada capítulo", text)
        self.assertNotIn("primeiros habitantes", text)

    def test_keeps_small_credits_on_regular_page(self) -> None:
        page = _FakePage(
            [
                ("Família e comunidade. " * 10, 8.8),
                ("CESAR DINIZ/PULSAR IMAGENS", 3.8),
            ]
        )
        self.assertIn("CESAR DINIZ/PULSAR IMAGENS", _text(page))


if __name__ == "__main__":
    unittest.main()
