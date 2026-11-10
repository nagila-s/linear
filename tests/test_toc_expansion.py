"""Itens de sumário não são "completados" com o texto nativo."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.steps.page_completeness import expand_cut_texts_from_plain

PLAIN = (
    "SUMÁRIO Conhecendo as culturas dos povos originários...............22 "
    "Respeito e alteridade.......23 Seja cidadão........24 "
    "O texto corrido da página que foi cortado no meio e continua aqui com mais palavras."
)


class TocExpansionTests(unittest.TestCase):
    def test_toc_item_is_not_expanded(self) -> None:
        page = {
            "conteudo": [
                {
                    "tipo": "sumario",
                    "itens": [{"nivel": 3, "texto": "Conhecendo as culturas dos povos originários", "pagina": 22}],
                }
            ]
        }
        out = expand_cut_texts_from_plain(page, PLAIN)
        self.assertEqual(out["conteudo"][0]["itens"][0]["texto"], "Conhecendo as culturas dos povos originários")

    def test_running_text_still_expands(self) -> None:
        page = {
            "conteudo": [
                {"tipo": "sumario", "itens": [{"nivel": 3, "texto": "Respeito e alteridade", "pagina": 23}]},
                {"tipo": "paragrafo", "texto": "O texto corrido da página que foi cortado no meio e continua"},
            ]
        }
        out = expand_cut_texts_from_plain(page, PLAIN)
        self.assertTrue(out["conteudo"][1]["texto"].endswith("com mais palavras."))


if __name__ == "__main__":
    unittest.main()
