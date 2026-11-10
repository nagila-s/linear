"""Tipo de página gravado no JSON (C6)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.openai_client import resolve_final_page_type


class FinalPageTypeTests(unittest.TestCase):
    def test_classified_type_wins(self) -> None:
        self.assertEqual(resolve_final_page_type("capa", "folha_de_rosto"), "capa")
        self.assertEqual(resolve_final_page_type("sumario", "conteudo"), "sumario")
        self.assertEqual(resolve_final_page_type("conheca", None), "conheca")

    def test_content_fallback_accepts_valid_model_type(self) -> None:
        self.assertEqual(resolve_final_page_type("conteudo", "ficha"), "ficha")
        self.assertEqual(resolve_final_page_type("conteudo", "Sumario"), "sumario")

    def test_content_fallback_rejects_invalid_model_type(self) -> None:
        self.assertEqual(resolve_final_page_type("conteudo", "folha_de_rosto"), "conteudo")
        self.assertEqual(resolve_final_page_type("conteudo", None), "conteudo")
        self.assertEqual(resolve_final_page_type(None, "secao"), "conteudo")


if __name__ == "__main__":
    unittest.main()
