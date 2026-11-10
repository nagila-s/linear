"""Pedidos de recuperação levam as regras do tipo de página (A1/A3)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.steps.page_completeness import format_page_text_context
from src.pipeline.steps.text_gap_fill import build_gap_fill_prompt
from src.services.openai_client import OpenAIService

RULES = "REGRAS DO CONHECA: ignore as miniaturas de páginas."


class _FakeService:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.settings = SimpleNamespace(openai_model_linearization="modelo")

    def _ask_vision(self, _png, prompt, _model, **_kwargs) -> str:
        self.prompts.append(prompt)
        return "{}"

    def _linearize_max_tokens(self) -> int:
        return 1000

    def _parse_linearization_content(self, *_args, **_kwargs) -> dict:
        return {}


class RecoveryPromptTests(unittest.TestCase):
    def test_continue_carries_rules(self) -> None:
        fake = _FakeService()
        OpenAIService._continue_truncated_json(fake, b"", '{"conteudo": [', rules_prompt=RULES)
        self.assertTrue(fake.prompts[0].startswith(RULES))
        self.assertIn("TRUNCADO", fake.prompts[0])

    def test_complete_carries_rules_and_is_neutral(self) -> None:
        for partial in ({"conteudo": []}, {"conteudo": [{"tipo": "paragrafo", "texto": "x" * 500}]}):
            fake = _FakeService()
            OpenAIService._complete_incomplete_json(
                fake, b"", partial, page_plain_text="texto", pdf_char_count=800, rules_prompt=RULES
            )
            prompt = fake.prompts[0]
            self.assertTrue(prompt.startswith(RULES))
            self.assertNotIn("ambas as colunas", prompt)
            self.assertNotIn("poemas", prompt)

    def test_gap_fill_carries_rules(self) -> None:
        prompt = build_gap_fill_prompt({"conteudo": []}, "texto do pdf", ["trecho"], rules_prompt=RULES)
        self.assertTrue(prompt.startswith(RULES))
        self.assertIn("APENAS os que as regras", prompt)

    def test_gap_fill_without_rules_still_works(self) -> None:
        prompt = build_gap_fill_prompt({"conteudo": []}, "texto do pdf", ["trecho"])
        self.assertTrue(prompt.startswith("Você corrige"))

    def test_native_text_is_subordinate(self) -> None:
        block = format_page_text_context("Texto da página.")
        self.assertNotIn("OBRIGATÓRIA", block)
        self.assertIn("As regras acima prevalecem", block)


if __name__ == "__main__":
    unittest.main()
