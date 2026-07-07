from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

PAGE_TYPES = frozenset(
    {
        "capa",
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

PROMPT_FILES: Dict[str, str] = {
    "capa": "capa.txt",
    "ficha": "ficha.txt",
    "apresentacao": "apresentacao.txt",
    "conheca": "conheca.txt",
    "sumario": "sumario.txt",
    "hino": "hino.txt",
    "referencias": "referencias.txt",
    "contracapa": "contracapa.txt",
    "conteudo": "base.txt",
}

_SECTION_LINE = re.compile(r"^={10,}\s*$", re.MULTILINE)


def parse_consolidated_prompts(text: str) -> Dict[str, str]:
    """Extrai seções de prompts_especializados.txt (CLASSIFICADOR, PROMPT_CAPA, ...)."""
    parts = _SECTION_LINE.split(text.strip())
    sections: Dict[str, str] = {}
    index = 1
    while index < len(parts):
        name = parts[index].strip()
        body = parts[index + 1].strip() if index + 1 < len(parts) else ""
        key = _section_name_to_key(name)
        if key and body:
            sections[key] = body
        index += 2
    return sections


def _section_name_to_key(name: str) -> Optional[str]:
    normalized = name.strip().upper()
    if normalized == "CLASSIFICADOR":
        return "classificador"
    if normalized.startswith("PROMPT_"):
        return normalized.removeprefix("PROMPT_").lower()
    return None


class PromptRouter:
    def __init__(
        self,
        prompts_dir: str,
        *,
        window_start: int = 20,
        window_end: int = 15,
        legacy_base_prompt: str = "",
        specialized_prompts_file: str = "prompts_especializados.txt",
    ) -> None:
        self.prompts_dir = Path(prompts_dir)
        self.window_start = max(1, window_start)
        self.window_end = max(0, window_end)
        self.legacy_base_prompt = legacy_base_prompt.strip()
        self._cache: Dict[str, str] = {}
        self._shared_rules = self._read_optional("_shared_rules.txt")
        self._consolidated = self._load_consolidated(specialized_prompts_file)

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
        return "conteudo"

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

        if normalized == "conteudo":
            prompt = self._load_base_prompt()
        elif normalized in self._consolidated:
            prompt = self._consolidated[normalized]
        else:
            filename = PROMPT_FILES.get(normalized, "base.txt")
            prompt = self._load_prompt_file(filename)

        prompt = prompt.replace("{{SHARED_RULES}}", self._shared_rules).strip()
        self._cache[normalized] = prompt
        return prompt

    @property
    def classifier_prompt(self) -> str:
        if "classificador" in self._consolidated:
            return self._consolidated["classificador"]
        return self._read_required("classificador.txt")

    def _load_base_prompt(self) -> str:
        base_path = self.prompts_dir / "base.txt"
        if base_path.exists():
            return base_path.read_text(encoding="utf-8").strip()
        if self.legacy_base_prompt:
            return self.legacy_base_prompt
        return self._read_required("base.txt")

    def _load_consolidated(self, specialized_prompts_file: str) -> Dict[str, str]:
        candidates = [
            Path(specialized_prompts_file),
            self.prompts_dir.parent / specialized_prompts_file,
            self.prompts_dir / specialized_prompts_file,
        ]
        for path in candidates:
            if path.is_file():
                return parse_consolidated_prompts(path.read_text(encoding="utf-8"))
        return {}

    def _load_prompt_file(self, filename: str) -> str:
        path = self.prompts_dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return self._load_base_prompt()

    def _read_required(self, filename: str) -> str:
        path = self.prompts_dir / filename
        if not path.exists():
            if filename == "base.txt":
                return self._load_base_prompt()
            raise FileNotFoundError(f"Prompt nao encontrado: {path}")
        return path.read_text(encoding="utf-8").strip()

    def _read_optional(self, filename: str) -> str:
        path = self.prompts_dir / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()
