"""Testes da etapa de preenchimento de lacunas sem reclassificar blocos."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.steps.page_completeness import editorial_plain_text
from src.pipeline.steps.text_gap_fill import (
    analyze_text_gaps,
    collect_tipo_fingerprint,
    find_missing_pdf_spans,
    preserves_classification,
)


class FindMissingSpansTests(unittest.TestCase):
    def test_detects_omitted_paragraph(self) -> None:
        pdf = (
            "Migrações hoje. As pessoas se deslocam por trabalho. "
            "O fenótipo está relacionado ao genótipo, com a contribuição de influências ambientais. "
            "Observe as fotos a seguir e faça o que se pede."
        )
        json_text = "Migrações hoje. Observe as fotos a seguir e faça o que se pede."
        missing = find_missing_pdf_spans(pdf, json_text)
        joined = " ".join(missing)
        self.assertIn("fenótipo", joined)
        self.assertTrue(any("genótipo" in span for span in missing))

    def test_ignores_page_number_and_credits(self) -> None:
        pdf = "Texto principal da pagina sobre fotossintese nas plantas verdes. 42 Shutterstock"
        json_text = "Texto principal da pagina sobre fotossintese nas plantas verdes."
        missing = find_missing_pdf_spans(pdf, json_text)
        self.assertFalse(any("42" == span.strip() for span in missing))
        self.assertFalse(any("Shutterstock" in span for span in missing))

    def test_similar_spelling_is_not_a_gap(self) -> None:
        pdf = "O conhecimento e essencial para a aprendizagem escolar contemporanea."
        json_text = "O conhecimento é essencial para a aprendizagem escolar contemporânea."
        missing = find_missing_pdf_spans(pdf, json_text)
        self.assertEqual(missing, [])


class AnalyzeGapsTests(unittest.TestCase):
    def test_needs_fill_when_paragraph_missing(self) -> None:
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 10,
            "conteudo": [
                {"tipo": "titulo_3", "texto": "Migrações hoje"},
                {"tipo": "paragrafo", "texto": "As pessoas se deslocam por trabalho."},
            ],
        }
        pdf = (
            "Migrações hoje As pessoas se deslocam por trabalho. "
            "Depois da guerra muitas famílias reconstruíram a vida em outro país "
            "e precisaram aprender a língua local para estudar e trabalhar."
        )
        report = analyze_text_gaps(page, pdf)
        self.assertTrue(report.needs_fill)
        self.assertGreater(report.missing_chars, 40)

    def test_no_fill_when_json_covers_pdf(self) -> None:
        text = "O fenótipo está relacionado ao genótipo, com a contribuição de influências ambientais."
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 11,
            "conteudo": [{"tipo": "paragrafo", "texto": text}],
        }
        report = analyze_text_gaps(page, text)
        self.assertFalse(report.needs_fill)


class PreserveClassificationTests(unittest.TestCase):
    def test_keeps_types_when_text_is_extended(self) -> None:
        original = {
            "tipo_pagina": "conteudo",
            "conteudo": [
                {"tipo": "titulo_3", "texto": "Migrações hoje"},
                {"tipo": "paragrafo", "texto": "As pessoas se deslocam."},
                {"tipo": "atividade", "instrucao": "Responda.", "itens": []},
            ],
        }
        patched = {
            "tipo_pagina": "conteudo",
            "conteudo": [
                {"tipo": "titulo_3", "texto": "Migrações hoje"},
                {
                    "tipo": "paragrafo",
                    "texto": "As pessoas se deslocam por trabalho e estudo.",
                },
                {"tipo": "atividade", "instrucao": "Responda.", "itens": []},
            ],
        }
        self.assertTrue(preserves_classification(original, patched))
        self.assertEqual(
            collect_tipo_fingerprint(original),
            ["titulo_3", "paragrafo", "atividade"],
        )

    def test_allows_inserting_new_block_between(self) -> None:
        original = {
            "tipo_pagina": "conteudo",
            "conteudo": [
                {"tipo": "titulo_3", "texto": "A"},
                {"tipo": "paragrafo", "texto": "B"},
            ],
        }
        patched = {
            "tipo_pagina": "conteudo",
            "conteudo": [
                {"tipo": "titulo_3", "texto": "A"},
                {"tipo": "paragrafo", "texto": "trecho extra do pdf"},
                {"tipo": "paragrafo", "texto": "B"},
            ],
        }
        self.assertTrue(preserves_classification(original, patched))

    def test_rejects_reclassification(self) -> None:
        original = {
            "tipo_pagina": "conteudo",
            "conteudo": [
                {"tipo": "titulo_3", "texto": "Migrações hoje"},
                {"tipo": "paragrafo", "texto": "Texto."},
            ],
        }
        patched = {
            "tipo_pagina": "conteudo",
            "conteudo": [
                {"tipo": "paragrafo", "texto": "Migrações hoje"},
                {"tipo": "paragrafo", "texto": "Texto."},
            ],
        }
        self.assertFalse(preserves_classification(original, patched))

    def test_rejects_tipo_pagina_change(self) -> None:
        original = {"tipo_pagina": "conteudo", "conteudo": [{"tipo": "paragrafo", "texto": "X"}]}
        patched = {"tipo_pagina": "sumario", "conteudo": [{"tipo": "paragrafo", "texto": "X"}]}
        self.assertFalse(preserves_classification(original, patched))


class EditorialPlainTextTests(unittest.TestCase):
    def test_reads_segments_and_instruction(self) -> None:
        page = {
            "conteudo": [
                {
                    "tipo": "paragrafo",
                    "texto": [
                        {"trecho": "Olá ", "estilo": "normal"},
                        {"trecho": "mundo", "estilo": "negrito"},
                    ],
                },
                {"tipo": "atividade", "instrucao": "Faça a atividade."},
            ]
        }
        plain = editorial_plain_text(page)
        self.assertIn("Olá", plain)
        self.assertIn("mundo", plain)
        self.assertIn("Faça a atividade.", plain)


if __name__ == "__main__":
    unittest.main()
