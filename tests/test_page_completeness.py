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
        self.assertEqual(page["tipo_pagina"], "conteudo")

    def test_scaffold_keeps_classified_page_type(self) -> None:
        from src.pipeline.steps.page_completeness import scaffold_page_from_plain_text

        page = scaffold_page_from_plain_text("Sumário\nCapítulo 1 .... 16", page_type="sumario")
        self.assertEqual(page["tipo_pagina"], "sumario")

    def test_pdf_char_count_ignores_dot_leaders(self) -> None:
        from src.pipeline.steps.page_completeness import pdf_text_char_count

        self.assertEqual(pdf_text_char_count("Fim. Outra frase... e mais."), 27)
        self.assertEqual(pdf_text_char_count("Capítulo 1 ........ 16"), len("Capítulo 1  16"))
        self.assertEqual(pdf_text_char_count("Alteridade . . . . . 20"), len("Alteridade  20"))

    def test_toc_with_dot_leaders_is_complete(self) -> None:
        from src.pipeline.steps.page_completeness import pdf_text_char_count

        titles = [f"Seção de estudo número {i}" for i in range(60)]
        plain = "SUMÁRIO\n" + "\n".join(f"{t}{'.' * 60}{10 + i}" for i, t in enumerate(titles))
        page = {
            "tipo_pagina": "sumario",
            "conteudo": [
                {"tipo": "sumario", "itens": [{"texto": t, "pagina": 10 + i} for i, t in enumerate(titles)]}
            ],
        }
        # Contando os pontos, a transcrição correta parece incompleta.
        self.assertTrue(is_linearization_incomplete(page, pdf_char_count=len(plain)))
        self.assertFalse(
            is_linearization_incomplete(page, pdf_char_count=pdf_text_char_count(plain))
        )

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

    def test_expand_cut_does_not_stop_inside_unclosed_quote(self) -> None:
        from src.pipeline.steps.page_completeness import expand_cut_texts_from_plain

        plain = (
            '\u201cPrimeira frase do excerto. Segunda frase continua o poema '
            "sem fechar ainda. Terceira frase fecha a citacao longa.\u201d "
            "Pergunta da atividade depois."
        )
        page = {
            "conteudo": [
                {
                    "tipo": "titulo_4",
                    "texto": "\u201cPrimeira frase do excerto. Segunda frase continua",
                }
            ]
        }
        expanded = expand_cut_texts_from_plain(page, plain)
        assert expanded is not None
        text = expanded["conteudo"][0]["texto"]
        self.assertIn("Terceira frase", text)
        self.assertIn("\u201d", text)

    def test_expand_cut_skips_name_followed_by_next_field(self) -> None:
        """Ficha t\u00e9cnica: nome terminado em min\u00fascula n\u00e3o pode engolir os cargos seguintes."""
        from src.pipeline.steps.page_completeness import expand_cut_texts_from_plain

        plain = (
            "Dire\u00e7\u00e3o-Geral Daniel Gon\u00e7alves Manaia Moreira Dire\u00e7\u00e3o de Conte\u00fado "
            "Fabr\u00edcio Cortezi de Abreu Moura N\u00daCLEO DE CONTE\u00daDO EDUCACIONAL Ger\u00eancia "
            "Marcele Quaglio Coordena\u00e7\u00e3o Mariana Bordignon Edi\u00e7\u00e3o de Conte\u00fado "
            "Sue Halmenschlager (Superv.); Gabriel Miranda"
        )
        page = {
            "conteudo": [
                {
                    "tipo": "ficha_catalografica",
                    "conteudo": [
                        {"campo": "Dire\u00e7\u00e3o-Geral", "valor": "Daniel Gon\u00e7alves Manaia Moreira"},
                        {"campo": "Dire\u00e7\u00e3o de Conte\u00fado", "valor": "Fabr\u00edcio Cortezi de Abreu Moura"},
                        {"texto": "N\u00facleo de Conte\u00fado Educacional"},
                        {"campo": "Ger\u00eancia", "valor": "Marcele Quaglio"},
                        {"campo": "Coordena\u00e7\u00e3o", "valor": "Mariana Bordignon"},
                    ],
                }
            ]
        }
        expanded = expand_cut_texts_from_plain(page, plain)
        assert expanded is not None
        itens = expanded["conteudo"][0]["conteudo"]
        self.assertEqual(itens[0]["valor"], "Daniel Gon\u00e7alves Manaia Moreira")
        self.assertEqual(itens[1]["valor"], "Fabr\u00edcio Cortezi de Abreu Moura")

    def test_expand_cut_skips_glossary_term_followed_by_definition(self) -> None:
        from src.pipeline.steps.page_completeness import expand_cut_texts_from_plain

        plain = (
            "Rep\u00fablica Democr\u00e1tica do Congo: pa\u00eds localizado na \u00c1frica. [...] Assim, "
            "desafiando a autoridade de Mangala, Pemba escapou de seu ventre. [...] "
            "na fuga, Pemba deixou vazar um pouco da placenta de Mangala."
        )
        page = {
            "conteudo": [
                {
                    "tipo": "glossario",
                    "termo": "Rep\u00fablica Democr\u00e1tica do Congo",
                    "definicao": "pa\u00eds localizado na \u00c1frica.",
                },
                {
                    "tipo": "paragrafo",
                    "texto": "Assim, desafiando a autoridade de Mangala, Pemba escapou de seu ventre.",
                },
            ]
        }
        expanded = expand_cut_texts_from_plain(page, plain)
        assert expanded is not None
        self.assertEqual(expanded["conteudo"][0]["termo"], "Rep\u00fablica Democr\u00e1tica do Congo")

    def test_expand_cut_poem_with_refrain_repeated_later(self) -> None:
        """Continua\u00e7\u00e3o repetida longe (fora da janela seguinte) ainda permite completar."""
        from src.pipeline.steps.page_completeness import expand_cut_texts_from_plain

        plain = (
            "Nao serei o poeta de um mundo caduco. "
            "Tambem nao cantarei o mundo futuro. "
            "Estou preso a vida e olho meus companheiros. "
            "Estao taciturnos mas nutrem grandes esperancas."
        )
        filler = "Texto de atividade sem relacao com o poema. " * 40
        page = {
            "conteudo": [
                {
                    "tipo": "titulo_4",
                    "texto": (
                        "Nao serei o poeta de um mundo caduco. "
                        "Tambem nao cantarei o mundo futuro. Estou preso"
                    ),
                },
                {"tipo": "paragrafo", "texto": filler},
                {"tipo": "paragrafo", "texto": "Copie o verso: a vida e olho meus companheiros."},
            ]
        }
        expanded = expand_cut_texts_from_plain(page, plain)
        assert expanded is not None
        self.assertIn("companheiros", expanded["conteudo"][0]["texto"])


if __name__ == "__main__":
    unittest.main()
