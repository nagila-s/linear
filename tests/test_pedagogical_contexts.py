"""Contexto enviado à Dorina IA vem do contexto_pedagogico do JSON."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.openai_client import OpenAIService, pedagogical_contexts


class PedagogicalContextsTests(unittest.TestCase):
    def test_uses_only_filled_contexts(self) -> None:
        page = {
            "conteudo": [
                {
                    "tipo": "atividade",
                    "instrucao": "De que cor é a camiseta das crianças?",
                    "referencias_visuais": ["fig1"],
                },
                {
                    "tipo": "imagem",
                    "id": "fig1",
                    "contexto_pedagogico": "De que cor é a camiseta das crianças?",
                },
                {"tipo": "imagem", "id": "FIG2", "contexto_pedagogico": None},
                {
                    "tipo": "boxe_complementar",
                    "conteudo": [{"tipo": "imagem", "id": "fig3", "contexto_pedagogico": "  "}],
                },
            ]
        }
        contexts = pedagogical_contexts(page, ["fig1", "fig2", "fig3"])
        self.assertEqual(
            contexts,
            {"fig1": "De que cor é a camiseta das crianças?", "fig2": "", "fig3": ""},
        )

    def test_empty_page(self) -> None:
        self.assertEqual(pedagogical_contexts({}, ["fig1"]), {"fig1": ""})
        self.assertEqual(pedagogical_contexts(None, []), {})

    def test_no_separate_context_call(self) -> None:
        self.assertFalse(hasattr(OpenAIService, "extract_context"))


if __name__ == "__main__":
    unittest.main()
