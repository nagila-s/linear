from __future__ import annotations

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


class PromptRouter:
    def __init__(
        self,
        prompts_dir: str,
        *,
        window_start: int = 20,
        window_end: int = 15,
    ) -> None:
        self.prompts_dir = Path(prompts_dir)
        self.window_start = max(1, window_start)
        self.window_end = max(0, window_end)
        self._cache: Dict[str, str] = {}
        self._shared_rules = self._read_file("_shared_rules.txt")

    def should_classify(self, page_number: int, total_pages: int) -> bool:
        if total_pages <= 0 or page_number <= 0:
            return False
        in_start = page_number <= self.window_start
        in_end = page_number >= total_pages - self.window_end + 1
        return in_start or in_end

    def normalize_page_type(self, raw: str) -> str:
        cleaned = (raw or "").strip().lower()
        cleaned = cleaned.split()[0] if cleaned else ""
        cleaned = cleaned.strip(".,;:!?\"'")
        if cleaned in PAGE_TYPES:
            return cleaned
        return CONTENT_PAGE_TYPE

    @staticmethod
    def supports_figure_description(page_type: str) -> bool:
        return (page_type or "").strip().lower() == CONTENT_PAGE_TYPE

    def should_skip_figure_pipeline(
        self,
        page_number: int,
        total_pages: int,
        page_type: str,
    ) -> bool:
        """Capa, prefácio etc. ficam no início/fim; mesmo se classificador errar, não descreve figuras."""
        if not self.supports_figure_description(page_type):
            return True
        return self.should_classify(page_number, total_pages)

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

    def get_prompt(self, page_type: str) -> str:
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
        return self._read_file("classificador.txt")

    def _read_file(self, filename: str) -> str:
        path = self.prompts_dir / filename
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()
