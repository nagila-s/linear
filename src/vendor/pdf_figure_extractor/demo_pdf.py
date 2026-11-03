from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pymupdf
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def build_sample_textbook_pdf(path: str | Path | None = None) -> bytes:
    """Monta um PDF curto no estilo livro didático, para testes e o inspector."""
    doc = pymupdf.open()
    _page_cerrado(doc)
    _page_ciclo(doc)
    _page_celulas(doc)
    _page_so_texto(doc)
    _page_exercicios(doc)
    _page_foto_entre_colunas(doc)
    data = doc.tobytes()
    doc.close()
    if path is not None:
        Path(path).write_bytes(data)
    return data


def _page_cerrado(doc: pymupdf.Document) -> None:
    page = doc.new_page(width=595, height=842)
    _header(page, "CIENCIAS - 6o ANO")
    page.insert_textbox(
        pymupdf.Rect(48, 72, 547, 110),
        "Capítulo 2  ·  Biomas brasileiros",
        fontsize=16,
        fontname="helv",
        color=(0.12, 0.22, 0.18),
    )
    page.insert_textbox(
        pymupdf.Rect(48, 108, 547, 200),
        (
            "O Cerrado é um bioma de savana com duas estações bem marcadas. "
            "Árvores de tronco tortuoso, gramíneas e queimadas naturais fazem "
            "parte desse equilíbrio. Observe a paisagem típica na figura."
        ),
        fontsize=11,
        fontname="helv",
        color=(0.15, 0.15, 0.15),
    )

    photo = _cerrado_photo()
    page.insert_image(pymupdf.Rect(90, 210, 505, 455), stream=photo)

    page.insert_textbox(
        pymupdf.Rect(90, 462, 505, 490),
        "Figura 1 - Paisagem do Cerrado brasileiro.",
        fontsize=10,
        fontname="heit",
        color=(0.2, 0.2, 0.2),
    )

    # Caixa pedagógica (não deve virar figura)
    page.draw_rect(pymupdf.Rect(48, 530, 547, 640), color=(0.75, 0.62, 0.15), fill=(1.0, 0.96, 0.78), width=1)
    page.insert_textbox(
        pymupdf.Rect(62, 542, 533, 628),
        (
            "Atenção  ·  Não confunda o Cerrado com o Pantanal. "
            "O primeiro ocupa o Planalto Central; o segundo é uma planície "
            "periodicamente alagada. Anote as diferenças no caderno."
        ),
        fontsize=11,
        fontname="helv",
        color=(0.25, 0.18, 0.05),
    )
    _footer(page, 21)


def _page_ciclo(doc: pymupdf.Document) -> None:
    page = doc.new_page(width=595, height=842)
    _header(page, "CIENCIAS - 6o ANO")
    page.insert_textbox(
        pymupdf.Rect(48, 72, 547, 160),
        (
            "A água circula entre atmosfera, solo e seres vivos. "
            "O esquema abaixo resume evaporação, condensação e precipitação."
        ),
        fontsize=11,
        fontname="helv",
        color=(0.15, 0.15, 0.15),
    )

    # Diagrama vetorial (não é XObject)
    page.draw_circle((297, 250), 42, color=(0.15, 0.35, 0.7), fill=(0.55, 0.75, 0.95), width=1.5)
    page.insert_textbox(pymupdf.Rect(255, 238, 340, 262), "nuvem", fontsize=10, fontname="hebo", color=(0.05, 0.15, 0.35))
    page.draw_circle((180, 390), 48, color=(0.1, 0.4, 0.55), fill=(0.35, 0.7, 0.85), width=1.5)
    page.insert_textbox(pymupdf.Rect(145, 378, 215, 402), "rio", fontsize=10, fontname="hebo", color=(0.05, 0.2, 0.3))
    page.draw_circle((415, 390), 48, color=(0.2, 0.45, 0.15), fill=(0.55, 0.78, 0.4), width=1.5)
    page.insert_textbox(pymupdf.Rect(378, 378, 452, 402), "solo", fontsize=10, fontname="hebo", color=(0.1, 0.25, 0.08))
    page.draw_line((297, 292), (180, 345), color=(0.2, 0.2, 0.45), width=2)
    page.draw_line((297, 292), (415, 345), color=(0.2, 0.2, 0.45), width=2)
    page.draw_line((228, 390), (367, 390), color=(0.2, 0.2, 0.45), width=2)
    page.draw_line((180, 345), (250, 310), color=(0.55, 0.25, 0.1), width=2)

    page.insert_textbox(
        pymupdf.Rect(90, 455, 505, 482),
        "Figura 2 - Ciclo da agua.",
        fontsize=10,
        fontname="heit",
        color=(0.2, 0.2, 0.2),
    )

    # Tabela (não deve ser extraída)
    table = pymupdf.Rect(80, 540, 515, 700)
    page.draw_rect(table, color=(0.4, 0.4, 0.4), width=0.8)
    rows = [540, 580, 620, 660, 700]
    cols = [80, 225, 370, 515]
    for y in rows:
        page.draw_line((80, y), (515, y), color=(0.4, 0.4, 0.4), width=0.6)
    for x in cols:
        page.draw_line((x, 540), (x, 700), color=(0.4, 0.4, 0.4), width=0.6)
    headers = ["Processo", "Onde ocorre", "Resultado"]
    for i, h in enumerate(headers):
        page.insert_textbox(pymupdf.Rect(cols[i] + 6, 548, cols[i + 1] - 4, 576), h, fontsize=10, fontname="hebo")
    data = [
        ("Evaporação", "Rios e solo", "Vapor d'água"),
        ("Condensação", "Atmosfera", "Nuvens"),
        ("Precipitação", "Céu → solo", "Chuva"),
    ]
    for r, row in enumerate(data):
        for c, cell in enumerate(row):
            page.insert_textbox(
                pymupdf.Rect(cols[c] + 6, rows[r + 1] + 8, cols[c + 1] - 4, rows[r + 2] - 4),
                cell,
                fontsize=10,
                fontname="helv",
            )
    _footer(page, 22)


