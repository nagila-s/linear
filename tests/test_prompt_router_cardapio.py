import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.services.openai_client import OpenAIService
from src.services.prompt_router import CARDAPIO_MODELO, PromptRouter, normalize_modelo

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


class CardapioPromptRouterTests(unittest.TestCase):
    def test_qualquer_tipo_usa_o_arquivo_de_cardapio(self) -> None:
        router = PromptRouter(str(PROMPTS), cardapio=True)
        esperado = (PROMPTS / "cardapio.txt").read_text(encoding="utf-8").strip()
        for page_type in ("capa", "sumario", "ficha", "conteudo", "contracapa"):
            prompt = router.get_prompt(page_type)
            self.assertEqual(prompt, esperado)
            self.assertNotIn("{{SHARED_RULES}}", prompt)

    def test_fluxo_de_livro_nao_usa_o_prompt_de_cardapio(self) -> None:
        livro = PromptRouter(str(PROMPTS))
        cardapio = (PROMPTS / "cardapio.txt").read_text(encoding="utf-8").strip()
        self.assertNotEqual(livro.get_prompt("conteudo"), cardapio)
        self.assertNotEqual(livro.get_prompt("capa"), cardapio)

    def test_normalize_modelo(self) -> None:
        self.assertIsNone(normalize_modelo(None))
        self.assertIsNone(normalize_modelo("  "))
        self.assertEqual(normalize_modelo("cardapio"), CARDAPIO_MODELO)
        self.assertEqual(normalize_modelo("Cardápio"), CARDAPIO_MODELO)
        with self.assertRaises(ValueError):
            normalize_modelo("literario")


class CardapioRoutingTests(unittest.TestCase):
    def test_cardapio_nao_chama_o_classificador(self) -> None:
        settings = MagicMock()
        settings.openai_api_key = "test"
        settings.prompts_directory = str(PROMPTS)
        settings.classification_window_start = 20
        settings.classification_window_end = 15
        settings.prompt_routing_enabled = True
        with patch("src.services.openai_client.get_settings", return_value=settings), patch(
            "src.services.openai_client.OpenAI"
        ):
            service = OpenAIService(cardapio=True)
        service._classify_page_type = MagicMock(side_effect=AssertionError("classificador"))

        prompt, page_type = service._resolve_linearization(b"png", 1, 12)
        esperado = (PROMPTS / "cardapio.txt").read_text(encoding="utf-8").strip()

        self.assertFalse(service.prompt_routing_enabled)
        self.assertEqual(page_type, "cardapio")
        self.assertEqual(prompt, esperado)
        service._classify_page_type.assert_not_called()
        self.assertEqual(service.resolve_page_type(b"png", page_number=1, total_pages=12), "cardapio")
