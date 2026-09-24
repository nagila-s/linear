"""Testes de completude / texto nativo."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.steps.page_completeness import (
    editorial_char_count,
    format_page_text_context,
    is_linearization_incomplete,
    looks_cut_mid_sentence,
)


class PageCompletenessTests(unittest.TestCase):
    def test_format_context_empty(self) -> None:
        self.assertEqual(format_page_text_context(""), "")
        self.assertEqual(format_page_text_context("   "), "")

    def test_format_context_has_marker(self) -> None:
        block = format_page_text_context("Poema completo aqui.")
        self.assertIn("TEXTO NATIVO", block)
        self.assertIn("Poema completo aqui.", block)

    def test_incomplete_short_vs_pdf(self) -> None:
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 92,
            "conteudo": [
                {
                    "tipo": "atividade",
                    "instrucao": "ENEM",
                    "itens": [
                        {
                            "tipo": "item",
                            "texto": (
                                "Nao serei o poeta de um mundo caduco. "
                                "Tambem nao cantarei o mundo futuro. "
                                "Estou preso a vida e olho"
                            ),
                        }
                    ],
                }
            ],
        }
        self.assertTrue(is_linearization_incomplete(page, pdf_char_count=3600))
        self.assertTrue(looks_cut_mid_sentence(page))

    def test_complete_enough(self) -> None:
        long_text = ("Linha do poema. " * 200).strip()
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 92,
            "conteudo": [
                {"tipo": "titulo_4", "texto": long_text},
                {"tipo": "atividade", "instrucao": "Responda.", "itens": []},
            ],
        }
        self.assertFalse(is_linearization_incomplete(page, pdf_char_count=len(long_text) + 50))
        self.assertGreater(editorial_char_count(page), 1000)

    def test_normalize_columns_schema(self) -> None:
        from src.pipeline.steps.page_completeness import normalize_page_structure

        page = {
            "pagina": 92,
            "coluna_esquerda": [{"tipo": "texto", "texto": "esquerda"}],
            "coluna_direita": [{"tipo": "texto", "texto": "direita"}],
        }
        normalized = normalize_page_structure(page)
        assert normalized is not None
        self.assertEqual(len(normalized["conteudo"]), 2)
        self.assertNotIn("coluna_esquerda", normalized)

    def test_enunciado_counts(self) -> None:
        page = {
            "conteudo": [
                {
                    "tipo": "questao",
                    "enunciado": "A" * 100,
                    "itens": [{"letra": "a", "texto": "B" * 50}],
                }
            ]
        }
        self.assertGreaterEqual(editorial_char_count(page), 150)

    def test_scaffold_covers_pdf_text(self) -> None:
        from src.pipeline.steps.page_completeness import scaffold_page_from_plain_text

        plain = ("Poema linha.\n" * 100) + "\n\n" + ("Questao longa. " * 80)
        page = scaffold_page_from_plain_text(plain, page_number=10, printed_page=92)
        self.assertTrue(page.get("conteudo"))
        self.assertGreater(editorial_char_count(page), len(plain) * 0.9)
        self.assertFalse(is_linearization_incomplete(page, pdf_char_count=len(plain)))

    def test_expand_cut_poem(self) -> None:
        from src.pipeline.steps.page_completeness import expand_cut_texts_from_plain

        plain = (
            "Nao serei o poeta de um mundo caduco. "
            "Tambem nao cantarei o mundo futuro. "
            "Estou preso a vida e olho meus companheiros. "
            "Estao taciturnos mas nutrem grandes esperancas."
        )
        page = {
            "conteudo": [
                {
                    "tipo": "titulo_4",
                    "texto": (
                        "\u201c\nNao serei o poeta de um mundo caduco. "
                        "Tambem nao cantarei o mundo futuro. Estou preso"
                    ),
                }
            ]
        }
        expanded = expand_cut_texts_from_plain(page, plain)
        assert expanded is not None
        text = expanded["conteudo"][0]["texto"]
        self.assertIn("companheiros", text)
        self.assertGreater(len(text), 100)


if __name__ == "__main__":
    unittest.main()