def _page_celulas(doc: pymupdf.Document) -> None:
    page = doc.new_page(width=595, height=842)
    _header(page, "CIENCIAS - 6o ANO")
    page.insert_textbox(
        pymupdf.Rect(48, 72, 547, 150),
        (
            "Compare os dois esquemas. A célula vegetal tem parede e cloroplastos; "
            "a animal, não. As duas compartilham núcleo e membrana."
        ),
        fontsize=11,
        fontname="helv",
        color=(0.15, 0.15, 0.15),
    )

    # Dois painéis que devem se fundir numa figura
    page.draw_oval(pymupdf.Rect(70, 180, 250, 360), color=(0.7, 0.25, 0.25), fill=(0.95, 0.72, 0.72), width=2)
    page.draw_circle((160, 255), 22, color=(0.45, 0.1, 0.1), fill=(0.75, 0.35, 0.4), width=1)
    page.insert_textbox(pymupdf.Rect(90, 368, 230, 392), "(a) animal", fontsize=10, fontname="hebo")

    page.draw_rect(pymupdf.Rect(345, 180, 525, 360), color=(0.2, 0.5, 0.2), fill=(0.7, 0.88, 0.65), width=2)
    page.draw_oval(pymupdf.Rect(365, 200, 505, 340), color=(0.15, 0.4, 0.15), fill=(0.55, 0.78, 0.5), width=1.5)
    page.draw_circle((435, 255), 20, color=(0.15, 0.3, 0.1), fill=(0.4, 0.6, 0.3), width=1)
    page.insert_textbox(pymupdf.Rect(365, 368, 505, 392), "(b) vegetal", fontsize=10, fontname="hebo")

    page.insert_textbox(
        pymupdf.Rect(70, 405, 525, 435),
        "Figura 3 - Celula animal (a) e vegetal (b).",
        fontsize=10,
        fontname="heit",
        color=(0.2, 0.2, 0.2),
    )
    page.insert_textbox(
        pymupdf.Rect(48, 460, 547, 560),
        (
            "Depois de observar a figura, escreva três organelas comuns às duas "
            "células e duas exclusivas da célula vegetal."
        ),
        fontsize=11,
        fontname="helv",
        color=(0.15, 0.15, 0.15),
    )
    _footer(page, 23)


def _page_so_texto(doc: pymupdf.Document) -> None:
    """Página de texto corrido: o detector não deve achar figura nenhuma aqui."""
    page = doc.new_page(width=595, height=842)
    _header(page, "CIENCIAS - 6o ANO")
    page.insert_textbox(
        pymupdf.Rect(48, 72, 547, 110),
        "Leitura  ·  O que é um bioma",
        fontsize=16,
        fontname="helv",
        color=(0.12, 0.22, 0.18),
    )
    paragrafos = [
        (
            "Bioma é o conjunto de vida vegetal e animal de uma região, definido pelo "
            "clima, pelo relevo e pelo solo. Dois lugares distantes podem ter o mesmo "
            "bioma se as condições forem parecidas."
        ),
        (
            "No Brasil são reconhecidos seis biomas continentais. Cada um tem espécies "
            "que só existem ali, e que dependem daquele regime de chuvas para completar "
            "o ciclo de vida."
        ),
        (
            "A perda de um bioma não é só a perda de árvores. Quando a vegetação original "
            "desaparece, o solo perde a proteção contra a chuva, os rios recebem mais "
            "sedimento e a temperatura local sobe."
        ),
        (
            "Por isso o estudo dos biomas aparece junto com o de clima e de solo: são três "
            "descrições do mesmo sistema, vistas de ângulos diferentes."
        ),
    ]
    y = 124
    for texto in paragrafos:
        page.insert_textbox(
            pymupdf.Rect(48, y, 547, y + 120),
            texto,
            fontsize=11,
            fontname="helv",
            color=(0.15, 0.15, 0.15),
        )
        y += 130
    _footer(page, 24)


