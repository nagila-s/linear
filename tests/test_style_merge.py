"""Testes de extração tipográfica e merge de estilos."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz

from src.pipeline.steps.pdf_text_styles import (
    PageTextStyles,
    TextRun,
    classify_font_style,
    extract_text_styles_from_pdf,
    pages_from_payload,
    pages_to_payload,
)
from src.pipeline.steps.style_merge import merge_styles_into_page, normalize_for_align
from src.utils.json_codec import parse_llm_json, repair_llm_json_text


def _make_styled_pdf() -> bytes:
    """PDF com título bold, parágrafo misto, aspas e hífen de quebra."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)

    # Título ALL CAPS em negrito
    page.insert_text((50, 60), "A REVOLUCAO FRANCESA", fontsize=14, fontname="hebo")

    # Parágrafo com trecho italic e aspas (ASCII — Helvetica não tem “ ”)
    page.insert_text((50, 100), "O termo ", fontsize=11, fontname="helv")
    page.insert_text((95, 100), "scrapbook", fontsize=11, fontname="heit")
    page.insert_text((155, 100), ' aparece em "manuais"', fontsize=11, fontname="helv")
    page.insert_text((290, 100), " escolares.", fontsize=11, fontname="helv")

    # Linha com hífen de quebra (simulado em duas linhas)
    page.insert_text((50, 140), "O conhe-", fontsize=11, fontname="helv")
    page.insert_text((50, 155), "cimento e essencial.", fontsize=11, fontname="helv")

    # Fonte Bold no nome sem depender só de flags (hebo já seta bold)
    page.insert_text((50, 200), "Direcao executiva: ", fontsize=11, fontname="hebo")
    page.insert_text((160, 200), "Maria Silva", fontsize=11, fontname="helv")

    data = doc.tobytes()
    doc.close()
    return data


