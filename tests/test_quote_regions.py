"""Testes de extração e reinserção de citações multilinha."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.steps.pdf_text_styles import PageTextStyles, TextRun
from src.pipeline.steps.quote_regions import (
    extract_quote_regions,
    restore_missing_quote_regions,
    restore_quotes_from_page_styles,
)
from src.pipeline.steps.style_merge import merge_styles_into_page


POEM = (
    "\u201cNao serei o poeta de um mundo caduco.\n"
    "Tambem nao cantarei o mundo futuro.\n"
    "Estou preso a vida e olho meus companheiros.\n"
    "Estao taciturnos mas nutrem grandes esperancas.\u201d"
)


class QuoteRegionTests(unittest.TestCase):
    def test_extracts_multiline_curly_quote(self) -> None:
        text = "Antes do excerto. " + POEM + " Depois da fonte."
        regions = extract_quote_regions(text)
        self.assertEqual(len(regions), 1)
        self.assertIn("companheiros", regions[0])
        self.assertTrue(regions[0].startswith("\u201c"))
        self.assertTrue(regions[0].endswith("\u201d"))

    def test_restores_omitted_quote_as_titulo_4(self) -> None:
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [
                {"tipo": "paragrafo", "texto": "Antes do excerto."},
                {"tipo": "paragrafo", "texto": "Responda a questao."},
            ],
        }
        pdf = "Antes do excerto. " + POEM + " Responda a questao."
        restored = restore_missing_quote_regions(
            page,
            extract_quote_regions(pdf),
            pdf_text=pdf,
        )
        assert restored is not None
        tipos = [b["tipo"] for b in restored["conteudo"]]
        self.assertIn("titulo_4", tipos)
        joined = " ".join(
            b["texto"] if isinstance(b.get("texto"), str) else "" for b in restored["conteudo"]
        )
        self.assertIn("companheiros", joined)
        self.assertIn("Responda a questao.", joined)

    def test_does_not_duplicate_present_quote(self) -> None:
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [{"tipo": "titulo_4", "texto": POEM}],
        }
        restored = restore_missing_quote_regions(
            page,
            extract_quote_regions(POEM),
            pdf_text=POEM,
        )
        assert restored is not None
        self.assertEqual(len(restored["conteudo"]), 1)

    def test_restore_then_italic_overlay(self) -> None:
        styles = PageTextStyles(
            page_number=1,
            runs=[
                TextRun("Antes. ", "normal"),
                TextRun(POEM.replace("\n", " "), "italico"),
                TextRun(" Depois.", "normal"),
            ],
            char_count=0,
        )
        styles.char_count = sum(len(r.text) for r in styles.runs)
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [{"tipo": "paragrafo", "texto": "Antes. Depois."}],
        }
        restored = restore_quotes_from_page_styles(
            page,
            styles,
            pdf_text="Antes. " + POEM.replace("\n", " ") + " Depois.",
        )
        merged = merge_styles_into_page(restored or page, styles, page_number=1)
        quoted = next(b for b in merged["conteudo"] if "companheiros" in str(b.get("texto")))
        texto = quoted["texto"]
        if isinstance(texto, list):
            self.assertIn("italico", [s["estilo"] for s in texto])
        else:
            self.fail(f"citação sem overlay de itálico: {texto!r}")


if __name__ == "__main__":
    unittest.main()
