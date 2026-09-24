from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict, Optional

PAGE_TYPES = frozenset(
    {
        "capa",
        "autores",
        "ficha",
        "apresentacao",
        "conheca",
        "sumario",
        "hino",
        "referencias",
        "contracapa",
        "conteudo",
    }
)

CONTENT_PAGE_TYPE = "conteudo"

LITERARY_PAGE_TYPES = frozenset({"capa", "sumario", "ficha", "conteudo", "contracapa"})

LITERARY_CLASSIFIER_PROMPT = """Classifique esta página de livro literário.
Responda SOMENTE com uma destas palavras, sem JSON e sem explicação:
capa
sumario
ficha
conteudo
contracapa

capa: primeira página com título, autor, editora ou ilustração de capa.
sumario: índice ou sumário com títulos e números de página.
ficha: ficha catalográfica (CIP), ISBN, dados de edição, créditos de produção e direitos autorais.
contracapa: quarta capa, sinopse de verso ou código de barras no verso.
conteudo: qualquer outra página, inclusive texto, capítulo, nota, figura, apresentação, hino ou autores.
"""

_LITERARY_CASE_LOCK = {
    "capa": 'CLASSIFICAÇÃO DESTA PÁGINA: capa. Siga somente [CAPA]. "tipo_pagina" deve ser "capa".',
    "sumario": 'CLASSIFICAÇÃO DESTA PÁGINA: sumario. Siga somente [SUMÁRIO]. "tipo_pagina" deve ser "sumario".',
    "ficha": 'CLASSIFICAÇÃO DESTA PÁGINA: ficha. Siga somente [FICHA CATALOGRÁFICA]. "tipo_pagina" deve ser "ficha".',
    "contracapa": (
        'CLASSIFICAÇÃO DESTA PÁGINA: contracapa. Siga somente [MIOLO E CONTRACAPA]. '
        '"tipo_pagina" deve ser "contracapa".'
    ),
    "conteudo": (
        'CLASSIFICAÇÃO DESTA PÁGINA: conteudo. Siga somente [MIOLO E CONTRACAPA]. '
        '"tipo_pagina" deve ser "conteudo".'
    ),
}


def _fold_label(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").lower()

# Um arquivo por tipo, todos em PROMPTS_DIRECTORY.
PROMPT_FILES: Dict[str, str] = {
    "capa": "capa.txt",
    "autores": "autores.txt",
    "ficha": "ficha.txt",
    "apresentacao": "apresentacao.txt",
    "conheca": "conheca.txt",
    "sumario": "sumario.txt",
    "hino": "hino.txt",
    "referencias": "referencias.txt",
    "contracapa": "contracapa.txt",
    "conteudo": "base.txt",
}

ALLOWED_PROMPT_FILENAMES = frozenset(
    {
        *PROMPT_FILES.values(),
        "_shared_rules.txt",
        "_shared_rules_literario.txt",
        "literario.txt",
        "classificador.txt",
    }
)


def sanitize_prompt_overrides(raw: object) -> Dict[str, str]:
    """Mantém só arquivos conhecidos; ignora chaves inválidas."""
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if name not in ALLOWED_PROMPT_FILENAMES:
            continue
        if not isinstance(value, str):
            continue
        cleaned[name] = value
    return cleaned


class PromptRouter:
    def __init__(
        self,
        prompts_dir: str,
        *,
        window_start: int = 20,
        window_end: int = 15,
        overrides: Optional[Dict[str, str]] = None,
        literario: bool = False,
    ) -> None:
        self.prompts_dir = Path(prompts_dir)
        self.window_start = max(1, window_start)
        self.window_end = max(0, window_end)
        self.literario = bool(literario)
        self.pin_literary_case = False
        self._overrides = sanitize_prompt_overrides(overrides or {})
        self._cache: Dict[str, str] = {}
        shared_name = "_shared_rules_literario.txt" if self.literario else "_shared_rules.txt"
        self._shared_rules = self._read_file(shared_name)

    def should_classify(self, page_number: int, total_pages: int) -> bool:
        if total_pages <= 0 or page_number <= 0:
            return False
        in_start = page_number <= self.window_start
        in_end = page_number >= total_pages - self.window_end + 1
        return in_start or in_end

    def normalize_page_type(self, raw: str) -> str:
        folded = _fold_label(raw or "")
        token = folded.split()[0] if folded else ""
        token = token.strip(".,;:!?\"'")
        allowed = LITERARY_PAGE_TYPES if self.literario else PAGE_TYPES
        if token in allowed:
            return token
        for word in re.findall(r"[a-z0-9_]+", folded):
            if word in allowed:
                return word
        return CONTENT_PAGE_TYPE

    @staticmethod
    def supports_figure_description(page_type: str) -> bool:
        return (page_type or "").strip().lower() == CONTENT_PAGE_TYPE

    @classmethod
    def should_skip_figure_pipeline(cls, page_type: str) -> bool:
        """Só páginas que não são de conteúdo (capa, ficha, sumário) ficam sem descrição de figura."""
        return not cls.supports_figure_description(page_type)

    def resolve_page_type(
        self,
        page_number: int,
        total_pages: int,
        classified_type: Optional[str] = None,
    ) -> str:
        if not self.should_classify(page_number, total_pages):
            return "conteudo"
        if classified_type is None:
            return "conteudo"
        return self.normalize_page_type(classified_type)

    def _literary_prompt(self) -> str:
        if "literario" not in self._cache:
            self._cache["literario"] = (
                self._read_file("literario.txt").replace("{{SHARED_RULES}}", self._shared_rules).strip()
            )
        return self._cache["literario"]

    def get_prompt(self, page_type: str) -> str:
        if self.literario:
            prompt = self._literary_prompt()
            if not self.pin_literary_case:
                return prompt
            normalized = self.normalize_page_type(page_type)
            lock = _LITERARY_CASE_LOCK.get(normalized, _LITERARY_CASE_LOCK[CONTENT_PAGE_TYPE])
            return f"{prompt}\n\n{lock}"

        normalized = self.normalize_page_type(page_type)
        if normalized in self._cache:
            return self._cache[normalized]

        filename = PROMPT_FILES.get(normalized, "base.txt")
        prompt = self._read_file(filename)
        if not prompt and normalized != "conteudo":
            prompt = self._read_file("base.txt")
        prompt = prompt.replace("{{SHARED_RULES}}", self._shared_rules).strip()
        self._cache[normalized] = prompt
        return prompt

    @property
    def classifier_prompt(self) -> str:
        if self.literario:
            return LITERARY_CLASSIFIER_PROMPT
        return self._read_file("classificador.txt")

    def _read_file(self, filename: str) -> str:
        if filename in self._overrides:
            return self._overrides[filename].strip()
        path = self.prompts_dir / filename
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()