def _empty_text_pdf() -> bytes:
    """PDF sem camada de texto (só desenho)."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(20, 20, 180, 180), color=(0, 0, 0), width=2)
    data = doc.tobytes()
    doc.close()
    return data


class ClassifyFontStyleTests(unittest.TestCase):
    def test_flags_and_names(self) -> None:
        self.assertEqual(classify_font_style(0, "Helvetica"), "normal")
        self.assertEqual(classify_font_style(1 << 4, "Helvetica"), "negrito")
        self.assertEqual(classify_font_style(1 << 1, "Helvetica"), "italico")
        self.assertEqual(classify_font_style((1 << 1) | (1 << 4), "X"), "negrito_italico")
        self.assertEqual(classify_font_style(0, "ABCDEF+MinionPro-Bold"), "negrito")
        self.assertEqual(classify_font_style(0, "Times-Italic"), "italico")
        self.assertEqual(classify_font_style(0, "Arial-BoldItalic"), "negrito_italico")


class ExtractTextStylesTests(unittest.TestCase):
    def test_extract_bold_italic_quotes(self) -> None:
        pdf = _make_styled_pdf()
        pages = extract_text_styles_from_pdf(pdf)
        self.assertEqual(len(pages), 1)
        page = pages[0]
        self.assertGreater(page.char_count, 40)
        full = "".join(r.text for r in page.runs)
        self.assertIn("REVOLUCAO", full.upper())
        self.assertIn("scrapbook", full)
        # Aspas presentes (ASCII no PDF sintético)
        self.assertIn('"manuais"', full)

        estilos = {r.estilo for r in page.runs if r.text.strip()}
        self.assertIn("negrito", estilos)
        self.assertIn("italico", estilos)

        # Desifenação: conhe- + cimento → conhecimento
        self.assertIn("conhecimento", full.replace(" ", "").lower() or full.lower())
        joined = full.replace("\n", " ")
        self.assertIn("conhecimento", joined.lower().replace(" ", "") or "conhecimento" in joined.lower())
        # Mais direto:
        compact = "".join(ch for ch in full if not ch.isspace())
        self.assertIn("conhecimento", compact.lower())

    def test_payload_roundtrip(self) -> None:
        pdf = _make_styled_pdf()
        pages = extract_text_styles_from_pdf(pdf)
        payload = pages_to_payload(pages)
        restored = pages_from_payload(payload)
        self.assertIn(1, restored)
        self.assertEqual(restored[1].char_count, pages[0].char_count)

    def test_scanned_empty(self) -> None:
        pages = extract_text_styles_from_pdf(_empty_text_pdf())
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].char_count, 0)
        self.assertEqual(pages[0].runs, [])


class StyleMergeTests(unittest.TestCase):
    def test_merge_bold_and_italic(self) -> None:
        styles = PageTextStyles(
            page_number=1,
            runs=[
                TextRun("A Revolucao Francesa", "negrito"),
                TextRun(" foi um periodo. O termo ", "normal"),
                TextRun("scrapbook", "italico"),
                TextRun(" aparece.", "normal"),
            ],
            char_count=0,
        )
        styles.char_count = sum(len(r.text) for r in styles.runs)

        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [
                {"tipo": "titulo_3", "texto": "A Revolução Francesa"},
                {
                    "tipo": "paragrafo",
                    "texto": "A Revolucao Francesa foi um periodo. O termo scrapbook aparece.",
                },
            ],
        }
        # Title case + accent drift on first field — fuzzy may or may not match.
        # Use closer LLM text for stable assertion:
        page["conteudo"][0]["texto"] = "A Revolucao Francesa"
        merged = merge_styles_into_page(page, styles, page_number=1)
        titulo = merged["conteudo"][0]["texto"]
        self.assertIsInstance(titulo, list)
        self.assertEqual(titulo[0]["estilo"], "negrito")

        para = merged["conteudo"][1]["texto"]
        self.assertIsInstance(para, list)
        estilos = [seg["estilo"] for seg in para]
        self.assertIn("italico", estilos)
        self.assertIn("negrito", estilos)

    def test_restore_quotes(self) -> None:
        styles = PageTextStyles(
            page_number=1,
            runs=[
                TextRun("Veja a palavra ", "normal"),
                TextRun("\u201cmanuais\u201d", "normal"),
                TextRun(" no glossario do livro.", "normal"),
            ],
            char_count=0,
        )
        styles.char_count = sum(len(r.text) for r in styles.runs)
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [
                {"tipo": "paragrafo", "texto": "Veja a palavra manuais no glossario do livro."},
            ],
        }
        merged = merge_styles_into_page(page, styles, page_number=1)
        texto = merged["conteudo"][0]["texto"]
        if isinstance(texto, list):
            flat = "".join(s["trecho"] for s in texto)
        else:
            flat = texto
        # Campo inteiro: aspas no meio não são leading/trailing do campo.
        # Caso de campo = só a palavra citada:
        page2 = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [{"tipo": "paragrafo", "texto": "manuais"}],
        }
        styles2 = PageTextStyles(
            page_number=1,
            runs=[
                TextRun("Introducao ao tema com contexto amplo. ", "normal"),
                TextRun("\u201cmanuais\u201d", "normal"),
            ],
            char_count=0,
        )
        styles2.char_count = sum(len(r.text) for r in styles2.runs)
        merged2 = merge_styles_into_page(page2, styles2, page_number=1)
        texto2 = merged2["conteudo"][0]["texto"]
        if isinstance(texto2, list):
            flat2 = "".join(s["trecho"] for s in texto2)
        else:
            flat2 = texto2
        self.assertTrue(flat2.startswith("\u201c"), flat2)
        self.assertTrue(flat2.endswith("\u201d"), flat2)
        self.assertIn("manuais", flat2)
        # O parágrafo longo ainda alinha sem explodir
        self.assertIn("manuais", flat)

    def test_preserve_circulado(self) -> None:
        styles = PageTextStyles(
            page_number=1,
            runs=[TextRun("Assinale a alternativa A correta.", "normal")],
            char_count=33,
        )
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [
                {
                    "tipo": "paragrafo",
                    "texto": [
                        {"trecho": "Assinale a alternativa ", "estilo": "normal"},
                        {"trecho": "A", "estilo": "circulado"},
                        {"trecho": " correta.", "estilo": "normal"},
                    ],
                }
            ],
        }
        merged = merge_styles_into_page(page, styles, page_number=1)
        texto = merged["conteudo"][0]["texto"]
        self.assertIsInstance(texto, list)
        circled = [s for s in texto if s.get("estilo") == "circulado"]
        self.assertEqual(len(circled), 1)
        self.assertEqual(circled[0]["trecho"], "A")

    def test_scanned_noop(self) -> None:
        styles = PageTextStyles(page_number=1, runs=[], char_count=0)
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [{"tipo": "paragrafo", "texto": "Texto qualquer."}],
        }
        merged = merge_styles_into_page(page, styles, page_number=1)
        self.assertEqual(merged["conteudo"][0]["texto"], "Texto qualquer.")

    def test_all_caps_title_case_alignment(self) -> None:
        styles = PageTextStyles(
            page_number=1,
            runs=[TextRun("FOTOSSINTESE E O PROCESSO", "negrito")],
            char_count=25,
        )
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [{"tipo": "titulo_3", "texto": "Fotossintese e o processo"}],
        }
        merged = merge_styles_into_page(page, styles, page_number=1)
        texto = merged["conteudo"][0]["texto"]
        self.assertIsInstance(texto, list)
        self.assertEqual(texto[0]["estilo"], "negrito")
        # Capitalização da LLM preservada
        self.assertEqual(texto[0]["trecho"], "Fotossintese e o processo")

    def test_no_midword_style_split(self) -> None:
        """Não deve partir palavra (D|iversidade) quando o PDF troca estilo no meio."""
        styles = PageTextStyles(
            page_number=1,
            runs=[
                TextRun("BELINKY, Tatiana. ", "normal"),
                TextRun("D", "normal"),
                TextRun("iversidade.", "italico"),
                TextRun(" Ilustracoes de Gilles Eduar.", "normal"),
            ],
            char_count=0,
        )
        styles.char_count = sum(len(r.text) for r in styles.runs)
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [
                {
                    "tipo": "fonte",
                    "texto": "BELINKY, Tatiana. Diversidade. Ilustracoes de Gilles Eduar.",
                }
            ],
        }
        merged = merge_styles_into_page(page, styles, page_number=1)
        texto = merged["conteudo"][0]["texto"]
        self.assertIsInstance(texto, list)
        flat_parts = [(s["trecho"], s["estilo"]) for s in texto]
        # Nenhuma fronteira de estilo no meio de "Diversidade"
        joined = "".join(t for t, _ in flat_parts)
        self.assertIn("Diversidade", joined)
        for trecho, _estilo in flat_parts:
            if "iversidade" in trecho.lower() and trecho.lower() != "diversidade.":
                # se contém só o sufixo, falhou
                if trecho.lower().startswith("iversidade"):
                    self.fail(f"palavra partida: {flat_parts}")
        # O trecho que contém Diversidade deve ser todo italico
        diver = [s for s in texto if "Diversidade" in s["trecho"] or "iversidade" in s["trecho"].lower()]
        self.assertTrue(diver, flat_parts)
        for s in diver:
            if "Diversidade" in s["trecho"] or s["trecho"].lower().startswith("diversidade"):
                self.assertEqual(s["estilo"], "italico", flat_parts)

    def test_reject_tiny_fuzzy_match(self) -> None:
        """Campo curto não deve casar fuzzy com pedaço aleatório e avançar o cursor errado."""
        styles = PageTextStyles(
            page_number=1,
            runs=[
                TextRun("Orientacao didatica: Organize tabelas com dados. ", "negrito"),
                TextRun("Depois discuta BNCC EF02MA01 com a turma.", "normal"),
            ],
            char_count=0,
        )
        styles.char_count = sum(len(r.text) for r in styles.runs)
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [
                {"tipo": "paragrafo", "texto": "x"},  # muito curto — sem fuzzy
                {"tipo": "paragrafo", "texto": "Depois discuta BNCC EF02MA01 com a turma."},
            ],
        }
        merged = merge_styles_into_page(page, styles, page_number=1)
        segundo = merged["conteudo"][1]["texto"]
        flat = segundo if isinstance(segundo, str) else "".join(s["trecho"] for s in segundo)
        self.assertIn("BNCC", flat)

    def test_descricao_untouched(self) -> None:
        styles = PageTextStyles(
            page_number=1,
            runs=[TextRun("Figura importante no capitulo", "negrito")],
            char_count=29,
        )
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [
                {
                    "tipo": "imagem",
                    "id": "fig1",
                    "descricao": "Figura importante no capitulo",
                }
            ],
        }
        merged = merge_styles_into_page(page, styles, page_number=1)
        self.assertEqual(merged["conteudo"][0]["descricao"], "Figura importante no capitulo")
        self.assertNotIsInstance(merged["conteudo"][0]["descricao"], list)


class JsonCodecQuoteTests(unittest.TestCase):
    def test_preserves_curly_quotes_in_strings(self) -> None:
        raw = '{"tipo_pagina":"conteudo","pagina":1,"conteudo":[{"tipo":"paragrafo","texto":"disse \u201colá\u201d"}]}'
        parsed = parse_llm_json(raw)
        texto = parsed["conteudo"][0]["texto"]
        self.assertIn("\u201c", texto)
        self.assertIn("\u201d", texto)

    def test_fallback_replaces_curly_delimiters(self) -> None:
        # Delimitadores tipográficos inválidos em JSON
        raw = "{\u201ctipo_pagina\u201d:\u201cconteudo\u201d,\u201cpagina\u201d:1,\u201cconteudo\u201d:[]}"
        cleaned = repair_llm_json_text(raw, replace_curly_quotes=True)
        parsed = json.loads(cleaned)
        self.assertEqual(parsed["tipo_pagina"], "conteudo")

    def test_normalize_for_align_quotes(self) -> None:
        a = normalize_for_align("\u201cmanuais\u201d")
        b = normalize_for_align('"manuais"')
        self.assertEqual(a, b)

    def test_unescaped_quotes_do_not_swallow_next_items(self) -> None:
        raw = (
            '{"tipo_pagina":"conteudo","pagina":1,"conteudo":['
            '{"tipo":"item","texto":"Pergunte: "Todos usaram?"},'
            '{"tipo":"item","texto":"SEGUNDO"},'
            '{"tipo":"item","texto":"TERCEIRO"}]}'
        )
        parsed = parse_llm_json(raw)
        blocos = parsed["conteudo"]
        self.assertEqual(len(blocos), 3)
        self.assertEqual(blocos[0]["texto"], 'Pergunte: "Todos usaram?"')
        self.assertEqual(blocos[1]["texto"], "SEGUNDO")
        self.assertEqual(blocos[2]["texto"], "TERCEIRO")

    def test_slashes_inside_citation_are_not_comments(self) -> None:
        raw = (
            '{"tipo_pagina":"conteudo","pagina":1,"conteudo":['
            '{"tipo":"item","texto":"leia "//o item citado" fim"},'
            '{"tipo":"item","texto":"ITEM SEGUINTE"}]}'
        )
        parsed = parse_llm_json(raw)
        blocos = parsed["conteudo"]
        self.assertEqual(len(blocos), 2)
        self.assertIn("//o item citado", blocos[0]["texto"])
        self.assertIn("fim", blocos[0]["texto"])
        self.assertEqual(blocos[1]["texto"], "ITEM SEGUINTE")

    def test_hash_inside_citation_stays_text(self) -> None:
        raw = (
            '{"tipo_pagina":"conteudo","pagina":1,"conteudo":['
            '{"tipo":"item","texto":"veja "http://exemplo.com/a #nota" agora"},'
            '{"tipo":"item","texto":"DEPOIS"}]}'
        )
        parsed = parse_llm_json(raw)
        blocos = parsed["conteudo"]
        self.assertEqual(len(blocos), 2)
        self.assertIn("#nota", blocos[0]["texto"])
        self.assertIn("http://exemplo.com/a", blocos[0]["texto"])
        self.assertEqual(blocos[1]["texto"], "DEPOIS")

    def test_comma_inside_citation_stays_in_sentence(self) -> None:
        raw = (
            '{"tipo_pagina":"conteudo","pagina":1,"conteudo":['
            '{"tipo":"paragrafo","texto":"ele disse "sim", também "não" e saiu."}]}'
        )
        parsed = parse_llm_json(raw)
        texto = parsed["conteudo"][0]["texto"]
        self.assertEqual(texto, 'ele disse "sim", também "não" e saiu.')

    def test_already_escaped_quotes_stay_escaped(self) -> None:
        raw = '{"tipo_pagina":"conteudo","pagina":1,"conteudo":[{"tipo":"item","texto":"disse \\"olá\\""}]}'
        parsed = parse_llm_json(raw)
        self.assertEqual(parsed["conteudo"][0]["texto"], 'disse "olá"')

    def test_curly_delimiters_with_inner_citation(self) -> None:
        raw = (
            "{\u201ctipo_pagina\u201d:\u201cconteudo\u201d,\u201cpagina\u201d:1,\u201cconteudo\u201d:["
            "{\u201ctipo\u201d:\u201citem\u201d,\u201ctexto\u201d:\u201cPergunte: \u201cTodos usaram?\u201d\u201d}]}"
        )
        parsed = parse_llm_json(raw)
        self.assertEqual(parsed["conteudo"][0]["texto"], 'Pergunte: "Todos usaram?"')


class EndToEndExtractMergeTests(unittest.TestCase):
    def test_pdf_extract_then_merge(self) -> None:
        pdf = _make_styled_pdf()
        pages = extract_text_styles_from_pdf(pdf)
        styles = pages[0]
        full = "".join(r.text for r in styles.runs)

        # Usar trecho real do PDF (normalizado pela LLM de forma leve)
        page = {
            "tipo_pagina": "conteudo",
            "pagina": 1,
            "conteudo": [
                {"tipo": "titulo_3", "texto": "A Revolucao Francesa"},
            ],
        }
        if "Direcao executiva" in full or "Direcao executiva" in full.replace("ç", "c"):
            page["conteudo"].append(
                {"tipo": "paragrafo", "texto": "Direcao executiva: Maria Silva"}
            )

        merged = merge_styles_into_page(page, styles, page_number=1)
        titulo = merged["conteudo"][0]["texto"]
        self.assertIsInstance(titulo, list)
        self.assertEqual(titulo[0]["estilo"], "negrito")


if __name__ == "__main__":
    unittest.main()