def _page_exercicios(doc: pymupdf.Document) -> None:
    """Exercícios numerados e uma caixa pedagógica: também sem nenhuma figura."""
    page = doc.new_page(width=595, height=842)
    _header(page, "CIENCIAS - 6o ANO")
    page.insert_textbox(
        pymupdf.Rect(48, 72, 547, 110),
        "Atividades",
        fontsize=16,
        fontname="helv",
        color=(0.12, 0.22, 0.18),
    )
    questoes = [
        "1. Explique com suas palavras a diferença entre clima e bioma.",
        "2. Cite duas consequências da retirada da vegetação original de uma região.",
        "3. Por que dois lugares distantes podem abrigar o mesmo bioma?",
        "4. Escolha um bioma brasileiro e descreva o regime de chuvas dele.",
        "5. Relacione a perda de vegetação com a quantidade de sedimento nos rios.",
    ]
    y = 130
    for questao in questoes:
        page.insert_textbox(
            pymupdf.Rect(48, y, 547, y + 60),
            questao,
            fontsize=11,
            fontname="helv",
            color=(0.15, 0.15, 0.15),
        )
        y += 70

    page.draw_rect(pymupdf.Rect(48, 520, 547, 620), color=(0.75, 0.62, 0.15), fill=(1.0, 0.96, 0.78), width=1)
    page.insert_textbox(
        pymupdf.Rect(62, 532, 533, 608),
        (
            "Para o caderno  ·  Responda às questões 1 e 3 em duplas. Compare as respostas "
            "com o texto da página anterior antes de entregar."
        ),
        fontsize=11,
        fontname="helv",
        color=(0.25, 0.18, 0.05),
    )
    _footer(page, 25)


def _page_foto_entre_colunas(doc: pymupdf.Document) -> None:
    """Foto no meio de duas colunas de texto.

    O caso difícil do layout de livro: a figura tem texto dos dois lados, e o
    recorte não pode invadir nenhuma das colunas.
    """
    page = doc.new_page(width=595, height=842)
    _header(page, "CIENCIAS - 6o ANO")
    page.insert_textbox(
        pymupdf.Rect(48, 72, 547, 110),
        "Paisagem e ocupação",
        fontsize=16,
        fontname="helv",
        color=(0.12, 0.22, 0.18),
    )
    page.insert_textbox(
        pymupdf.Rect(48, 120, 175, 430),
        (
            "PARAGRAFO_ESQUERDO — a vegetação de cerrado resiste ao fogo natural porque "
            "guarda reservas nas raízes, bem abaixo da superfície queimada."
        ),
        fontsize=10,
        fontname="helv",
        color=(0.15, 0.15, 0.15),
    )
    page.insert_textbox(
        pymupdf.Rect(420, 120, 547, 430),
        (
            "PARAGRAFO_DIREITO — já o fogo usado para abrir pasto vem em outra época e "
            "com outra intensidade, e a vegetação não se recompõe."
        ),
        fontsize=10,
        fontname="helv",
        color=(0.15, 0.15, 0.15),
    )

    page.insert_image(pymupdf.Rect(205, 150, 390, 300), stream=_cerrado_photo())
    page.insert_textbox(
        pymupdf.Rect(205, 306, 390, 340),
        "Figura 4 - Vegetacao de cerrado depois da queimada.",
        fontsize=9,
        fontname="heit",
        color=(0.2, 0.2, 0.2),
    )
    _footer(page, 26)


def _header(page: pymupdf.Page, title: str) -> None:
    page.insert_textbox(pymupdf.Rect(48, 28, 400, 50), title, fontsize=9, fontname="hebo", color=(0.35, 0.25, 0.1))
    page.draw_line((48, 54), (547, 54), color=(0.75, 0.6, 0.2), width=1.2)


def _footer(page: pymupdf.Page, number: int) -> None:
    page.draw_line((48, 800), (547, 800), color=(0.75, 0.6, 0.2), width=0.8)
    page.insert_textbox(
        pymupdf.Rect(250, 808, 345, 828),
        str(number),
        fontsize=9,
        fontname="helv",
        color=(0.3, 0.3, 0.3),
        align=pymupdf.TEXT_ALIGN_CENTER,
    )


def _cerrado_photo() -> bytes:
    img = Image.new("RGB", (640, 400), (120, 175, 220))
    draw = ImageDraw.Draw(img)
    for y in range(220, 400):
        t = (y - 220) / 180
        color = (int(160 + 50 * t), int(130 - 20 * t), int(60 - 10 * t))
        draw.line([(0, y), (640, y)], fill=color)
    rng = np.random.default_rng(4)
    for _ in range(18):
        x = int(rng.integers(20, 620))
        h = int(rng.integers(40, 120))
        w = int(rng.integers(8, 22))
        y = 220 - h + int(rng.integers(0, 25))
        draw.ellipse((x, y, x + w, 230), fill=(70, 90, 40))
        draw.rectangle((x + w // 3, 220, x + 2 * w // 3, 250), fill=(90, 60, 30))
    img = img.filter(ImageFilter.SMOOTH_MORE)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()
