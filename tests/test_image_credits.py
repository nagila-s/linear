"""Créditos de imagem não entram no texto editorial nem disparam lacuna."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.steps.image_credits import is_image_credit, omit_image_credits, strip_image_credits
from src.pipeline.steps.text_gap_fill import find_missing_pdf_spans


class ImageCreditTests(unittest.TestCase):
    def test_photographer_slash_credit(self) -> None:
        self.assertTrue(is_image_credit("ALESSANDRA NOHVAIS/GRUPO VILAVOX"))
        self.assertTrue(is_image_credit("João Silva/Shutterstock"))
        self.assertTrue(is_image_credit("Acervo da editora"))

    def test_bibliographic_source_stays(self) -> None:
        biblio = (
            "BOTELHO, Luiz Felipe. O segredo da arca de Trancoso. "
            "Prefácio. São Paulo: Paulinas, 2007. p. 7-8."
        )
        self.assertFalse(is_image_credit(biblio))
        self.assertIn("Paulinas, 2007", strip_image_credits(biblio))

    def test_strips_credit_glued_to_sentence(self) -> None:
        raw = (
            "Depois, comente com os colegas. ALESSANDRA NOHVAIS/GRUPO VILAVOX "
            "OS ELEMENTOS VISUAIS"
        )
        cleaned = strip_image_credits(raw)
        self.assertNotIn("ALESSANDRA", cleaned)
        self.assertIn("comente com os colegas", cleaned)
        self.assertIn("OS ELEMENTOS VISUAIS", cleaned)

    def test_credit_is_not_a_missing_span(self) -> None:
        pdf = (
            "Outro elemento essencial à linguagem teatral é o conjunto de sons. "
            "ALESSANDRA NOHVAIS/GRUPO VILAVOX"
        )
        json_text = "Outro elemento essencial à linguagem teatral é o conjunto de sons."
        missing = find_missing_pdf_spans(pdf, json_text)
        self.assertFalse(any("ALESSANDRA" in span or "VILAVOX" in span for span in missing))

    def test_omit_from_page_keeps_caption_and_biblio(self) -> None:
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 43,
            "conteudo": [
                {
                    "tipo": "imagem",
                    "legenda": "As atrizes encenam o espetáculo, em Salvador (BA), em 2012.",
                    "fonte": "ALESSANDRA NOHVAIS/GRUPO VILAVOX",
                },
                {
                    "tipo": "paragrafo",
                    "texto": "Comente com os colegas. ALESSANDRA NOHVAIS/GRUPO VILAVOX",
                },
                {
                    "tipo": "fonte",
                    "texto": "BOTELHO, Luiz Felipe. O segredo da arca de Trancoso. São Paulo: Paulinas, 2007.",
                },
                {"tipo": "fonte", "texto": "Shutterstock"},
            ],
        }
        cleaned = omit_image_credits(page)
        imagem = cleaned["conteudo"][0]
        self.assertIsNone(imagem["fonte"])
        self.assertIn("Salvador", imagem["legenda"])
        self.assertNotIn("VILAVOX", cleaned["conteudo"][1]["texto"])
        self.assertIn("colegas", cleaned["conteudo"][1]["texto"])
        fontes = [b for b in cleaned["conteudo"] if b.get("tipo") == "fonte"]
        self.assertEqual(len(fontes), 1)
        self.assertIn("2007", fontes[0]["texto"])
