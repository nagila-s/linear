import unittest
from pathlib import Path

from src.services.prompt_router import PromptRouter
from src.worker.pipeline.stages.describe import _ensure_cover_image, _is_literary_cover

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


class LiteraryPromptRouterTests(unittest.TestCase):
    def test_capa_e_conteudo_usam_o_prompt_literario(self) -> None:
        router = PromptRouter(str(PROMPTS), literario=True)
        capa = router.get_prompt("capa")
        conteudo = router.get_prompt("conteudo")
        self.assertIs(capa, conteudo)
        self.assertIn("[CAPA]", capa)
        self.assertIn("FIDELIDADE ABSOLUTA", capa)
        tipos = capa.split("Tipos de bloco permitidos:", 1)[-1].split("[IMAGENS]", 1)[0]
        self.assertNotIn("atividade", tipos)
        self.assertIn("nota_rodape", tipos)
        self.assertIn("ficha_catalografica", tipos)
        self.assertIn("[FICHA CATALOGRÁFICA]", capa)

    def test_tipos_didaticos_viram_conteudo(self) -> None:
        router = PromptRouter(str(PROMPTS), literario=True)
        self.assertEqual(router.normalize_page_type("ficha"), "ficha")
        self.assertEqual(router.normalize_page_type("hino"), "conteudo")
        self.assertEqual(router.normalize_page_type("capa"), "capa")
        self.assertEqual(router.normalize_page_type("sumario"), "sumario")
        self.assertIn("\nficha\n", router.classifier_prompt)
        self.assertIn("contracapa", router.classifier_prompt)
        self.assertEqual(router.normalize_page_type("Sumário."), "sumario")
        self.assertEqual(router.normalize_page_type("A página é de ficha catalográfica."), "ficha")

    def test_classificacao_trava_o_caso_do_prompt(self) -> None:
        router = PromptRouter(str(PROMPTS), literario=True)
        router.pin_literary_case = True
        capa = router.get_prompt("capa")
        ficha = router.get_prompt("ficha")
        self.assertIn('CLASSIFICAÇÃO DESTA PÁGINA: capa.', capa)
        self.assertIn('CLASSIFICAÇÃO DESTA PÁGINA: ficha.', ficha)
        self.assertNotEqual(capa, ficha)

    def test_modo_didatico_nao_usa_prompt_literario(self) -> None:
        router = PromptRouter(str(PROMPTS), literario=False)
        prompt = router.get_prompt("conteudo")
        self.assertNotIn("[CAPA]", prompt)
        self.assertEqual(router.normalize_page_type("ficha"), "ficha")


class LiteraryCoverTests(unittest.TestCase):
    def test_capa_literaria_exige_bloco_de_imagem(self) -> None:
        page = {"tipo_pagina": "capa", "conteudo": [{"tipo": "titulo_1", "texto": "O livro"}]}
        self.assertTrue(_is_literary_cover(page, literario=True, miolo_only=False))
        self.assertFalse(_is_literary_cover(page, literario=True, miolo_only=True))
        self.assertEqual(_ensure_cover_image(page), "fig1")
        self.assertEqual(page["conteudo"][-1]["id"], "fig1")

    def test_capa_com_figura_reusa_o_id(self) -> None:
        page = {
            "tipo_pagina": "capa",
            "conteudo": [{"tipo": "imagem", "id": "fig2", "descricao": "paisagem"}],
        }
        self.assertEqual(_ensure_cover_image(page), "fig2")
        self.assertEqual(len(page["conteudo"]), 1)

    def test_capa_escolhe_o_menor_id_numerico(self) -> None:
        page = {
            "tipo_pagina": "capa",
            "conteudo": [
                {"tipo": "imagem", "id": "fig10", "descricao": "a"},
                {"tipo": "imagem", "id": "fig2", "descricao": "b"},
            ],
        }
        self.assertEqual(_ensure_cover_image(page), "fig2")


if __name__ == "__main__":
    unittest.main()
